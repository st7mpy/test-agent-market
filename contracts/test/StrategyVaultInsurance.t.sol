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

/// @notice Insurance fund + realized-loss waterfalls (C, ADR-015). Proves the fund is
/// excluded from depositor NAV, that strategy losses are absorbed first-loss → bond →
/// depositors, and that oracle-failure losses are absorbed by the insurance fund —
/// keeping depositor NAV whole up to each buffer's size.
contract StrategyVaultInsuranceTest is Test {
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
        usdc.mint(treasury, 1_000_000e6);
        vm.prank(oracle);
        vault.setCapacityCap(1_000_000e6);
    }

    // --- helpers ---------------------------------------------------------- //
    function _firstLoss(uint256 a) internal {
        vm.startPrank(maker); usdc.approve(address(vault), a); vault.depositFirstLoss(a); vm.stopPrank();
    }
    function _bond(uint256 a) internal {
        vm.startPrank(maker); usdc.approve(address(vault), a); vault.postBond(a); vm.stopPrank();
    }
    function _fundInsurance(address who, uint256 a) internal {
        vm.startPrank(who); usdc.approve(address(vault), a); vault.fundInsurance(a); vm.stopPrank();
    }
    function _deposit(address who, uint256 a) internal {
        vm.startPrank(who); usdc.approve(address(vault), a); vault.deposit(a, who); vm.stopPrank();
    }
    function _loss(uint256 a) internal {            // simulate USDC leaving on a realized loss
        vm.prank(address(vault)); usdc.transfer(burn, a);
    }

    // --- NAV exclusion ---------------------------------------------------- //
    function testInsuranceFundExcludedFromNav() public {
        _firstLoss(20_000e6);
        _deposit(alice, 100_000e6);
        assertEq(vault.totalAssets(), 100_000e6);

        _fundInsurance(treasury, 30_000e6);
        assertEq(vault.insuranceFund(), 30_000e6);
        assertEq(vault.totalAssets(), 100_000e6, "insurance fund must not inflate depositor NAV");
    }

    function testSlashToInsuranceReclassifiesReservedCapital() public {
        _firstLoss(10_000e6);
        _bond(5_000e6);
        uint256 navBefore = vault.totalAssets();

        vm.prank(riskGate);
        uint256 moved = vault.slashToInsurance(6_000e6, "limit breach");   // 5k bond + 1k first-loss

        assertEq(moved, 6_000e6);
        assertEq(vault.makerBond(), 0);
        assertEq(vault.makerFirstLoss(), 9_000e6);
        assertEq(vault.insuranceFund(), 6_000e6);
        assertEq(vault.totalAssets(), navBefore, "reclassification doesn't change depositor NAV");
    }

    // --- strategy-loss waterfall: first-loss -> bond -> depositors -------- //
    function testStrategyLossAbsorbedByFirstLossKeepsDepositorsWhole() public {
        _firstLoss(10_000e6);
        _deposit(alice, 100_000e6);

        _loss(8_000e6);                              // realized strategy loss
        vm.prank(riskGate);
        uint256 residual = vault.applyStrategyLoss(8_000e6);

        assertEq(residual, 0, "first-loss fully absorbs");
        assertEq(vault.makerFirstLoss(), 2_000e6);   // 10k - 8k
        assertEq(vault.totalAssets(), 100_000e6, "depositor NAV untouched");
    }

    function testStrategyLossBeyondBuffersHitsDepositors() public {
        _firstLoss(5_000e6);
        _bond(3_000e6);
        _deposit(alice, 100_000e6);

        _loss(12_000e6);
        vm.prank(riskGate);
        uint256 residual = vault.applyStrategyLoss(12_000e6);

        assertEq(residual, 4_000e6, "5k FL + 3k bond absorbed; 4k spills to depositors");
        assertEq(vault.makerFirstLoss(), 0);
        assertEq(vault.makerBond(), 0);
        assertEq(vault.totalAssets(), 96_000e6, "depositors bear only the residual");
    }

    // --- oracle-failure waterfall: insurance fund -> depositors ----------- //
    function testOracleLossAbsorbedByInsuranceFund() public {
        _firstLoss(10_000e6);                        // maker capital must stay untouched
        _deposit(alice, 100_000e6);
        _fundInsurance(treasury, 6_000e6);

        _loss(6_000e6);                              // oracle-failure loss
        vm.prank(riskGate);
        uint256 residual = vault.coverOracleLoss(6_000e6);

        assertEq(residual, 0, "insurance fully covers");
        assertEq(vault.insuranceFund(), 0);
        assertEq(vault.makerFirstLoss(), 10_000e6, "maker capital NOT raided for oracle failure");
        assertEq(vault.totalAssets(), 100_000e6, "depositor NAV protected");
    }

    function testOracleLossBeyondFundHitsDepositorsNotMaker() public {
        _firstLoss(10_000e6);
        _deposit(alice, 100_000e6);
        _fundInsurance(treasury, 6_000e6);

        _loss(10_000e6);
        vm.prank(riskGate);
        uint256 residual = vault.coverOracleLoss(10_000e6);

        assertEq(residual, 4_000e6, "6k fund absorbed; 4k beyond it");
        assertEq(vault.insuranceFund(), 0);
        assertEq(vault.makerFirstLoss(), 10_000e6, "maker still untouched");
        assertEq(vault.totalAssets(), 96_000e6);
    }

    // --- access control --------------------------------------------------- //
    function testLossFunctionsAreRiskGateOnly() public {
        _firstLoss(10_000e6);
        _fundInsurance(treasury, 10_000e6);
        vm.expectRevert(bytes("!riskGate"));
        vault.applyStrategyLoss(1_000e6);
        vm.expectRevert(bytes("!riskGate"));
        vault.coverOracleLoss(1_000e6);
        vm.expectRevert(bytes("!riskGate"));
        vault.slashToInsurance(1_000e6, "x");
    }
}
