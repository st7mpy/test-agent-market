# Vault Contracts (Phase 2)

`StrategyVault.sol` — the **ERC-4626 vault skeleton** that custodies depositor capital
and encodes the value-capture + alignment mechanics from
[`../docs/DESIGN.md`](../docs/DESIGN.md) and [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

> ⚠️ **SKELETON — not audited, not compiled in this session, not for production.**
> No Solidity toolchain was available at authoring time, so this has **not been compiled
> or tested**. Treat it as a structural starting point. The money-path must pass external
> audit (PLAN.md Phase 3, AUDIT #1) before any real capital.

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
forge install OpenZeppelin/openzeppelin-contracts foundry-rs/forge-std --no-commit
forge build
forge test -vvv
```

`test/StrategyVault.t.sol` covers: co-invest ratio gating, capacity-cap revert, profit-only
HWM fee (no double-charge on a second crystallization), and slash access-control + waterfall.

## How it connects to the rest

The off-chain platform drives this contract:
- the **Capacity Oracle** (predmkt, ADR-007) calls `setCapacityCap`;
- the **RiskGate** (`predmkt/execution.py`, ADR-006) is the only slasher;
- NAV/positions are reconciled off-chain (`predmkt/reconcile.py`, ADR-011) against the
  venue, while this vault is the on-chain custody + fee + alignment layer.
