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

/// @dev SKELETON tests — provided for `forge test` once OpenZeppelin + forge-std
/// are installed (see README). Not compiled or run in the authoring session.
contract StrategyVaultTest is Test {
    MockUSDC usdc;
    StrategyVault vault;

    address maker = makeAddr("maker");
    address riskGate = makeAddr("riskGate");
    address oracle = makeAddr("oracle");
    address treasury = makeAddr("treasury");
    address alice = makeAddr("alice");

    function setUp() public {
        usdc = new MockUSDC();
        vault = new StrategyVault(IERC20(address(usdc)), "PM Vault", "pmVLT",
                                  maker, riskGate, oracle, treasury);
        usdc.mint(maker, 1_000_000e6);
        usdc.mint(alice, 1_000_000e6);
        vm.prank(oracle);
        vault.setCapacityCap(200_000e6);
    }

    function _firstLoss(uint256 amt) internal {
        vm.startPrank(maker);
        usdc.approve(address(vault), amt);
        vault.depositFirstLoss(amt);
        vm.stopPrank();
    }

    function _deposit(address who, uint256 amt) internal {
        vm.startPrank(who);
        usdc.approve(address(vault), amt);
        vault.deposit(amt, who);
        vm.stopPrank();
    }

    function testDepositRequiresCoInvestRatio() public {
        vm.startPrank(alice);
        usdc.approve(address(vault), 100_000e6);
        vm.expectRevert(bytes("co-invest ratio"));   // no first-loss posted yet
        vault.deposit(100_000e6, alice);
        vm.stopPrank();
    }

    function testDepositSucceedsWithFirstLoss() public {
        _firstLoss(10_000e6);                        // 10% of a 100k deposit
        _deposit(alice, 100_000e6);
        assertEq(vault.depositorAssets(), 100_000e6);
        assertGt(vault.balanceOf(alice), 0);
    }

    function testCapacityCapEnforced() public {
        _firstLoss(20_000e6);
        vm.prank(oracle);
        vault.setCapacityCap(50_000e6);
        vm.startPrank(alice);
        usdc.approve(address(vault), 60_000e6);
        vm.expectRevert(bytes("capacity cap"));
        vault.deposit(60_000e6, alice);
        vm.stopPrank();
    }

    function testPerformanceFeeProfitOnlyWithHWM() public {
        _firstLoss(10_000e6);
        _deposit(alice, 100_000e6);
        usdc.mint(address(vault), 10_000e6);         // simulate +10% strategy profit
        uint256 before = vault.balanceOf(maker);
        vault.crystallizeFee();
        assertGt(vault.balanceOf(maker), before);    // maker earned fee shares
        uint256 mid = vault.balanceOf(maker);
        vault.crystallizeFee();                      // no new profit above HWM
        assertEq(vault.balanceOf(maker), mid);       // -> no additional fee
    }

    function testSlashWaterfallAndAccessControl() public {
        _firstLoss(10_000e6);
        vm.startPrank(maker);
        usdc.approve(address(vault), 5_000e6);
        vault.postBond(5_000e6);
        vm.stopPrank();

        vm.expectRevert(bytes("!riskGate"));         // non-RiskGate cannot slash
        vault.slash(1_000e6, treasury, "test");

        vm.prank(riskGate);
        vault.slash(3_000e6, treasury, "limit breach");   // bond first
        assertEq(vault.makerBond(), 2_000e6);
        assertEq(vault.makerFirstLoss(), 10_000e6);       // untouched (bond covered it)
    }
}
