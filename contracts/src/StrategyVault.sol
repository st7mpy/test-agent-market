// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {ERC4626} from "@openzeppelin/contracts/token/ERC20/extensions/ERC4626.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

/// @title StrategyVault
/// @notice Phase-2 ERC-4626 vault SKELETON for the prediction-market quant
///         marketplace. Implements the value-capture + alignment mechanics from
///         docs/DESIGN.md and docs/ARCHITECTURE.md (ADR-004/005/006/007):
///           * profit-only performance fee with a per-share high-water mark;
///           * TVL-tiered fee rate;
///           * maker first-loss co-investment + a slashable bond;
///           * dynamic capacity cap (set by the off-chain Capacity Oracle);
///           * mechanical slashing callable ONLY by the RiskGate.
///
/// @dev  ⚠️ NOT EXTERNALLY AUDITED, NOT FOR PRODUCTION (compiles + tested under Foundry).
///       Deliberate simplifications, flagged inline with `SKELETON:`:
///       (1) the maker bond + first-loss + insurance fund sit in the vault but are
///           excluded from `totalAssets()` so they do not distort depositor share price;
///           a production design may escrow them externally.
///       The junior/senior LOSS-WATERFALL (DESIGN.md §11) is now implemented:
///       `applyStrategyLoss` (first-loss → bond → depositors) and `coverOracleLoss`
///       (insurance fund → depositors) — both RiskGate-only, driven by the authoritative
///       off-chain loss measurement (ADR-011/015). The loss amount is trusted input, so
///       these are privileged and must be called only against a reconciled realized loss.
contract StrategyVault is ERC4626 {
    using SafeERC20 for IERC20;

    // --- roles --------------------------------------------------------- //
    address public owner;                // governance
    address public immutable maker;      // strategy author (posts first-loss + bond); fixed per vault
    address public riskGate;             // the ONLY address allowed to slash (ADR-006)
    address public capacityOracle;       // sets the dynamic capacity cap (ADR-007)
    address public protocolTreasury;     // receives the protocol's cut of the fee

    // --- economics ----------------------------------------------------- //
    uint256 public highWaterMarkPPS;    // per-share HWM, WAD-scaled (ADR-004)
    uint256 public capacityCap;         // max depositor assets (ADR-007)
    uint256 public minCoInvestRatioBps; // first-loss >= ratio * depositorAssets (ADR-005)
    uint256 public protocolFeeShareBps; // protocol's cut of the performance fee

    // --- maker skin-in-the-game (excluded from share NAV) -------------- //
    uint256 public makerFirstLoss;      // junior tranche (asset units)
    uint256 public makerBond;           // locked, slashable (asset units)

    // --- depositor insurance fund (excluded from share NAV) ------------ //
    uint256 public insuranceFund;       // oracle-failure backstop (ADR-014/015)

    uint256 internal constant WAD = 1e18;
    uint256 internal constant BPS = 10_000;

    // --- events -------------------------------------------------------- //
    event CapacityCapSet(uint256 cap);
    event FirstLossDeposited(uint256 assets);
    event BondPosted(uint256 assets);
    event FeeCrystallized(uint256 feeAssets, uint256 makerShares, uint256 protocolShares, uint256 newHwmPPS);
    event Slashed(uint256 amount, address indexed beneficiary, string reason);
    event RiskGateUpdated(address indexed oldGate, address indexed newGate);
    event CapacityOracleUpdated(address indexed oldOracle, address indexed newOracle);
    event ProtocolTreasuryUpdated(address indexed oldTreasury, address indexed newTreasury);
    event OwnershipTransferred(address indexed oldOwner, address indexed newOwner);
    event MinCoInvestRatioUpdated(uint256 oldBps, uint256 newBps);
    event ProtocolFeeShareUpdated(uint256 oldBps, uint256 newBps);
    event InsuranceFunded(address indexed from, uint256 assets);
    event SlashedToInsurance(uint256 amount, string reason);
    event StrategyLossApplied(uint256 loss, uint256 fromFirstLoss, uint256 fromBond, uint256 residualToDepositors);
    event OracleLossCovered(uint256 loss, uint256 fromInsurance, uint256 residualToDepositors);

    modifier onlyOwner() { require(msg.sender == owner, "!owner"); _; }
    modifier onlyRiskGate() { require(msg.sender == riskGate, "!riskGate"); _; }
    modifier onlyCapacityOracle() { require(msg.sender == capacityOracle, "!oracle"); _; }

    constructor(
        IERC20 asset_,
        string memory name_,
        string memory symbol_,
        address maker_,
        address riskGate_,
        address capacityOracle_,
        address treasury_
    ) ERC20(name_, symbol_) ERC4626(asset_) {
        require(
            maker_ != address(0) && riskGate_ != address(0) &&
            capacityOracle_ != address(0) && treasury_ != address(0),
            "zero addr"
        );
        owner = msg.sender;
        maker = maker_;
        riskGate = riskGate_;
        capacityOracle = capacityOracle_;
        protocolTreasury = treasury_;
        highWaterMarkPPS = WAD;          // 1 share == 1 asset at inception
        minCoInvestRatioBps = 500;       // 5%
        protocolFeeShareBps = 1500;      // protocol takes 15% of the perf fee
        capacityCap = type(uint256).max; // raised/lowered by the oracle
    }

    // ------------------------------------------------------------------ //
    // NAV: exclude maker bond + first-loss + insurance fund so reserved
    // capital doesn't inflate depositor share price.
    // SKELETON: a production design would escrow these outside the vault.
    // ------------------------------------------------------------------ //
    function totalAssets() public view override returns (uint256) {
        uint256 bal = IERC20(asset()).balanceOf(address(this));
        uint256 reserved = makerBond + makerFirstLoss + insuranceFund;
        return bal > reserved ? bal - reserved : 0;
    }

    function pricePerShare() public view returns (uint256) {
        uint256 supply = totalSupply();
        return supply == 0 ? WAD : Math.mulDiv(totalAssets(), WAD, supply);
    }

    /// @notice TVL-tiered performance-fee rate (assumes 6-decimal USDC).
    function performanceFeeBps() public view returns (uint256) {
        uint256 tvl = totalAssets();
        if (tvl < 100_000e6) return 500;       // $0–100k   -> 5%
        if (tvl < 500_000e6) return 1000;      // $100k–500k-> 10%
        if (tvl < 2_000_000e6) return 1500;    // $500k–2M  -> 15%
        return 2000;                            // $2M+      -> 20%
    }

    function depositorAssets() public view returns (uint256) {
        return totalAssets(); // bond + first-loss already excluded above
    }

    // ------------------------------------------------------------------ //
    // Maker skin-in-the-game (ADR-005)
    // ------------------------------------------------------------------ //
    function depositFirstLoss(uint256 assets) external {
        require(msg.sender == maker, "!maker");
        IERC20(asset()).safeTransferFrom(msg.sender, address(this), assets);
        makerFirstLoss += assets;
        emit FirstLossDeposited(assets);
    }

    function postBond(uint256 assets) external {
        require(msg.sender == maker, "!maker");
        IERC20(asset()).safeTransferFrom(msg.sender, address(this), assets);
        makerBond += assets;
        emit BondPosted(assets);
    }

    // ------------------------------------------------------------------ //
    // Depositor insurance fund (ADR-014/015) — the oracle-failure backstop.
    // Funded by the protocol (and slashing proceeds, see `slashToInsurance`);
    // permissionless top-up so anyone can bolster depositor protection.
    // ------------------------------------------------------------------ //
    function fundInsurance(uint256 assets) external {
        IERC20(asset()).safeTransferFrom(msg.sender, address(this), assets);
        insuranceFund += assets;
        emit InsuranceFunded(msg.sender, assets);
    }

    // ------------------------------------------------------------------ //
    // ERC-4626 entry/exit hooks: crystallize fee, enforce capacity + ratio
    // ------------------------------------------------------------------ //
    function deposit(uint256 assets, address receiver) public override returns (uint256) {
        _crystallizeFee();
        _enforceEntry(assets);
        return super.deposit(assets, receiver);
    }

    function mint(uint256 shares, address receiver) public override returns (uint256) {
        _crystallizeFee();
        _enforceEntry(previewMint(shares));
        return super.mint(shares, receiver);
    }

    function withdraw(uint256 assets, address receiver, address ownr) public override returns (uint256) {
        _crystallizeFee();
        return super.withdraw(assets, receiver, ownr);
    }

    function redeem(uint256 shares, address receiver, address ownr) public override returns (uint256) {
        _crystallizeFee();
        return super.redeem(shares, receiver, ownr);
    }

    function _enforceEntry(uint256 incomingAssets) internal view {
        require(depositorAssets() + incomingAssets <= capacityCap, "capacity cap");
        uint256 newDepositor = depositorAssets() + incomingAssets;
        // first-loss must cover the minimum co-investment ratio AFTER this deposit
        require(makerFirstLoss * BPS >= newDepositor * minCoInvestRatioBps, "co-invest ratio");
    }

    // ------------------------------------------------------------------ //
    // Profit-only performance fee with high-water mark (ADR-004)
    // ------------------------------------------------------------------ //
    function crystallizeFee() external returns (uint256) {
        return _crystallizeFee();
    }

    function _crystallizeFee() internal returns (uint256 feeAssets) {
        uint256 supply = totalSupply();
        if (supply == 0) return 0;
        uint256 pps = pricePerShare();
        if (pps <= highWaterMarkPPS) return 0;                 // profit-only

        uint256 profitAssets = Math.mulDiv(pps - highWaterMarkPPS, supply, WAD);
        feeAssets = Math.mulDiv(profitAssets, performanceFeeBps(), BPS);
        if (feeAssets == 0) return 0;

        // charge the fee by minting dilutive shares to maker + protocol
        uint256 feeShares = previewDeposit(feeAssets);
        uint256 protocolShares = Math.mulDiv(feeShares, protocolFeeShareBps, BPS);
        uint256 makerShares = feeShares - protocolShares;
        if (makerShares > 0) _mint(maker, makerShares);
        if (protocolShares > 0) _mint(protocolTreasury, protocolShares);

        highWaterMarkPPS = pricePerShare();                    // reset HWM post-dilution
        emit FeeCrystallized(feeAssets, makerShares, protocolShares, highWaterMarkPPS);
    }

    // ------------------------------------------------------------------ //
    // Mechanical slashing — RiskGate only (ADR-006). Waterfall: bond first,
    // then first-loss; proceeds compensate affected depositors / insurance.
    // ------------------------------------------------------------------ //
    function slash(uint256 amount, address beneficiary, string calldata reason)
        external
        onlyRiskGate
    {
        uint256 fromBond = amount > makerBond ? makerBond : amount;
        makerBond -= fromBond;
        uint256 remaining = amount - fromBond;
        uint256 fromFL = remaining > makerFirstLoss ? makerFirstLoss : remaining;
        makerFirstLoss -= fromFL;

        uint256 paid = fromBond + fromFL;
        if (paid > 0) IERC20(asset()).safeTransfer(beneficiary, paid);
        emit Slashed(paid, beneficiary, reason);
    }

    /// @notice Slash the maker (bond first, then first-loss) and route the proceeds
    /// INTO the insurance fund instead of paying an external beneficiary. The USDC
    /// stays in the contract — it's reclassified from maker-reserved to the depositor
    /// backstop — so it grows the fund without a transfer. RiskGate only (ADR-006).
    function slashToInsurance(uint256 amount, string calldata reason)
        external
        onlyRiskGate
        returns (uint256 moved)
    {
        uint256 fromBond = amount > makerBond ? makerBond : amount;
        makerBond -= fromBond;
        uint256 remaining = amount - fromBond;
        uint256 fromFL = remaining > makerFirstLoss ? makerFirstLoss : remaining;
        makerFirstLoss -= fromFL;

        moved = fromBond + fromFL;
        insuranceFund += moved;
        emit SlashedToInsurance(moved, reason);
    }

    // ------------------------------------------------------------------ //
    // Realized-loss waterfalls (DESIGN.md §11, ADR-015). RiskGate-only; the loss
    // amount is the authoritative off-chain measurement (ADR-011). Each reduces the
    // appropriate reserved bucket so `totalAssets` keeps depositors whole up to the
    // bucket's size — the residual (buckets exhausted) is what depositors bear.
    // ------------------------------------------------------------------ //

    /// @notice A maker STRATEGY loss: the junior first-loss absorbs first, then the
    /// bond, then depositors (ADR-005). This is the maker eating their own mistakes.
    function applyStrategyLoss(uint256 lossAssets)
        external
        onlyRiskGate
        returns (uint256 residualToDepositors)
    {
        uint256 fromFL = lossAssets > makerFirstLoss ? makerFirstLoss : lossAssets;
        makerFirstLoss -= fromFL;
        uint256 remaining = lossAssets - fromFL;
        uint256 fromBond = remaining > makerBond ? makerBond : remaining;
        makerBond -= fromBond;
        residualToDepositors = remaining - fromBond;
        emit StrategyLossApplied(lossAssets, fromFL, fromBond, residualToDepositors);
    }

    /// @notice An ORACLE-FAILURE loss (not the maker's fault): the insurance fund
    /// absorbs it, protecting depositors up to the fund's size. The maker's
    /// alignment capital is deliberately NOT raided for a non-maker-fault event;
    /// any shortfall beyond the fund is borne by depositors (a fund-sizing problem).
    function coverOracleLoss(uint256 lossAssets)
        external
        onlyRiskGate
        returns (uint256 residualToDepositors)
    {
        uint256 fromIns = lossAssets > insuranceFund ? insuranceFund : lossAssets;
        insuranceFund -= fromIns;
        residualToDepositors = lossAssets - fromIns;
        emit OracleLossCovered(lossAssets, fromIns, residualToDepositors);
    }

    // ------------------------------------------------------------------ //
    // Admin
    // ------------------------------------------------------------------ //
    function setCapacityCap(uint256 cap) external onlyCapacityOracle {
        capacityCap = cap;
        emit CapacityCapSet(cap);
    }

    function setRiskGate(address g) external onlyOwner {
        require(g != address(0), "zero addr");
        emit RiskGateUpdated(riskGate, g);
        riskGate = g;
    }

    function setCapacityOracle(address o) external onlyOwner {
        require(o != address(0), "zero addr");
        emit CapacityOracleUpdated(capacityOracle, o);
        capacityOracle = o;
    }

    function setProtocolTreasury(address t) external onlyOwner {
        require(t != address(0), "zero addr");
        emit ProtocolTreasuryUpdated(protocolTreasury, t);
        protocolTreasury = t;
    }

    function setMinCoInvestRatioBps(uint256 b) external onlyOwner {
        emit MinCoInvestRatioUpdated(minCoInvestRatioBps, b);
        minCoInvestRatioBps = b;
    }

    function setProtocolFeeShareBps(uint256 b) external onlyOwner {
        require(b <= BPS, "bps>100%");          // protocol cut is a fraction of the fee
        emit ProtocolFeeShareUpdated(protocolFeeShareBps, b);
        protocolFeeShareBps = b;
    }

    function transferOwnership(address o) external onlyOwner {
        require(o != address(0), "zero addr");
        emit OwnershipTransferred(owner, o);
        owner = o;
    }
}
