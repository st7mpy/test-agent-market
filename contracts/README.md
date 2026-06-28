# Vault Contracts (Phase 2)

`StrategyVault.sol` — the **ERC-4626 vault skeleton** that custodies depositor capital
and encodes the value-capture + alignment mechanics from
[`../docs/DESIGN.md`](../docs/DESIGN.md) and [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

> ⚠️ **Not externally audited — not for production.**
> Now **compiles (Foundry 1.7.1 / solc 0.8.24 / OpenZeppelin v5) and passes 17 tests**,
> with Slither findings triaged (see [`AUDIT-PREP.md`](AUDIT-PREP.md)). It remains a
> structural starting point: the money-path must pass **external Audit #1**
> (PLAN.md Phase 3) before any real capital, and the loss-waterfall is still stubbed.

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
2. **Junior/senior loss-waterfall is stubbed** (`_applyLoss` reverts). True first-loss —
   the maker's junior tranche absorbing *strategy* losses before depositors — requires
   integration with settlement and is the open question flagged in DESIGN.md §11.
3. Fee/HWM rounding, reentrancy hardening, pausing, and per-depositor fee equalization are
   not addressed here.

## Build & test (with Foundry)

This repo does not vendor dependencies. To compile and run the tests:

```bash
# install Foundry: https://book.getfoundry.sh/getting-started/installation
cd contracts
forge install OpenZeppelin/openzeppelin-contracts foundry-rs/forge-std --no-git
forge build          # Compiler run successful (solc 0.8.24)
forge test           # 17 passed; 0 failed
```

- `test/StrategyVault.t.sol` (5) — happy path: co-invest ratio gating, capacity-cap
  revert, profit-only HWM fee, slash access-control + waterfall.
- `test/StrategyVaultProperties.t.sol` (12) — adversarial money-path vectors: the
  HWM **no-double-charge-across-a-drawdown** invariant, deposit/withdraw NAV
  correctness, slash-waterfall spill + over-slash cap, co-invest-ratio gating across
  multiple deposits, and admin hardening (zero-checks, rotation, bounds).

See [`AUDIT-PREP.md`](AUDIT-PREP.md) for the toolchain, the full coverage matrix, and
the Slither triage (17 findings → 4 reviewed-and-accepted).

## How it connects to the rest

The off-chain platform drives this contract:
- the **Capacity Oracle** (predmkt, ADR-007) calls `setCapacityCap`;
- the **RiskGate** (`predmkt/execution.py`, ADR-006) is the only slasher;
- NAV/positions are reconciled off-chain (`predmkt/reconcile.py`, ADR-011) against the
  venue, while this vault is the on-chain custody + fee + alignment layer.
