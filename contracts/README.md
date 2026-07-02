# Vault Contracts (Phase 2)

`StrategyVault.sol` — the **ERC-4626 vault** that custodies depositor capital
and encodes the value-capture + alignment mechanics from
[`../docs/DESIGN.md`](../docs/DESIGN.md) and [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).
`TranchedVault.sol` — the Phase-6 **senior/junior depositor tranches** (ADR-017).

> ⚠️ **Not externally audited — not for production.**
> Now **compiles (Foundry 1.7.1 / solc 0.8.24 / OpenZeppelin v5) and passes 31 tests**
> (5 happy-path + 12 property + 7 insurance/loss-waterfall + 7 tranched), with Slither
> findings triaged (see [`AUDIT-PREP.md`](AUDIT-PREP.md)). It remains a structural
> starting point: the money-path must pass **external Audit #1**
> (PLAN.md Phase 3) before any real capital.

## What it implements

| Mechanic | ADR | Where |
|---|---|---|
| ERC-4626 shares over USDC | — | `is ERC4626` |
| Profit-only performance fee + per-share high-water mark | ADR-004 | `_crystallizeFee` |
| TVL-tiered fee rate | ADR-004 | `performanceFeeBps` |
| Maker first-loss co-investment + slashable bond | ADR-005 | `depositFirstLoss`, `postBond` |
| Min co-investment ratio enforced on deposit | ADR-005 | `_enforceEntry` |
| Dynamic capacity cap (set by off-chain oracle) | ADR-007 | `setCapacityCap`, `_enforceEntry` |
| Mechanical slashing, RiskGate-only, waterfall | ADR-006 | `slash` |

The fee is charged by minting dilutive shares to the maker + protocol treasury, only on
gains above the HWM; the HWM resets after each crystallization. Slashing takes from the
**bond first, then first-loss**, and pays the proceeds to a beneficiary (affected depositors
/ insurance fund).

## Known simplifications (flagged `SKELETON:` inline)

1. **Bond + first-loss are excluded from `totalAssets()`** so they don't distort depositor
   share price. A production design would escrow them outside the vault.
2. **Realized-loss waterfalls take a trusted input** — `applyStrategyLoss` (first-loss →
   bond → depositors) and `coverOracleLoss` (insurance fund → depositors) are implemented
   (ADR-015), but the loss *amount* is a RiskGate-supplied number from off-chain
   reconciliation; that measurement path needs settlement integration and is in Audit #1's scope.
3. Fee/HWM rounding, reentrancy hardening, pausing, and per-depositor fee equalization are
   not addressed here.

## Build & test (with Foundry)

This repo does not vendor dependencies. To compile and run the tests:

```bash
# install Foundry: https://book.getfoundry.sh/getting-started/installation
cd contracts
forge install OpenZeppelin/openzeppelin-contracts foundry-rs/forge-std --no-git
forge build          # Compiler run successful (solc 0.8.24)
forge test           # 31 passed; 0 failed
```

- `test/StrategyVault.t.sol` (5) — happy path: co-invest ratio gating, capacity-cap
  revert, profit-only HWM fee, slash access-control + waterfall.
- `test/StrategyVaultProperties.t.sol` (12) — adversarial money-path vectors: the
  HWM **no-double-charge-across-a-drawdown** invariant, deposit/withdraw NAV
  correctness, slash-waterfall spill + over-slash cap, co-invest-ratio gating across
  multiple deposits, and admin hardening (zero-checks, rotation, bounds).
- `test/StrategyVaultInsurance.t.sol` (7) — insurance fund + realized-loss waterfalls
  (ADR-015): fund excluded from NAV, strategy-loss junior-first, oracle-loss covered
  by the fund with maker capital untouched, RiskGate-only access.
- `test/TranchedVault.t.sol` (7) — senior/junior tranching (ADR-017): loss junior-first,
  senior coupon priority, withdraw-at-grown-NAV, balance invariant.

See [`AUDIT-PREP.md`](AUDIT-PREP.md) for the toolchain, the full coverage matrix, and
the Slither triage (first pass 17 findings → 3 reviewed-and-accepted).

## How it connects to the rest

The off-chain platform drives this contract:
- the **Capacity Oracle** (predmkt, ADR-007) calls `setCapacityCap`;
- the **RiskGate** (`predmkt/execution.py`, ADR-006) is the only slasher;
- NAV/positions are reconciled off-chain (`predmkt/reconcile.py`, ADR-011) against the
  venue, while this vault is the on-chain custody + fee + alignment layer.
