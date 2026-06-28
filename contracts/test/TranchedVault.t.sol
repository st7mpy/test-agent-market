// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {TranchedVault} from "../src/TranchedVault.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("USD Coin", "USDC") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
    function decimals() public pure override returns (uint8) { return 6; }
}

/// @notice Senior/junior tranching (E, ADR-017): losses hit junior first (senior
/// protected by subordination); yield pays the senior coupon first, junior takes the
/// residual (its upside). Invariant throughout: assetBalance == seniorAssets + juniorAssets.
contract TranchedVaultTest is Test {
    MockUSDC usdc;
    TranchedVault vault;

    address controller = makeAddr("controller");
    address sink       = makeAddr("lossSink");
    address senior     = makeAddr("seniorLP");
    address junior     = makeAddr("juniorLP");

    uint256 constant WAD = 1e18;

    function setUp() public {
        usdc = new MockUSDC();
        // senior coupon = 2% of senior NAV per distribution
        vault = new TranchedVault(IERC20(address(usdc)), controller, sink, 200);
        usdc.mint(senior, 1_000_000e6);
        usdc.mint(junior, 1_000_000e6);
        usdc.mint(controller, 1_000_000e6);
    }

    function _depSenior(uint256 a) internal {
        vm.startPrank(senior); usdc.approve(address(vault), a); vault.depositSenior(a); vm.stopPrank();
    }
    function _depJunior(uint256 a) internal {
        vm.startPrank(junior); usdc.approve(address(vault), a); vault.depositJunior(a); vm.stopPrank();
    }
    function _yield(uint256 a) internal {
        vm.startPrank(controller); usdc.approve(address(vault), a); vault.distributeYield(a); vm.stopPrank();
    }
    function _assertBalanceInvariant() internal view {
        assertEq(usdc.balanceOf(address(vault)), vault.totalAssets(), "balance == senior + junior");
    }

    function testDepositsMintAtParity() public {
        _depSenior(100_000e6);
        _depJunior(50_000e6);
        assertEq(vault.seniorSharePrice(), WAD);
        assertEq(vault.juniorSharePrice(), WAD);
        assertEq(vault.totalAssets(), 150_000e6);
        _assertBalanceInvariant();
    }

    function testYieldPaysSeniorCouponJuniorResidual() public {
        _depSenior(100_000e6);
        _depJunior(50_000e6);

        _yield(10_000e6);                       // senior coupon cap = 2% * 100k = 2k
        assertEq(vault.seniorAssets(), 102_000e6, "senior gets only its 2k coupon");
        assertEq(vault.juniorAssets(), 58_000e6, "junior takes the 8k residual");
        // junior upside: +16% on 50k vs senior +2% on 100k
        assertGt(vault.juniorSharePrice(), vault.seniorSharePrice());
        _assertBalanceInvariant();
    }

    function testLossJuniorFirstProtectsSenior() public {
        _depSenior(100_000e6);
        _depJunior(50_000e6);

        vm.prank(controller);
        uint256 fromSenior = vault.applyLoss(30_000e6);     // < junior buffer

        assertEq(fromSenior, 0, "senior untouched while junior absorbs");
        assertEq(vault.juniorAssets(), 20_000e6);           // 50k - 30k
        assertEq(vault.seniorAssets(), 100_000e6, "senior principal protected");
        assertEq(vault.seniorSharePrice(), WAD);
        assertLt(vault.juniorSharePrice(), WAD);            // junior bore it
        _assertBalanceInvariant();
    }

    function testLossBeyondJuniorHitsSenior() public {
        _depSenior(100_000e6);
        _depJunior(50_000e6);

        vm.prank(controller);
        uint256 fromSenior = vault.applyLoss(70_000e6);     // wipes 50k junior, 20k into senior

        assertEq(fromSenior, 20_000e6);
        assertEq(vault.juniorAssets(), 0, "junior wiped first");
        assertEq(vault.seniorAssets(), 80_000e6);
        assertEq(vault.juniorSharePrice(), 0);
        _assertBalanceInvariant();
    }

    function testWithdrawAtGrownNav() public {
        _depSenior(100_000e6);
        _depJunior(50_000e6);
        _yield(10_000e6);                       // junior NAV 50k -> 58k

        uint256 before = usdc.balanceOf(junior);
        uint256 shares = vault.juniorShares(junior);
        vm.prank(junior);
        vault.withdrawJunior(shares);
        assertEq(usdc.balanceOf(junior) - before, 58_000e6, "junior redeems grown NAV");
        assertEq(vault.juniorAssets(), 0);
        _assertBalanceInvariant();
    }

    function testWaterfallsAreControllerOnly() public {
        _depSenior(10_000e6);
        _depJunior(10_000e6);
        vm.expectRevert(bytes("!controller"));
        vault.applyLoss(1_000e6);
        vm.startPrank(senior);
        usdc.approve(address(vault), 1_000e6);
        vm.expectRevert(bytes("!controller"));
        vault.distributeYield(1_000e6);
        vm.stopPrank();
    }

    function testSequenceKeepsBalanceInvariant() public {
        _depSenior(100_000e6);
        _depJunior(40_000e6);
        _yield(5_000e6);
        vm.prank(controller); vault.applyLoss(20_000e6);
        _yield(3_000e6);
        vm.prank(controller); vault.applyLoss(60_000e6);   // beyond junior -> hits senior
        _assertBalanceInvariant();
        assertEq(vault.juniorAssets(), 0);
        assertGt(vault.seniorAssets(), 0);
    }
}
