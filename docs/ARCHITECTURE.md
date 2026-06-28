# Architecture & Rationale

*Companion to `DESIGN.md`. Where `DESIGN.md` says **what** the system is, this document says **why** each choice was made, what alternatives were rejected, and what each choice costs. It also gives a concrete, buildable module layout and the key interface contracts.*

---

## 1. Context

A two-sided marketplace where **makers** (quants) publish private trading strategies as **vaults** and **depositors** allocate capital to them, on prediction-market venues (Polymarket, Kalshi). Configuration **B-on-C**: an infrastructure layer (connectivity, hosted execution, risk, custody, track-record) with a capital-allocator / vault layer on top.

The architecture is shaped by four forces that a naive "deploy an open-source bot locally" design gets wrong:

1. **Alpha is adversarial, capacity-constrained, and decays when shared.** → strategies stay private; capacity is capped; positions are disclosed on a lag.
2. **Strategy code is untrusted but must trade real money.** → code never touches keys; it emits intents through a risk choke point.
3. **Fees are only enforceable if capital is custodied in the protocol.** → hosted execution + in-protocol vaults, not local laptops.
4. **The two venues are architecturally and legally incompatible.** → a split on-chain / regulated-custodial custody model.

---

## 2. Architectural principles

| Principle | Rationale |
|---|---|
| **Untrusted strategy, trusted platform** | The marketplace's whole value is running other people's code near other people's money. That only works if the code is sandboxed and keys/risk live with the platform. |
| **Intents in, orders out** | A single choke point (the Risk Gate) where every order is validated makes risk, capacity, mandate, and slashing enforceable. No bypass path. |
| **Verifiable over claimed** | Backtests are cheap to fake and overfit. Every number that gates capital (track record, NAV, capacity) is derived from *realized, signed, reproducible* data. |
| **Align by capital, not by reputation** | Reputation is cheap; first-loss capital and a slashable bond are not. Alignment is enforced by money at risk, sized to outweigh the fee's option value. |
| **Mechanical over discretionary** | Slashing and capacity changes fire on objective, pre-committed, on-protocol-measurable triggers — not governance votes — for enforceability and legal cleanliness. |
| **Reconcile to reality** | Vault NAV is a derived view; the venue is the source of truth. Divergence halts the vault. |

---

## 3. Decision records (ADRs)

Each records the **choice**, the **rationale**, the **alternatives rejected**, and the **consequences** (what it costs us).

### ADR-001 — Hosted execution, not local
**Choice:** strategies run on platform-operated infrastructure; never on the user's machine.
**Rationale:** (a) the only proven-profitable strategy class (latency/cross-venue arb) is an infrastructure game — a laptop on residential internet is the slow leg; (b) trading needs 24/7 uptime; (c) keys can't be safely held on a user device; (d) **the performance fee is only enforceable if capital is custodied in-protocol**, which requires hosted execution.
**Rejected:** *local agent* (rug risk, latency, no enforceable rake); *hybrid local+hosted* (doubles the attack surface for no benefit).
**Consequences:** we operate real infra and inherit custody/regulatory obligations. Accepted — these are the moat, not overhead.

### ADR-002 — Intent-based execution; strategy code never holds keys
**Choice:** sandboxed strategy emits **intents** (desired orders / target positions) onto a bus; a **Risk Gate** validates them; only the **Execution/OMS** (holding keys in KMS/HSM) signs and routes.
**Rationale:** third-party code adjacent to funds is the dominant risk. If the strategy held scoped API keys it could exfiltrate them, self-deal (trade its depositors against the maker's own wallet), or bypass risk limits. Intents make every order pass one validated choke point and keep keys out of untrusted code entirely.
**Rejected:** *scoped per-strategy API keys* (exfiltration; no pre-trade risk choke point); *first-party-only strategies* (kills the marketplace).
**Consequences:** an intent schema and a latency hop through the Risk Gate. Mitigate latency with a co-located fast path for arb strategies (validated but minimal).

### ADR-003 — Private strategies + verified real-money track record; not open source
**Choice:** strategy code is confidential; what's public is *verified realized performance*.
**Rationale:** open-sourcing alpha triggers the market-for-lemons (anyone with real edge runs it privately) and instant alpha decay. QuantConnect's Alpha Streams — the closest precedent — deprecated its open marketplace over exactly this (overfitting + selection bias). Verifiable PnL, not shared code, is the defensible asset.
**Rejected:** *open-source marketplace* (lemons, decay); *backtests-as-truth* (overfit, unverifiable).
**Consequences:** we need confidentiality infra and a transparency mechanism that doesn't leak the strategy → ADR-009.

### ADR-004 — Profit-only performance fee, per-share high-water mark, TVL-tiered
**Choice:** makers earn **only** on profit above a per-share HWM; rate tiers with TVL; no management or turnover fee.
**Rationale:** a fee on AUM pays makers to gather and park capital regardless of returns; a fee on *turnover* pays them to churn — actively destructive in a negative-sum venue. Profit-only ties maker income to depositor outcomes. Per-share HWM (not per-depositor) is fair across entry timing and prevents charging twice to recover a drawdown.
**Rejected:** *AUM management fee* (pays for parking); *turnover/volume fee* (incentivizes churn — the original pitch's worst idea); *per-depositor HWM* (entry-timing unfairness, heavier bookkeeping).
**Consequences:** HWM and fee-equalization accounting complexity on deposits/withdrawals mid-period.

### ADR-005 — Maker co-investment (first-loss) + slashable bond, ratio enforced continuously
**Choice:** maker posts a junior **first-loss** tranche sized as a minimum % of depositor TVL, **plus** a separate locked **slashable bond**; the ratio is enforced continuously.
**Rationale:** a profit-only fee is still a *free option* — "heads I take 20%, tails I lose a token stake" — which incentivizes reckless risk. First-loss + bond, sized so blow-up downside exceeds the option's upside value, neutralizes that convexity and self-selects makers who believe their edge survives outside capital (countering lemons). Enforcing the *ratio* (not a fixed amount) stops the "$5k stake, $2M AUM" cosmetic-alignment failure.
**Rejected:** *reputation only* (cosmetic); *fixed bond* (doesn't scale with AUM, so alignment erodes as the vault grows).
**Consequences:** makers need real capital (slows growth, raises quality); the co-invest-ratio + bond sizing is the #1 modeling task before launch.

### ADR-006 — Mechanical, pre-committed slashing triggers only
**Choice:** slashing fires on objective, on-protocol-measurable conditions; no discretionary slashing.
**Rationale:** discretionary slashing invites disputes, governance capture, and legal exposure ("you took my money on a judgment call"). Mechanical triggers (limit breach, drawdown breach, mandate deviation, detected manipulation, ratio shortfall) are defensible and predictable.
**Rejected:** *governance/committee slashing* (disputes, capture, legal risk).
**Consequences:** every slashable condition must be expressible as a measurable on-protocol predicate; "soft" misalignment that isn't measurable can't be slashed (only delisted).

### ADR-007 — Capacity caps driven by *realized* execution quality
**Choice:** each vault's max TVL is set by a Capacity Oracle from realized slippage/edge decay and tightens automatically as fills degrade.
**Rationale:** capacity-limited strategies go negative-EV when overcapitalized; makers paid on profit still want max AUM, so they can't be trusted to self-cap. Realized execution quality is hard to fake, unlike self-declared capacity.
**Rejected:** *maker-declared capacity* (gamed for fees); *fixed caps* (wrong as edge decays); *no caps* (overcapitalization silently loses depositor money — reputational death).
**Consequences:** oracle design + gaming-resistance work; conservative defaults that may frustrate makers; governance review path for disputes.

### ADR-008 — Split custody: on-chain ERC-4626 (Polymarket) vs regulated custodial vehicle (Kalshi)
**Choice:** Polymarket capital lives in on-chain ERC-4626 vaults; Kalshi capital lives in a regulated pooled vehicle (fund / series-LLC / omnibus) with an off-chain share ledger. A unified accounting service consolidates both.
**Rationale:** the in-contract fee skim is only clean on-chain. Kalshi is off-chain, KYC'd, USD — it *cannot* be a smart contract, so its fee capture and custody must be a regulated structure. Forcing one model onto both either abandons Kalshi (the larger regulated venue) or throws away on-chain transparency/efficiency for Polymarket.
**Rejected:** *on-chain only* (drops Kalshi); *custodial only* (loses on-chain transparency, adds custody risk for Polymarket).
**Consequences:** dual accounting + reconciliation; two legal rails (geofenced Polymarket vs CPO/CTA-registered Kalshi) that must never co-mingle.

### ADR-009 — Public verified results, delayed/obfuscated live positions
**Choice:** verified realized performance is public immediately; *live positions* are disclosed on a lag (T+delay or aggregate exposure buckets).
**Rationale:** "public performance" builds trust and prevents track-record fraud, but real-time public positions let anyone copy/front-run the strategy and decay the very alpha depositors pay for. Splitting *results* (immediate) from *live fills* (delayed) gives transparency without leakage.
**Rejected:** *full real-time transparency* (copy-trading decays alpha); *full opacity* (breaks verifiability/trust).
**Consequences:** must pick the delay window — long enough to protect alpha, short enough to stay credible — and defend it publicly.

### ADR-010 — Reproducible, content-addressed backtests; only real-money gates AUM
**Choice:** backtests run the *same container* against a snapshotted historical feed and are content-addressed (container hash + data hash) and signed. They're publishable but **never** gate outside capital — only realized track record does.
**Rationale:** backtests are trivially overfit; making them reproducible deters fraud, and refusing to let them unlock AUM removes the incentive to overfit for marketing.
**Rejected:** *backtests as track record* (overfit, unverifiable).
**Consequences:** deterministic feed replay + data snapshotting infrastructure.

### ADR-011 — NAV reconciliation is authoritative; divergence trips the kill-switch
**Choice:** vault NAV is continuously reconciled against actual venue balances/positions; a material divergence halts the vault and flattens if needed.
**Rationale:** NAV is a derived view that drives deposits, withdrawals, and fees. If it drifts from venue reality, it's either a bug or an exploit, and every share priced off it is wrong. Halting on divergence is fail-safe.
**Rejected:** *trust internal ledger* (silent corruption → mispriced shares → loss/fraud).
**Consequences:** reconciliation jobs, conservative marks for pending-resolution positions, and accepted false-positive halts.

### ADR-012 — Research signals are a typed provider seam, off the execution hot path (differentiator F)
**Choice:** fair-value estimates come from a `SignalProvider` (`predmkt/signals.py`) that only *proposes* a probability; it is adapted into the strategy's `fair_value_fn` hook and its output still flows through the normal `strategy → intent → Risk Gate` path. The production provider is an **LLM research agent** (news / base-rates / sentiment), but it is one interface implementation, not a privileged component.
**Rationale:** an LLM is non-deterministic, slow, and occasionally wrong — it must never sit in the order-signing path or be able to move funds directly. Making it a provider that emits a number behind the existing intent boundary (ADR-002) means a bad signal can at worst propose a trade the Risk Gate then bounds/refuses; it can't bypass limits. A typed seam also lets us swap providers (LLM, devigged sportsbook, other-venue implied) and A/B them without touching the hot path. This is the *legitimate* use of "AI agents" here — signal generation, not autonomous execution.
**Rejected:** *LLM in the hot path* (latency, non-determinism, and an unbounded failure mode next to keys); *bespoke per-strategy plumbing* (no common validation, no swap­pability).
**Consequences:** signals are advisory; the reference LLM provider (Claude, e.g. `claude-opus-4-8`) is a future drop-in behind `SignalProvider` and must be validated by ADR-013 before it is allowed to size capital.

### ADR-013 — A signal must prove Brier *skill* over the market + calibration before it sizes capital
**Choice:** no provider influences sizing until it shows, on **resolved real-money markets**, (a) a positive **Brier skill score** vs the market-implied null model and (b) calibration within tolerance (ECE ≤ 10%). The gate is `SignalReport.trustworthy` in `predmkt/signals.py`.
**Rationale:** the market price is already a strong, free forecast. A signal that doesn't beat it adds nothing; a *miscalibrated* signal (confident when it shouldn't be) actively missizes Kelly bets and is worse than using the price. Brier skill answers "does it add information?"; calibration answers "can I trust its magnitudes?" — Kelly sizing needs both. Scoring against the market-implied null (not against 0.5) makes the bar honest: beating the market, not beating ignorance. This mirrors ADR-010 (backtests don't gate AUM; only real-money does) for signals.
**Rejected:** *trust backtested/claimed accuracy* (overfit, unverifiable); *score vs a naïve 0.5 baseline* (flatters any signal); *skill-only with no calibration check* (a high-skill but overconfident signal still wrecks Kelly sizing).
**Consequences:** providers need a sustained resolved-market sample before they're trusted (skill is hard to resolve in small samples — see `signal_demo.py`); the harness (Brier, skill, reliability curve, ECE) is part of the maker-onboarding and signal-promotion pipeline.

---

## 4. Trust boundaries

```
  UNTRUSTED                 │  TRUSTED PLATFORM (keys, risk, custody)        │ EXTERNAL
 ─────────────────────────  │  ───────────────────────────────────────────  │ ──────────
  Maker strategy code       │   Risk Gate ─► Execution/OMS (KMS/HSM keys)    │  Polymarket
  (sandboxed microVM,       │     ▲              │                            │  Kalshi
   no keys, no egress  ──intents──┘              └── signed orders ───────────┼─►
   except feed + bus)       │   Accounting ◄── reconcile ── Custody           │  (UMA oracle)
                            │   Attestation (signs NAV/track-record)          │
  Depositor (KYC'd)         │   Compliance (KYC/AML, geofence, sanctions)     │
```

The only thing crossing from untrusted → trusted is an **intent** (data, never code execution with privileges, never keys). Everything that can move money sits on the trusted side of the line.

---

## 5. Key data flows

**Order path (hot):** `strategy → intent → Risk Gate (validate: limits, capacity, mandate, slippage) → Execution/OMS (sign) → Venue adapter → venue`. Fills flow back → positions → NAV.

**Deposit:** `depositor → Compliance (KYC/geofence) → Vault.deposit(USDC/USD) → mint shares at NAV/share (capacity-cap checked) → co-invest ratio re-checked`.

**Fee crystallization:** `period close → per-share NAV vs HWM → accrue profit-only fee → split maker / protocol per TVL tier → update HWM`.

**Capacity loop:** `Execution fills → realized slippage/edge metrics → Capacity Oracle → adjust maxTVL → gate deposits`.

**Slash:** `Risk Gate / monitor detects trigger → Slashing module locks & slashes bond/first-loss → waterfall: affected depositors → insurance fund → burn → vault paused`.

**Attestation:** `NAVSnapshot signed by Execution → anchored on-chain → track-record page (results immediate, positions on lag per ADR-009)`.

---

## 6. Failure modes & mitigations

| Failure | Mitigation |
|---|---|
| Malicious strategy tries to exfiltrate keys / self-deal | Sandbox with no key access + no egress; intent-only boundary (ADR-002) |
| Strategy over-trades / breaches limits | Pre-trade Risk Gate rejects; post-trade drift → slash (ADR-006) |
| Overcapitalized vault quietly goes negative-EV | Realized-data capacity caps (ADR-007) |
| Maker takes reckless risk for fee upside | First-loss + bond sized to kill the option convexity (ADR-005) |
| Internal NAV drifts from venue reality | Continuous reconciliation + kill-switch (ADR-011) |
| Strategy copied/front-run via public positions | Delayed/obfuscated position disclosure (ADR-009) |
| Oracle/resolution dispute (UMA) | Conservative marks on pending resolution; resolution-risk exposure limit in Risk Engine |
| Systemic concentration (many vaults, same trade) | Cross-vault correlation monitor + global exposure limits + global kill-switch |
| Venue outage / desync | Reconciliation break → halt; per-venue exposure caps |

---

## 7. Buildable module layout (monorepo)

```
/contracts                Solidity — ERC-4626 vault, fee/HWM, co-invest tranche,
                          bond + slashing, capacity-cap gate (Polygon)
/services
  /venue-gateway          VenueAdapter impls (Polymarket, Kalshi) → normalized model
  /marketdata             live feed normalization + external reference feeds
  /tickstore              historical tick store for deterministic backtest replay
  /strategy-runtime       Firecracker/gVisor orchestration; intent-bus producer
  /risk-gate              pre-trade + continuous risk; kill-switch; slash triggers
  /execution-oms          KMS/HSM key custody; order routing; fills
  /accounting             NAV, shares, HWM, fee accrual, reconciliation
  /capacity-oracle        realized-slippage → dynamic caps
  /attestation            signed NAV snapshots, track-record, on-chain anchoring
  /compliance             KYC/AML, geofencing, sanctions, tax export
/sdk
  /maker-sdk-py           strategy authoring (Python)
  /maker-sdk-ts           strategy authoring (TypeScript)
/packages/shared          intent schema, domain types, IDL/proto (single source of truth)
/web                      Next.js — marketplace + maker dashboard + depositor app
/docs                     EVALUATION.md, DESIGN.md, ARCHITECTURE.md
```

**Why a monorepo:** the intent schema and domain types are the contract between half a dozen services and two SDK languages; co-locating them in `/packages/shared` as the single source of truth prevents drift. The hot path (`strategy-runtime → risk-gate → execution-oms`) is split into separate services so the risk choke point is process-isolated from untrusted strategy orchestration.

---

## 8. Key interface contracts (sketches)

These are the boundaries that matter most; everything else is implementation detail behind them.

**The intent — the untrusted→trusted boundary (ADR-002):**
```ts
// packages/shared — the ONLY thing a strategy can emit. Declarative, no keys, no side effects.
type Intent =
  | { kind: "target_position"; vaultId: Id; venue: VenueId; marketId: MarketId;
      outcome: OutcomeId; targetExposure: Decimal /* signed, quote ccy */ }
  | { kind: "order"; vaultId: Id; venue: VenueId; marketId: MarketId;
      outcome: OutcomeId; side: "buy" | "sell"; size: Decimal;
      limitPrice: Decimal; tif: "GTC" | "IOC" | "FOK" }
  | { kind: "cancel"; vaultId: Id; orderId: OrderId };
// Risk Gate is free to reject, clip, or net these. The strategy cannot assume execution.
```

**The venue adapter — the venue-heterogeneity boundary (ADR-008):**
```ts
interface VenueAdapter {
  listMarkets(): Promise<Market[]>;
  orderbook(m: MarketId): Promise<OrderBook>;
  subscribe(feed: FeedSpec): AsyncIterable<MarketEvent>;       // normalized live data
  placeOrder(o: SignedOrder): Promise<Ack>;                    // called ONLY by Execution/OMS
  cancel(id: OrderId): Promise<Ack>;
  positions(account: AccountRef): Promise<Position[]>;         // for reconciliation
  balances(account: AccountRef): Promise<Balance[]>;
  resolution(m: MarketId): Promise<ResolutionStatus>;          // UMA / Kalshi settlement
}
```

**The signed NAV snapshot — the verifiability boundary (ADR-010/011):**
```ts
interface NavSnapshot {
  vaultId: Id; ts: Timestamp;
  realizedCash: Decimal; markedPositions: Decimal; nav: Decimal; navPerShare: Decimal;
  pendingResolution: Decimal;     // conservatively marked
  reconciledAgainstVenue: boolean; // false ⇒ kill-switch (ADR-011)
  sig: Signature;                  // signed by Execution; anchored on-chain by Attestation
}
```

**The vault — the value-capture boundary (ADR-004/005), Solidity sketch:**
```solidity
// ERC-4626 vault with profit-only HWM fee, first-loss tranche, slashable bond.
contract StrategyVault is ERC4626 {
    uint256 public highWaterMarkPerShare;      // ADR-004
    uint256 public makerFirstLoss;             // junior tranche, absorbs losses first (ADR-005)
    uint256 public makerBond;                  // locked, slashable (ADR-005/006)
    uint256 public capacityCap;                // set by Capacity Oracle (ADR-007)
    FeeTier  public tier;                      // perf fee + protocol cut by TVL band

    function deposit(uint256 a, address r) public override returns (uint256) {
        require(totalAssets() + a <= capacityCap, "capacity");          // ADR-007
        require(_coInvestRatioOk(a), "co-invest ratio");                // ADR-005
        return super.deposit(a, r);
    }
    function crystallizeFee() external { /* profit above HWM only, split by tier */ } // ADR-004
    function slash(SlashTrigger t, uint256 amt) external onlyRiskGate {               // ADR-006
        /* waterfall: affected depositors -> insurance fund -> burn */
    }
}
```

---

## 9. What to validate before building (carried from DESIGN §11)

1. **Co-invest ratio + bond sizing** that provably outweighs the fee's option value — model first; it's the alignment lynchpin (ADR-005).
2. **Capacity-oracle** estimator robustness and gaming-resistance (ADR-007).
3. **Redemption vs open positions** — lockup/notice policy given event-resolution illiquidity.
4. **Per-share HWM equalization** edge cases on mid-period flows (ADR-004).
5. **Regulated wrapper** jurisdiction, cost, timeline — gates the Kalshi rail (ADR-008).
6. **Position-disclosure delay** window (ADR-009).
