// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

/// @title TranchedVault
/// @notice Phase-6 structured-product vault (differentiator E): depositor capital is
///         split into a **senior** tranche (principal-protected by subordination,
///         steady yield-priority) and a **junior** tranche (first-loss, levered upside).
///         It generalizes the maker first-loss / loss-waterfall idea (ADR-015) to the
///         *depositor* side, widening the funnel to conservative capital.
///
/// Mechanics (ADR-017):
///   * Losses hit **junior first**, then senior — so senior principal is protected as
///     long as the junior buffer has value (no tranche is *absolutely* principal-
///     protected; protection = subordination).
///   * Yield pays the **senior coupon first** (a capped priority cut of each
///     distribution), and the **junior takes the residual** — so junior earns the
///     upside it's compensated for by bearing first loss.
///   * `distributeYield` pulls USDC in (real gains, e.g. from the market-neutral
///     venue-yield, B); `applyLoss` sends the absorbed amount to `lossSink` (the
///     capital is gone). Both are controller-only on the authoritative accounting,
///     so the invariant `assetBalance == seniorAssets + juniorAssets` always holds.
///
/// @dev  ⚠️ NOT EXTERNALLY AUDITED. SKELETON: tranche shares are internal balances
///       (non-transferable), not ERC20/ERC4626; first-depositor share-inflation
///       hardening and per-tranche fee/HWM are out of scope here.
contract TranchedVault {
    using SafeERC20 for IERC20;

    IERC20 public immutable asset;
    address public owner;
    address public controller;             // platform accounting; only it applies yield/loss
    address public immutable lossSink;     // where absorbed-loss USDC goes (capital is gone)
    uint256 public immutable seniorCouponBps; // senior's priority cut per distribution (fixed at issuance)

    uint256 public seniorAssets;        // senior tranche NAV (asset units)
    uint256 public juniorAssets;        // junior tranche NAV (asset units)
    uint256 public totalSeniorShares;
    uint256 public totalJuniorShares;
    mapping(address => uint256) public seniorShares;
    mapping(address => uint256) public juniorShares;

    uint256 internal constant WAD = 1e18;
    uint256 internal constant BPS = 10_000;

    event SeniorDeposited(address indexed who, uint256 assets, uint256 shares);
    event JuniorDeposited(address indexed who, uint256 assets, uint256 shares);
    event SeniorWithdrawn(address indexed who, uint256 assets, uint256 shares);
    event JuniorWithdrawn(address indexed who, uint256 assets, uint256 shares);
    event YieldDistributed(uint256 amount, uint256 toSenior, uint256 toJunior);
    event LossApplied(uint256 loss, uint256 fromJunior, uint256 fromSenior);
    event ControllerUpdated(address indexed oldController, address indexed newController);
    event OwnershipTransferred(address indexed oldOwner, address indexed newOwner);

    modifier onlyOwner() { require(msg.sender == owner, "!owner"); _; }
    modifier onlyController() { require(msg.sender == controller, "!controller"); _; }

    constructor(IERC20 asset_, address controller_, address lossSink_, uint256 seniorCouponBps_) {
        require(address(asset_) != address(0) && controller_ != address(0) && lossSink_ != address(0), "zero addr");
        require(seniorCouponBps_ <= BPS, "coupon>100%");
        asset = asset_;
        owner = msg.sender;
        controller = controller_;
        lossSink = lossSink_;
        seniorCouponBps = seniorCouponBps_;
    }

    // --- NAV views ------------------------------------------------------ //
    function totalAssets() public view returns (uint256) { return seniorAssets + juniorAssets; }

    function seniorSharePrice() public view returns (uint256) {
        return totalSeniorShares == 0 ? WAD : Math.mulDiv(seniorAssets, WAD, totalSeniorShares);
    }

    function juniorSharePrice() public view returns (uint256) {
        return totalJuniorShares == 0 ? WAD : Math.mulDiv(juniorAssets, WAD, totalJuniorShares);
    }

    // --- deposits (mint tranche shares at current NAV) ------------------ //
    function depositSenior(uint256 assets) external returns (uint256 shares) {
        shares = totalSeniorShares == 0 ? assets : Math.mulDiv(assets, totalSeniorShares, seniorAssets);
        asset.safeTransferFrom(msg.sender, address(this), assets);
        seniorAssets += assets;
        totalSeniorShares += shares;
        seniorShares[msg.sender] += shares;
        emit SeniorDeposited(msg.sender, assets, shares);
    }

    function depositJunior(uint256 assets) external returns (uint256 shares) {
        shares = totalJuniorShares == 0 ? assets : Math.mulDiv(assets, totalJuniorShares, juniorAssets);
        asset.safeTransferFrom(msg.sender, address(this), assets);
        juniorAssets += assets;
        totalJuniorShares += shares;
        juniorShares[msg.sender] += shares;
        emit JuniorDeposited(msg.sender, assets, shares);
    }

    // --- withdrawals (burn shares at current NAV) ----------------------- //
    function withdrawSenior(uint256 shares) external returns (uint256 assets) {
        require(shares > 0 && shares <= seniorShares[msg.sender], "shares");
        assets = Math.mulDiv(shares, seniorAssets, totalSeniorShares);
        seniorShares[msg.sender] -= shares;
        totalSeniorShares -= shares;
        seniorAssets -= assets;
        asset.safeTransfer(msg.sender, assets);
        emit SeniorWithdrawn(msg.sender, assets, shares);
    }

    function withdrawJunior(uint256 shares) external returns (uint256 assets) {
        require(shares > 0 && shares <= juniorShares[msg.sender], "shares");
        assets = Math.mulDiv(shares, juniorAssets, totalJuniorShares);
        juniorShares[msg.sender] -= shares;
        totalJuniorShares -= shares;
        juniorAssets -= assets;
        asset.safeTransfer(msg.sender, assets);
        emit JuniorWithdrawn(msg.sender, assets, shares);
    }

    // --- waterfalls (controller-only, authoritative accounting) --------- //

    /// @notice Distribute realized yield: senior coupon first, junior takes the residual.
    function distributeYield(uint256 amount) external onlyController {
        asset.safeTransferFrom(msg.sender, address(this), amount);
        uint256 seniorCut = Math.mulDiv(seniorAssets, seniorCouponBps, BPS);
        uint256 toSenior = amount < seniorCut ? amount : seniorCut;
        seniorAssets += toSenior;
        juniorAssets += amount - toSenior;
        emit YieldDistributed(amount, toSenior, amount - toSenior);
    }

    /// @notice Apply a realized loss: junior absorbs first, then senior. The absorbed
    /// USDC is sent to `lossSink` (the capital is gone), keeping balance == NAV.
    function applyLoss(uint256 loss) external onlyController returns (uint256 fromSenior) {
        uint256 fromJunior = loss > juniorAssets ? juniorAssets : loss;
        juniorAssets -= fromJunior;
        uint256 remaining = loss - fromJunior;
        fromSenior = remaining > seniorAssets ? seniorAssets : remaining;
        seniorAssets -= fromSenior;
        uint256 absorbed = fromJunior + fromSenior;
        if (absorbed > 0) asset.safeTransfer(lossSink, absorbed);
        emit LossApplied(loss, fromJunior, fromSenior);
    }

    // --- admin ---------------------------------------------------------- //
    function setController(address c) external onlyOwner {
        require(c != address(0), "zero addr");
        emit ControllerUpdated(controller, c);
        controller = c;
    }

    function transferOwnership(address o) external onlyOwner {
        require(o != address(0), "zero addr");
        emit OwnershipTransferred(owner, o);
        owner = o;
    }
}
