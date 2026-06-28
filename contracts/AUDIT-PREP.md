# Vault Audit-Prep Notes (Phase 2 → Audit #1 scoping)

Status as of this pass: **compiles, tests pass, statically analyzed.** Still
**not externally audited** — external Audit #1 (PLAN.md Phase 3) remains the gate
before any outside capital.

## Toolchain (reproducible)

| Component | Version |
|---|---|
| Foundry (`forge`) | 1.7.1 |
| solc | 0.8.24 (pinned in `foundry.toml`) |
| OpenZeppelin contracts | v5 (`forge install` default branch) |
| forge-std | pinned by `forge install` |
| Slither | 0.11.5 |

```bash
cd contracts
forge install OpenZeppelin/openzeppelin-contracts foundry-rs/forge-std --no-git
forge build          # Compiler run successful
forge test           # 17 passed; 0 failed
slither . --filter-paths "lib/" --exclude-dependencies
```

## Test coverage (17 tests)

`test/StrategyVault.t.sol` (5 — happy path):
co-invest gating, capacity-cap revert, profit-only HWM fee, slash access-control.

`test/StrategyVaultProperties.t.sol` (12 — adversarial money-path vectors):

| Property proven | Test | Plan ref |
|---|---|---|
| HWM never double-charges a recovery (profit → drawdown → recovery → new high) | `testNoDoubleChargeAcrossDrawdown` | §3 fee gate |
| Crystallize is idempotent without new profit | `testCrystallizeIdempotentWithoutNewProfit` | §3 |
| Flat deposit→withdraw returns principal, no fee, maker capital untouched | `testFlatDepositWithdrawNoFeeNoLoss` | §2/§3 |
| Profit then withdraw: depositor nets profit minus fee | `testProfitThenWithdrawNetsProfitMinusFee` | §3 |
| Slash spills bond → first-loss in order | `testSlashSpillsFromBondIntoFirstLoss` | §4 |
| Slash caps at bond+first-loss, no underflow | `testSlashCapsAtBondPlusFirstLossNoUnderflow` | inv. #7 |
| Co-invest ratio blocks growth beyond first-loss | `testCoInvestRatioBlocksGrowthBeyondFirstLoss` | inv. #5 |
| Reserved capital excluded from depositor NAV | `testReservedCapitalExcludedFromNav` | ADR-005 |
| Role setters reject zero address | `testRoleSettersRejectZeroAddress` | hardening |
| Oracle/treasury rotation re-gates access | `testRotateOracleAndTreasury` | hardening |
| Protocol fee-share bounded ≤ 100% | `testProtocolFeeShareBounded` | hardening |
| Only owner can administer | `testOnlyOwnerCanAdminister` | hardening |

Strategy gain/loss (e.g. an event resolution) is simulated by moving USDC in/out
of the vault, since the on-chain vault is the custody layer; live NAV vs venue is
reconciled off-chain (`predmkt/reconcile.py`, ADR-011) and already has its own
halt-on-divergence tests in `strategies/tests/test_smoke.py`.

## Slither triage

First pass: 17 findings. After hardening: **4 findings, all reviewed and accepted.**

**Fixed:**
- *missing-zero-check* — added zero-address `require`s to the constructor and all
  role setters.
- *events-access / events-maths* — added events for every admin state change
  (`RiskGateUpdated`, `CapacityOracleUpdated`, `ProtocolTreasuryUpdated`,
  `OwnershipTransferred`, `MinCoInvestRatioUpdated`, `ProtocolFeeShareUpdated`).
- *immutable-states* — `maker` is now `immutable` (fixed per vault); `capacityOracle`
  and `protocolTreasury` gained rotation setters (operational key-rotation safety).
- Added a `protocolFeeShareBps <= 100%` bound.

**Accepted (with rationale) — remaining 4:**
- *incorrect-equality* ×3 (`supply == 0`, `feeAssets == 0`): exact-zero checks on
  unsigned internal counts. The detector targets equality on manipulable values
  (balances/timestamps); these are control-flow guards and are correct.
- *dead-code* `_applyLoss`: the **intentional** junior loss-waterfall stub
  (reverts), flagged `SKELETON:` inline. It is the open question in DESIGN.md §11 —
  left as a documented placeholder for settlement integration, not removed, so the
  design intent stays visible to the auditor.

## Still open before Audit #1 sign-off (NOT done here)

- Junior/senior **loss-waterfall** (`_applyLoss`) — needs settlement integration.
- **Per-share HWM equalization** on mid-period deposits/withdrawals (depositors who
  enter above/below the HWM are not individually equalized).
- **Reentrancy** review of the deposit/withdraw + fee-mint path (no `nonReentrant`
  guards yet; OZ ERC4626 + SafeERC20 are the only protections).
- **Pause / emergency-halt** on the contract itself (today the halt lives off-chain).
- Confirm **bond/first-loss escrow** design (currently same-contract balance,
  excluded from NAV via accounting — a production design may escrow externally).
