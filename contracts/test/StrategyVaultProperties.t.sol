// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {StrategyVault} from "../src/StrategyVault.sol";

contract MockUSDC is ERC20 {
    constructor() ERC20("USD Coin", "USDC") {}
    function mint(address to, uint256 amt) external { _mint(to, amt); }
    function decimals() public pure override returns (uint8) { return 6; }
}

/// @notice Money-path correctness vectors for the Phase-2/3 checkpoint
///         (PLAN.md §3): the performance fee must crystallize correctly across
///         deposits, withdrawals, AND a drawdown — the high-water mark must
///         never double-charge a recovery. Plus slash-waterfall spill/cap and
///         co-invest-ratio gating across multiple deposits.
///
/// These complement the happy-path checks in StrategyVault.t.sol with the
/// adversarial vectors the plan calls out as non-negotiable before real money.
contract StrategyVaultPropertiesTest is Test {
    MockUSDC usdc;
    StrategyVault vault;

    address maker    = makeAddr("maker");
    address riskGate = makeAddr("riskGate");
    address oracle   = makeAddr("oracle");
    address treasury = makeAddr("treasury");
    address alice    = makeAddr("alice");
    address burn     = address(0xdead);

    function setUp() public {
        usdc = new MockUSDC();
        vault = new StrategyVault(IERC20(address(usdc)), "PM Vault", "pmVLT",
                                  maker, riskGate, oracle, treasury);
        usdc.mint(maker, 1_000_000e6);
        usdc.mint(alice, 1_000_000e6);
        vm.prank(oracle);
        vault.setCapacityCap(1_000_000e6);
    }

    // --- helpers ---------------------------------------------------------- //
    function _firstLoss(uint256 amt) internal {
        vm.startPrank(maker);
        usdc.approve(address(vault), amt);
        vault.depositFirstLoss(amt);
        vm.stopPrank();
    }

    function _bond(uint256 amt) internal {
        vm.startPrank(maker);
        usdc.approve(address(vault), amt);
        vault.postBond(amt);
        vm.stopPrank();
    }

    function _deposit(address who, uint256 amt) internal {
        vm.startPrank(who);
        usdc.approve(address(vault), amt);
        vault.deposit(amt, who);
        vm.stopPrank();
    }

    /// Simulate a strategy gain: USDC appears in the vault (e.g. a winning resolution).
    function _gain(uint256 amt) internal { usdc.mint(address(vault), amt); }

    /// Simulate a strategy loss: USDC leaves the vault (e.g. a losing resolution).
    function _loss(uint256 amt) internal {
        vm.prank(address(vault));
        usdc.transfer(burn, amt);
    }

    // --------------------------------------------------------------------- //
    // THE KEY INVARIANT: HWM never double-charges a recovery.
    // --------------------------------------------------------------------- //
    function testNoDoubleChargeAcrossDrawdown() public {
        _firstLoss(50_000e6);          // generous, supports the deposit + ratio
        _deposit(alice, 100_000e6);

        // (1) first profit -> fee is charged, HWM rises
        _gain(20_000e6);               // +20%
        uint256 makerBefore = vault.balanceOf(maker);
        vault.crystallizeFee();
        uint256 makerAfterFirstFee = vault.balanceOf(maker);
        assertGt(makerAfterFirstFee, makerBefore, "maker should earn fee on first profit");
        uint256 hwm1 = vault.highWaterMarkPPS();

        // (2) drawdown below HWM -> no fee
        _loss(15_000e6);
        vault.crystallizeFee();
        assertEq(vault.balanceOf(maker), makerAfterFirstFee, "no fee during drawdown");

        // (3) partial recovery, still below HWM -> STILL no fee (the no-double-charge property)
        _gain(14_000e6);
        assertLe(vault.pricePerShare(), hwm1, "precondition: still under prior HWM");
        vault.crystallizeFee();
        assertEq(vault.balanceOf(maker), makerAfterFirstFee, "no fee on recovery up to old HWM");

        // (4) a genuine NEW high above the prior HWM -> fee resumes, on new profit only
        _gain(30_000e6);
        assertGt(vault.pricePerShare(), hwm1, "precondition: now above prior HWM");
        vault.crystallizeFee();
        assertGt(vault.balanceOf(maker), makerAfterFirstFee, "fee resumes on new high");
    }

    // A second crystallization with no new profit must be a no-op (idempotent).
    function testCrystallizeIdempotentWithoutNewProfit() public {
        _firstLoss(50_000e6);
        _deposit(alice, 100_000e6);
        _gain(10_000e6);
        vault.crystallizeFee();
        uint256 m = vault.balanceOf(maker);
        vault.crystallizeFee();
        vault.crystallizeFee();
        assertEq(vault.balanceOf(maker), m, "repeat crystallize without profit is a no-op");
    }

    // --------------------------------------------------------------------- //
    // Withdrawal NAV correctness (PLAN.md §2/§3: clean withdraw at correct NAV)
    // --------------------------------------------------------------------- //
    function testFlatDepositWithdrawNoFeeNoLoss() public {
        _firstLoss(50_000e6);
        uint256 start = usdc.balanceOf(alice);
        _deposit(alice, 100_000e6);

        // no profit -> crystallize charges nothing
        vault.crystallizeFee();
        assertEq(vault.balanceOf(maker), 0, "no fee on a flat vault");

        // full redeem returns principal (within rounding) and never touches maker capital
        uint256 shares = vault.balanceOf(alice);
        vm.prank(alice);
        vault.redeem(shares, alice, alice);
        assertApproxEqAbs(usdc.balanceOf(alice), start, 2, "depositor gets principal back");
        assertEq(vault.makerFirstLoss(), 50_000e6, "first-loss untouched by a depositor withdrawal");
    }

    function testProfitThenWithdrawNetsProfitMinusFee() public {
        _firstLoss(50_000e6);
        uint256 start = usdc.balanceOf(alice);
        _deposit(alice, 100_000e6);
        _gain(20_000e6);                       // +20% before fee

        uint256 shares = vault.balanceOf(alice);
        vm.prank(alice);
        vault.redeem(shares, alice, alice);     // redeem crystallizes fee first

        uint256 finalBal = usdc.balanceOf(alice);
        assertGt(finalBal, start, "depositor keeps net profit");
        assertLt(finalBal, start + 20_000e6, "maker took a performance-fee cut of the profit");
        assertGt(vault.balanceOf(maker), 0, "maker holds fee shares");
    }

    // --------------------------------------------------------------------- //
    // Slash waterfall: bond first, then first-loss, capped (no underflow).
    // --------------------------------------------------------------------- //
    function testSlashSpillsFromBondIntoFirstLoss() public {
        _firstLoss(10_000e6);
        _bond(5_000e6);

        vm.prank(riskGate);
        vault.slash(8_000e6, treasury, "drawdown breach");   // 5k bond + 3k first-loss

        assertEq(vault.makerBond(), 0, "bond drained first");
        assertEq(vault.makerFirstLoss(), 7_000e6, "remainder taken from first-loss");
        assertEq(usdc.balanceOf(treasury), 8_000e6, "beneficiary paid the full slash");
    }

    function testSlashCapsAtBondPlusFirstLossNoUnderflow() public {
        _firstLoss(10_000e6);
        _bond(5_000e6);

        vm.prank(riskGate);
        vault.slash(99_000e6, treasury, "catastrophic");     // asks for more than exists

        assertEq(vault.makerBond(), 0);
        assertEq(vault.makerFirstLoss(), 0);
        assertEq(usdc.balanceOf(treasury), 15_000e6, "paid is capped at bond + first-loss");
    }

    // --------------------------------------------------------------------- //
    // Co-invest ratio holds as depositors enter (invariant #5).
    // --------------------------------------------------------------------- //
    function testCoInvestRatioBlocksGrowthBeyondFirstLoss() public {
        // default ratio is 5%
        _firstLoss(5_000e6);            // supports exactly 100k of depositor assets
        _deposit(alice, 100_000e6);     // 5k >= 5% * 100k -> ok at the boundary
        assertEq(vault.depositorAssets(), 100_000e6);

        // a further deposit needs more first-loss; without it, it must revert
        vm.startPrank(alice);
        usdc.approve(address(vault), 10_000e6);
        vm.expectRevert(bytes("co-invest ratio"));
        vault.deposit(10_000e6, alice);
        vm.stopPrank();

        // top up first-loss, then the same deposit succeeds
        _firstLoss(1_000e6);            // 6k first-loss supports 110k+ at 5%
        _deposit(alice, 10_000e6);
        assertEq(vault.depositorAssets(), 110_000e6);
    }

    // --------------------------------------------------------------------- //
    // Admin hardening (Slither follow-ups): zero-checks, rotation, bounds.
    // --------------------------------------------------------------------- //
    function testRoleSettersRejectZeroAddress() public {
        vm.startPrank(address(this)); // deployer is owner
        vm.expectRevert(bytes("zero addr"));
        vault.setRiskGate(address(0));
        vm.expectRevert(bytes("zero addr"));
        vault.setCapacityOracle(address(0));
        vm.expectRevert(bytes("zero addr"));
        vault.setProtocolTreasury(address(0));
        vm.expectRevert(bytes("zero addr"));
        vault.transferOwnership(address(0));
        vm.stopPrank();
    }

    function testRotateOracleAndTreasury() public {
        address newOracle = makeAddr("newOracle");
        address newTreasury = makeAddr("newTreasury");
        vault.setCapacityOracle(newOracle);
        vault.setProtocolTreasury(newTreasury);
        assertEq(vault.capacityOracle(), newOracle);
        assertEq(vault.protocolTreasury(), newTreasury);

        // the old oracle can no longer set the cap; the new one can
        vm.prank(oracle);
        vm.expectRevert(bytes("!oracle"));
        vault.setCapacityCap(123);
        vm.prank(newOracle);
        vault.setCapacityCap(123);
        assertEq(vault.capacityCap(), 123);
    }

    function testProtocolFeeShareBounded() public {
        vault.setProtocolFeeShareBps(3000);             // 30% of the fee -> ok
        assertEq(vault.protocolFeeShareBps(), 3000);
        vm.expectRevert(bytes("bps>100%"));
        vault.setProtocolFeeShareBps(10_001);           // > 100% of the fee -> reject
    }

    function testOnlyOwnerCanAdminister() public {
        vm.startPrank(alice);
        vm.expectRevert(bytes("!owner"));
        vault.setRiskGate(alice);
        vm.expectRevert(bytes("!owner"));
        vault.setProtocolFeeShareBps(100);
        vm.stopPrank();
    }

    // Reserved capital (bond + first-loss) is excluded from depositor NAV (SKELETON note 1).
    function testReservedCapitalExcludedFromNav() public {
        _firstLoss(30_000e6);
        _bond(20_000e6);
        // vault holds 50k USDC but none of it is depositor NAV yet
        assertEq(usdc.balanceOf(address(vault)), 50_000e6);
        assertEq(vault.totalAssets(), 0, "bond + first-loss are not depositor assets");

        _deposit(alice, 100_000e6);
        assertEq(vault.totalAssets(), 100_000e6, "only depositor capital counts toward NAV");
    }
}
