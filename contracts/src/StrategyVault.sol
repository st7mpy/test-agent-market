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
/// @dev  ⚠️ SKELETON — NOT AUDITED, NOT COMPILED in-session, NOT FOR PRODUCTION.
///       Deliberate simplifications, flagged inline with `SKELETON:`:
///       (1) the maker bond + first-loss sit in the vault but are excluded from
///           `totalAssets()` so they do not distort depositor share price;
///       (2) true junior/senior LOSS-WATERFALL accounting (first-loss absorbing
///           strategy losses before depositors) requires integration with
///           settlement and is left as a documented stub (`_applyLoss`). This is
///           the open question called out in DESIGN.md §11.
contract StrategyVault is ERC4626 {
    using SafeERC20 for IERC20;

    // --- roles --------------------------------------------------------- //
    address public owner;            // governance
    address public maker;            // strategy author (posts first-loss + bond)
    address public riskGate;         // the ONLY address allowed to slash (ADR-006)
    address public capacityOracle;   // sets the dynamic capacity cap (ADR-007)
    address public protocolTreasury; // receives the protocol's cut of the fee

    // --- economics ----------------------------------------------------- //
    uint256 public highWaterMarkPPS;    // per-share HWM, WAD-scaled (ADR-004)
    uint256 public capacityCap;         // max depositor assets (ADR-007)
    uint256 public minCoInvestRatioBps; // first-loss >= ratio * depositorAssets (ADR-005)
    uint256 public protocolFeeShareBps; // protocol's cut of the performance fee

    // --- maker skin-in-the-game (excluded from share NAV) -------------- //
    uint256 public makerFirstLoss;      // junior tranche (asset units)
    uint256 public makerBond;           // locked, slashable (asset units)

    uint256 internal constant WAD = 1e18;
    uint256 internal constant BPS = 10_000;

    // --- events -------------------------------------------------------- //
    event CapacityCapSet(uint256 cap);
    event FirstLossDeposited(uint256 assets);
    event BondPosted(uint256 assets);
    event FeeCrystallized(uint256 feeAssets, uint256 makerShares, uint256 protocolShares, uint256 newHwmPPS);
    event Slashed(uint256 amount, address indexed beneficiary, string reason);

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
    // NAV: exclude maker bond + first-loss so they don't inflate share price.
    // SKELETON: a production design would escrow these outside the vault.
    // ------------------------------------------------------------------ //
    function totalAssets() public view override returns (uint256) {
        uint256 bal = IERC20(asset()).balanceOf(address(this));
        uint256 reserved = makerBond + makerFirstLoss;
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

    /// @dev SKELETON: junior loss-waterfall (first-loss absorbs strategy losses
    /// before depositors). Real implementation requires settlement integration.
    function _applyLoss(uint256 /*lossAssets*/) internal pure {
        revert("SKELETON: loss-waterfall not implemented");
    }

    // ------------------------------------------------------------------ //
    // Admin
    // ------------------------------------------------------------------ //
    function setCapacityCap(uint256 cap) external onlyCapacityOracle {
        capacityCap = cap;
        emit CapacityCapSet(cap);
    }

    function setRiskGate(address g) external onlyOwner { riskGate = g; }
    function setMinCoInvestRatioBps(uint256 b) external onlyOwner { minCoInvestRatioBps = b; }
    function setProtocolFeeShareBps(uint256 b) external onlyOwner { protocolFeeShareBps = b; }
    function transferOwnership(address o) external onlyOwner { owner = o; }
}
