# System Design — Prediction-Market Quant Vault Marketplace

*Configuration B-on-C: a picks-and-shovels infrastructure layer (C) with a private-strategy capital-allocator / vault marketplace (B) on top. Draft for review — not committed.*

## 0. Feasibility summary (context)

Conditionally feasible with the confirmed incentive design: **profit-only performance fee + high-water mark + TVL-tiered rate**, **maker co-investment (first-loss) + slashable bond**, **public verified track records**, **mechanical slashing**, and **dynamic capacity caps**. Bounded by three conditions: (1) co-invest ratio + bond must be sized to neutralize the maker's "free option" convexity; (2) TAM is capped by venue open interest (~$0.2–0.3B/venue); (3) a regulated wrapper (CPO/CTA + custodial Kalshi rail) is mandatory and front-loaded.

Design non-goals (explicitly rejected): local/laptop execution, open-sourcing alpha as the moat, decentralization for its own sake, turnover-based fees, "front running" as a product.

The real moat: **verified real-money track records + multi-venue connectivity + risk/custody infrastructure** — an infra/ops moat, not a "quant network."

## 1. Architecture overview

```
                            ┌─────────────────────────────────────────┐
                            │              Web App / API                │
                            │  Maker SDK+dashboard │ Depositor market   │
                            └───────────────┬───────────────────────────┘
                                            │
        ┌───────────────────────────────────┼───────────────────────────────────┐
        │                                    │                                    │
┌───────▼────────┐   ┌───────────────┐  ┌────▼───────────┐   ┌──────────────────┐
│ Vault &        │   │ Track-Record  │  │ Strategy       │   │ Capacity Oracle  │
│ Accounting (B) │   │ & Attestation │  │ Runtime        │   │ (dynamic caps)   │
│ shares/NAV/HWM │   │ (verified PnL)│  │ (sandboxed)    │   └──────────────────┘
│ fees/co-invest │   └───────────────┘  └────┬───────────┘
│ bond/slashing  │                           │ intents (orders, target positions)
└───────┬────────┘                      ┌────▼───────────┐
        │ NAV/settlement                 │  Risk Gate     │  pre-trade + continuous
┌───────▼────────┐                       │  (limits,      │  limits, drawdown, mandate,
│ Custody &      │◄──────reconcile──────►│  capacity,     │  capacity, correlation,
│ Settlement     │                       │  kill-switch)  │  kill-switch, slash triggers
│ on-chain+offch │                       └────┬───────────┘
└───────┬────────┘                            │ approved orders (signed by Exec, keys in KMS)
        │                                 ┌────▼───────────┐
        │                                 │ Execution / OMS│  HSM/KMS keys — strategy NEVER
        │                                 └────┬───────────┘  touches keys or funds
        │                                      │
   ┌────▼──────────────────────────────────────▼───────────────────────────┐
   │                    Venue Connectivity Layer (adapters)                 │
   │   Polymarket adapter (CLOB API + Polygon/CTF, USDC)                    │
   │   Kalshi adapter (REST/FIX, KYC member acct, USD)                      │
   └───────────────────────────────────────────────────────────────────────┘
                                      ▲
                          ┌───────────┴───────────┐
                          │ Market Data & Feeds   │  normalized live books/trades +
                          │ + Historical Tick Store│  external reference feeds + tick history
                          └────────────────────────┘
```

### Subsystems

| # | Subsystem | Responsibility | Notes |
|---|---|---|---|
| C1 | **Venue Connectivity** | `VenueAdapter` interface normalizing each venue | The hard, defensible integration work |
| C2 | **Market Data & Feeds** | Normalized live orderbooks/trades; external reference feeds (sportsbooks, other venues, oracles, news); historical tick store | Powers strategies + backtesting |
| C3 | **Strategy Runtime** | Runs each vault's strategy in an isolated sandbox; emits *intents* only | Hosted, not local; security crux |
| C4 | **Risk Gate / Engine** | Pre-trade + continuous risk; kill-switch; emits slash triggers | Sits between strategy and execution |
| C5 | **Execution / OMS** | Holds keys (KMS/HSM); signs & routes approved orders | Strategy never sees keys/funds |
| C6 | **Custody & Settlement** | On-chain vaults (Polygon) + regulated custodial accounts (Kalshi); reconciliation | Split rail |
| B1 | **Vault & Accounting** | Shares, NAV, HWM, fee accrual, co-invest, bond, slashing | The B core |
| B2 | **Track-Record & Attestation** | Verified real-money PnL, public perf, backtest registry, delayed position disclosure | Tamper-evident |
| B3 | **Capacity Oracle** | Estimates per-strategy capacity; drives dynamic caps | Anti-overcapitalization |
| B4 | **Protocol/Fee Module** | Protocol take rate; TVL-tier logic | |
| X | **Identity/Compliance** | KYC/AML, geofencing, sanctions, tax | Gates both rails |

## 2. The execution & security model (C core)

The central security decision: **strategy code is untrusted and never touches keys or funds.**

```
Strategy container (sandboxed: gVisor/Firecracker, no key access,
egress limited to feed + intent bus)
        │  emits INTENTS: target positions / orders / cancels
        ▼
Risk Gate  ── validates: position & notional limits, capacity cap, mandate
        │     conformance, balance, slippage-vs-book-depth guard
        │  (reject / clip / approve)
        ▼
Execution/OMS  ── holds venue API keys & signing keys in KMS/HSM,
        │          signs and routes approved orders to the venue adapter
        ▼
Venue
```

- **Sandboxing:** each strategy runs as an isolated worker (Firecracker microVM / gVisor). No outbound network except the data-feed subscription and the intent bus. No filesystem/key access. This neutralizes the "third-party code near my funds" rug risk that sinks the naive "deploy locally" design.
- **Intent-based, not key-based:** strategies declare *what* they want (target exposure / orders); the platform decides *whether* and *how* to execute. Risk and key custody stay with the platform.
- **Latency tiers:** latency-sensitive strategies (arb) get execution workers co-located near venue endpoints. This is precisely *why hosted beats local* — and it's sold honestly as bounded infrastructure, not magic.
- **Determinism / reproducibility:** the same container runs against (a) a historical feed replay → reproducible backtest, and (b) the live feed → live trading. Backtest artifacts are content-addressed (container hash + data snapshot hash) and signed, so "past performance" is reproducible, not a marketing screenshot.

## 3. Vault & fee mechanics (B core)

### 3.1 Vault structure

A vault = one strategy + its capital. Capital has three layers of seniority:

```
Depositor capital            (senior)   ─ earns P&L, pays performance fee on profit
Maker co-investment          (junior /  ─ first-loss: absorbs losses before depositors
                              first-loss)   also earns P&L on its share
Maker slashable bond          (locked)   ─ not P&L-bearing; slashed on breach/misalignment
```

- **Shares:** ERC-4626-style accounting. Deposit mints shares at current NAV/share; withdraw burns. **Notice period / lockup** because positions may be illiquid until event resolution.
- **NAV:** consolidated mark-to-market across venues (open positions valued at venue mid/last + realized cash), resolution-aware (pending-resolution positions marked conservatively; UMA-dispute exposure flagged).

### 3.2 Performance fee — profit-only, HWM, TVL-tiered

- **Profit-only:** fee charged *only* on NAV gains. No management/turnover fee (avoids the churn/AUM-gather misalignment).
- **High-water mark (per-share):** fee accrues only on new highs above the prior peak NAV/share, so depositors never pay twice to recover a drawdown. Per-share (not per-depositor) HWM keeps it fair across entry timing.
- **Crystallization:** accrued monthly and on withdrawal; only crystallized fee is paid out.
- **TVL-tiered rate** (per your spec — small maker / small fee, scaling with track record + AUM band):

  | Vault TVL band | Maker perf fee | Protocol take (of fee) | Min co-invest ratio | Min track record |
  |---|---|---|---|---|
  | $0–100k (incubating) | 5% | 0% (waived to bootstrap) | 10% | 60-day live |
  | $100k–500k | 10% | 10% | 7.5% | 90-day live |
  | $500k–2M | 15% | 15% | 5% | 180-day live |
  | $2M+ (capacity-permitting) | 20% | 20% | 5% + tighter caps | 365-day live |

  *(Numbers are a starting schedule to calibrate, not gospel. Note the protocol waives its cut at the incubating tier to attract makers, then scales in.)*

### 3.3 Co-investment + bond (the alignment crux)

- **Min co-invest ratio** enforced continuously: maker first-loss tranche ≥ `r% × depositor TVL`. If depositors grow past the ratio, the vault either caps further deposits or requires the maker to top up. This is what stops the "$5k stake, $2M AUM" free-option.
- **Slashable bond:** a separate locked stake, not P&L-bearing, sized so that `bond + first-loss` makes the maker's expected downside on a blow-up exceed the option value of reckless upside. This bond is the convexity-neutralizer.
- Both are **locked** (with unbonding delay) so they can't be pulled before a breach is adjudicated.

### 3.4 Slashing — mechanical, pre-committed triggers

Slashing must be objective and on-protocol-measurable to be enforceable and legally clean. Triggers:

| Trigger | Detection | Penalty |
|---|---|---|
| Position / notional limit breach | Risk Gate (should be impossible pre-trade; covers post-trade drift) | Partial bond slash + force-flatten |
| Drawdown limit breach | NAV monitor | Bond slash, vault paused |
| Mandate deviation (trades outside declared markets/strategy class) | Risk Gate mandate check | Bond slash |
| Manipulation / wash trading | Surveillance + venue signals | Full bond slash + ban |
| Co-invest ratio not maintained | Accounting | Deposits frozen, escalating slash |

Slashed funds waterfall: **compensate affected depositors first → protocol insurance fund → burn.**

### 3.5 Dynamic capacity caps

- Each vault has `maxTVL = CapacityOracle(strategy)`. Deposits beyond the cap are **rejected or queued**.
- The **Capacity Oracle** estimates capacity from realized slippage and edge decay: as the strategy's realized fills worsen relative to backtested/expected, the cap **tightens automatically**. Conservative by default; governance can review.
- Anti-gaming: caps are driven by *realized* execution quality (hard to fake) rather than maker self-attestation.

## 4. Custody & settlement split

The Morpho-style non-custodial vault is clean **only on-chain**; the off-chain venue needs a regulated structure.

| | Polymarket rail | Kalshi rail |
|---|---|---|
| Custody | ERC-4626 vault on Polygon holds USDC + CTF outcome tokens | Regulated pooled vehicle (fund/series-LLC or omnibus) holds USD at Kalshi via KYC'd member account |
| Fee capture | In-contract (performance fee skimmed on crystallization) | Off-chain ledger, fund administrator |
| Transparency | On-chain NAV; positions disclosed on delay | Off-chain NAV ledger, optionally mirrored on-chain |
| Regulatory | Geofenced (no US persons) | CFTC/NFA-registered (CPO/CTA), full KYC/AML |
| Settlement | On-chain (Polygon) + UMA resolution | USD wire/ACH, Kalshi clearing |

A **unified accounting service** consolidates both into one NAV/share per vault and reconciles vault NAV against actual venue balances on a schedule (breaks → kill-switch).

## 5. Track-record & transparency (honoring "public" + protecting alpha)

- **Public, verified, real-money** performance: returns, Sharpe/Sortino, max drawdown, win rate, fee history — each NAV snapshot signed by the Execution engine and anchored on-chain (tamper-evident). This is the moat: PnL you can't fake.
- **Backtests public but clearly labeled** and reproducible (container hash + data snapshot). **Backtests never gate outside AUM** — only real-money track record does (per the tier table).
- **Live positions disclosed on a lag** (T+delay or aggregate exposure buckets), not in real time, to prevent copy-trading/front-running that would decay depositors' alpha. Transparency on *results*, delay on *live fills*.

## 6. Risk engine specifics

- **Pre-trade:** position/notional limits, capacity-cap check, balance check, mandate conformance, **slippage guard** (order size vs current book depth — critical on thin prediction-market books).
- **Continuous:** per-vault drawdown limit, VaR, **cross-vault correlation** (many vaults piling into the same trade = systemic concentration), oracle/resolution-risk exposure (UMA disputes), per-venue exposure limits.
- **Kill-switch:** per-vault and global; auto-flatten on hard breach.
- Emits **slash triggers** to B1.

## 7. Compliance architecture

- **Two legally separated rails:** Kalshi (US, regulated, CPO/CTA + KYC/AML) vs Polymarket (geofenced, no US persons). Never co-mingle.
- Fee-charging on pooled capital ⇒ regulated fund activity; vaults wrapped as funds / compliant vehicles; **legal counsel gates launch.**
- Depositor + maker KYC/AML, sanctions screening, tax reporting (depositor PnL, fee income).

## 8. Core data model

`Vault`, `Strategy(version, containerHash, mandate)`, `Maker`, `Depositor`, `Position`, `Order/Fill`, `NAVSnapshot(signed)`, `FeeAccrual`, `HighWaterMark`, `CoInvestTranche`, `Bond`, `SlashEvent`, `CapacityState`, `TrackRecordAttestation`, `RiskLimitSet`, `Venue/Market`.

## 9. Suggested stack

- **Execution + Risk Gate:** Rust/Go low-latency services; NATS/Redis intent bus; Firecracker/gVisor sandboxes.
- **Vaults:** Solidity ERC-4626 (Polygon); off-chain ledger in Postgres; reconciliation workers.
- **Market data:** Timescale/kdb tick store; Kafka feeds.
- **Keys:** cloud KMS + HSM; strategies never receive credentials.
- **App:** Next.js; maker SDK in Python + TypeScript.

## 10. Phased build (de-risk order)

| Phase | Scope | Proves |
|---|---|---|
| **0** | C-infra, single venue (Polymarket), one *internal* strategy, backtest + risk + execution, no outside AUM | The infra + a real-money track record |
| **1** | Vault + accounting + profit-only fee + HWM + co-invest, a few invited makers, capped AUM, single venue | The B economics + alignment |
| **2** | Slashing + dynamic capacity caps + public track record | Safety + trust |
| **3** | Kalshi rail (regulated custodial) + cross-venue; CPO/CTA wrapper live | Multi-venue + compliance |
| **4** | Open marketplace | Scale (within OI ceiling) |

## 11. Open questions to resolve before/within build

1. **Co-invest ratio + bond sizing** to neutralize the maker free-option convexity — model this explicitly (the #1 design risk).
2. **Capacity oracle** robustness and resistance to gaming.
3. **Liquidity/lockup** policy given positions resolve at event time (depositor redemption vs open positions).
4. **Per-share HWM** edge cases (deposits/withdrawals mid-period, fee equalization).
5. **Regulated wrapper** structure, jurisdiction, cost, and timeline — gates Phase 3.
6. Position-disclosure delay length: long enough to protect alpha, short enough to keep "public" credible.
