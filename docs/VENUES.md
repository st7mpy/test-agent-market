# Venue Deployment Matrix

**Purpose:** where the strategies actually deploy, what each venue costs, what it
requires, and which strategies fit which book. This operationalizes the multi-venue
posture (ADR-016, COMPETITION.md §4: *treat the venue as a frenemy*) — no strategy or
revenue line may depend on a single venue.

**Honesty note (matches `fees.py`):** all numbers below are as-researched mid-2026 and
**approximate**. Re-confirm every fee schedule and API limit against venue docs before
real capital. Live endpoints were unreachable from this build environment (egress
policy), so no figure here has been verified against a live API.

---

## 1. The landscape in one table

| Venue | Type | 30-day volume (≈, 2026) | Taker fee | Maker fee | API | Custody | Geo/reg |
|---|---|---|---|---|---|---|---|
| **Polymarket** | Hybrid CLOB, on-chain (Polygon, USDC) | ~$9.7B; >96% of on-chain category | ~0 (category-capped schedule in `fees.py`) | 0 | CLOB REST/WSS + Gamma; EIP-712 signed orders | Self-custody wallet | CFTC DCM via QCEX; US access restored |
| **Kalshi** | Centralized exchange, fiat USD | ~$6B (~53% of regulated category) | ~0.07·P·(1−P), ~0.2% headline; discounts >$50k/mo | ~0.05% **rebate**; $0.01/contract on some resting fills | REST + WSS, RSA keys; FIX for institutions | Custodial (exchange) | CFTC DCM; KYC; US-first |
| **ForecastEx** (IBKR ForecastTrader) | CFTC DCM + its own clearinghouse | smaller; institutional-leaning | $0.01/contract flat (YES+NO bids total $1.01) | **$0** | via IBKR APIs (TWS/CP) | Custodial (broker) | CFTC DCM; KYC via IBKR |
| Limitless | On-chain CLOB/AMM (Base) | <$15M combined with Myriad/Azuro | varies | varies | REST | Self-custody | Offshore |
| Myriad | On-chain (Abstract/Linea) | ↑ | varies | varies | REST | Self-custody | Offshore |
| Azuro | On-chain sports AMM protocol | ↑ (thin: $500 ticket ≈ 2–3c impact) | pool spread | LP model | Subgraph/SDK | Self-custody | Offshore |
| SX Bet | On-chain sports exchange | small | ~2% net-win style | rebates | REST/WSS | Self-custody | Offshore |
| Novig / ProphetX | US sports exchanges | small | ~commission-free spread capture | — | via aggregator | Custodial | US, state-gated |
| Manifold | Play-money | n/a | n/a | n/a | REST | n/a | n/a — **signal source only** |
| **PolyRouter** (aggregator) | Unified REST over 7 venues (Polymarket, Kalshi, Manifold, Limitless, ProphetX, Novig, SX) | — | passthrough | passthrough | one REST schema | mixed | mixed |

Fee models implemented in code: Polymarket + Kalshi + ForecastEx (`predmkt/fees.py`,
venue-dispatched via `taker_fee_per_share`). Live adapters implemented: Polymarket +
Kalshi (`predmkt/venue.py`). ForecastEx/Limitless adapters are deliberately **not**
stubbed — nothing untestable ships as code here.

## 2. Deployment tiers (the decision)

**Tier 1 — deploy now: Polymarket.** >96% of on-chain volume, effectively zero fees,
deepest books (a $4,500 ticket clears at ~2c spread on flagship contracts), no-KYC
self-custody rail matches the vault architecture (ERC-4626 on-chain custody), and the
public on-chain fill history is what powers the smart-money flow signal. Everything in
Phase 0/1 runs here first. This was already the locked founder decision; the 2026 data
still supports it.

**Tier 1.5 — second rail: Kalshi.** Already behind the `VenueAdapter` seam. Its fee
curve (peaks at P=0.50, cheap at the extremes) is the *mirror* of where Polymarket's
schedule bites, so cross-venue arb edges must be computed venue-by-venue (already the
case, ADR-016). The maker rebate (~0.05%) plus resting-fill economics feed the
venue-yield accounting (differentiator B). Custodial + KYC means it is the **regulated
wrapper's** rail, not the on-chain vault's — per PLAN.md Phase 8 it stays deferred for
real capital until the CPO/CTA work lands.

**Tier 2 — fee-model-ready: ForecastEx.** Flat $0.01/contract, **zero maker fees**, and
~3–4% APY interest passthrough on collateral (Incentive Coupon) — the strongest
venue-yield (B) economics of the three CFTC venues. Price-flat fees make it relatively
expensive for near-$1 theta trades and relatively cheap mid-range (the exact opposite
of Polymarket). Institutional custody via IBKR. Adapter work is justified once
cross-venue arb shows real Polymarket↔Kalshi edge capture.

**Tier 3 — monitor, don't build:** Limitless, Myriad, Azuro, SX, Novig, ProphetX.
Combined volume under ~$15M/month and thin books (2–3c impact for a $500 ticket) mean
capacity is below platform minimums; revisit quarterly. If more than one becomes worth
touching, integrate **once** via PolyRouter rather than N adapters. Manifold is
play-money: useless for deployment, occasionally useful as a *prior* for the signal
layer (F).

## 3. Strategy × venue fit

| Strategy (module) | Polymarket | Kalshi | ForecastEx | Notes |
|---|---|---|---|---|
| Intra-market / NegRisk arb (`arbitrage.py`) | ✅ primary | ◻ (no CTF split/merge) | ◻ | needs split/merge + NegRisk mechanics — Polymarket-specific |
| Cross-venue arb (`arbitrage.py` + `CrossVenueFeed`) | ✅ | ✅ | ⏳ after adapter | edge must survive BOTH venues' fee models; resolution-rule match is asserted, never assumed |
| Market making (`market_maker.py`) | ✅ (0 maker fee) | ✅ (rebate = venue yield) | ✅ ($0 maker + coupon) | the venue-yield (B) product lives here |
| Kelly edge + signals (`kelly_edge.py`, `signals.py`) | ✅ | ✅ | ✅ | venue-agnostic by construction |
| Relation arb (`relation_arb.py`) | ✅ primary | ✅ within-venue | ✅ within-venue | needs a curated, human-verified relation set; richest related-market graph is on Polymarket |
| Longshot-bias harvester (`longshot_bias.py`) | ✅ | ⚠️ fees bite at P=0.5 but are tiny in the tails — fine | ⚠️ $0.01 flat is material on small tail edges | calibrate `beta` per venue/category from resolved data |
| Theta convergence (`theta_convergence.py`) | ✅ (near-0 fees at extremes) | ✅ (cheap at extremes) | ⚠️ $0.01 flat eats ~25% of a 4c carry | oracle-risk gate is mandatory on Polymarket (UMA disputes) |
| Smart-money flow (`flow_signal.py`) | ✅ **only** | ❌ | ❌ | requires public per-wallet fills — uniquely on-chain; feeds Kelly on any venue |

## 4. Per-venue deployment prerequisites

**Polymarket** — Polygon wallet + USDC; orders signed EIP-712 (the platform's KMS
signer, never strategy code — ADR-002); Gamma API for discovery, CLOB REST/WSS for
books, Data API for positions/fills (`data-api.polymarket.com` — reconciliation +
flow-signal source); geofence compliance handled at the platform layer.

**Kalshi** — KYC'd account, RSA API keys, custodial balance; WSS for books; FIX only
if institutional volume justifies it. Fee tier improves >$50k/mo volume.

**ForecastEx** — IBKR account; access through IBKR Client Portal / TWS API rather than
a native venue API; contracts clear through ForecastEx's own DCO. Collateral earns the
Incentive Coupon — record it in the Phase-0 journal's venue-yield line (B).

## 5. Sources

- [QuantVPS — highest-volume prediction markets 2026](https://www.quantvps.com/blog/prediction-markets-volume-compared)
- [tech-insider — crypto prediction markets 2026](https://tech-insider.org/prediction-markets/crypto-prediction-markets/)
- [tech-insider — ForecastEx review, June 2026](https://tech-insider.org/prediction-markets/platforms/forecastex-review/)
- [pm.wiki — ForecastEx / IBKR ForecastTrader guide](https://pm.wiki/learn/forecastex-prediction-market)
- [IBKR — event-contract pricing](https://www.interactivebrokers.com/en/pricing/commissions-events.php)
- [Prediction Hunt — prediction-market APIs](https://www.predictionhunt.com/blog/best-api-for-prediction-markets)
- [Interexy — aggregator integration (PolyRouter)](https://interexy.com/how-to-integrate-prediction-market-aggregators)
- [defirate — US prediction-market apps 2026](https://defirate.com/prediction-markets/)
- Repo: `docs/COMPETITION.md` §4–5 (venue platform risk, aggregation layer), `docs/DIFFERENTIATION.md` (B/D/F), `predmkt/fees.py`.
