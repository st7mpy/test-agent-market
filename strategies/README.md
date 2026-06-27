# Sample Strategies (`predmkt`)

Clean-room, runnable **sample trading strategies** for the prediction-market vault
platform — the first concrete deliverable of **Phase 0** in [`../docs/PLAN.md`](../docs/PLAN.md).

Three strategy families, mapping to what the platform advertises (Arb / Kelly / mispricing):

| Strategy | File | Idea |
|---|---|---|
| **Arbitrage** | `predmkt/arbitrage.py` | Near-risk-free: intra-market YES/NO, combinatorial (NegRisk) dutch-book, and cross-venue |
| **Market making** | `predmkt/market_maker.py` | Avellaneda–Stoikov inventory model adapted to bounded [0,1] binary markets |
| **Forecast-edge + Kelly** | `predmkt/kelly_edge.py` | Fair-value estimate → edge vs price → fractional-Kelly sizing; + mean-reversion |

> ⚠️ **These are educational reference implementations, not turnkey money-printers.**
> Parameters are illustrative defaults; the platform's plan (PLAN.md, Phase 0) requires a
> real **verified, real-money** track record — not backtests — before any capital is allocated.
> Nothing here is financial advice.

## Run it

```bash
cd strategies
python demo.py            # prints the intents each strategy emits on synthetic scenarios
python tests/test_smoke.py   # 5 dependency-free smoke tests
```

Pure standard library — no dependencies, no network.

## How they fit the platform

Each strategy implements the **intent-based execution boundary** from
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) (ADR-002): it reads market state and
returns a list of declarative **`Intent`s** (`LimitOrder`, `Split`, `Merge`, `Convert`,
`CancelAll`). It **never holds keys or funds** and cannot assume execution — the platform's
Risk Gate validates every intent and the Execution/OMS signs and routes it. That's exactly
how an untrusted maker strategy will run inside the sandbox.

```
predmkt/
  types.py         # domain types + the Intent vocabulary
  fees.py          # Polymarket (min(p,1-p) + per-100 cap) and Kalshi fee models
  base.py          # Strategy base class + per-tick Context
  arbitrage.py     # strategy 1
  market_maker.py  # strategy 2
  kelly_edge.py    # strategy 3
  sim.py           # tiny offline simulator + synthetic order-book builders
demo.py            # runnable demonstration
tests/test_smoke.py
```

## Strategy notes

**Arbitrage.** Built on the identity that a complete set (1 YES + 1 NO) is worth exactly $1.
Buys both legs when `ask_YES + ask_NO + fees < 1 − θ`; mints-and-sells when the bids sum
above $1; extends to multi-outcome NegRisk baskets and to cross-venue pairs. **Refuses to
trade cross-venue when resolution rules don't match** — that's basis risk, not arbitrage.

**Market making.** Quotes around an inventory-adjusted reservation price
`r = s − q·γ·σ²·τ` with half-spread `½(γσ²τ + (2/γ)ln(1+γ/k))`. Adapted for prediction
markets: prices clamped to [tick, 1−tick]; σ a capped EWMA; inventory **normalised** before
skewing (share counts in the hundreds otherwise saturate a [0,1] range); τ floored and γ
ramped up near resolution (inventory jumps to 0/1, it doesn't de-risk smoothly); a min-spread
floor and a max-spread cap; one-sided quoting at the inventory cap; pull-on-vol-spike.

**Forecast-edge + Kelly.** `f* = (p − m)/(1 − m)` scaled by a fractional-Kelly λ (default ¼,
because `p` is estimated and full Kelly badly overbets on error). Fair value `p` is pluggable:
an external reference anchor (built-in) or an own-price mean-reversion z-score with a trend/news
regime guard (built-in). Layered risk caps: min-edge-after-fees, per-market fraction, depth,
per-category and gross exposure, and a daily stop.

## Provenance & licensing

**Our code is original and MIT-licensed** (see `LICENSE`). The strategies were written
clean-room from the *techniques* (algorithms and math, which are not copyrightable) after
researching public sources. **No third-party source code was copied.** Reference material
consulted (verify each repo's license before reusing any of *their* code):

| Reference | License | Used for |
|---|---|---|
| Polymarket/ctf-exchange, neg-risk-ctf-adapter, py-clob-client | MIT | CTF split/merge + NegRisk + API semantics |
| Hummingbot (Avellaneda–Stoikov strategy) | Apache-2.0 | A–S parameter intuition |
| javifalces/HFTFramework | Apache-2.0 | A–S tuning intuition |
| Avellaneda & Stoikov (2008); arXiv:2510.15205 | papers | MM math + bounded-market adaptation |
| guberm/polymarket-bot | MIT | Layered-cap intuition (Kelly) |
| Kelly (1956); arXiv:1603.06183 (Risk-Constrained Kelly) | papers | Sizing math |
| arXiv:2508.03474 (Arbitrage in Prediction Markets) | paper | Arb conditions |

> Fee numbers and venue mechanics are modelled approximately for illustration — confirm exact
> schedules (Polymarket fees, Kalshi `0.07·C·P·(1−P)`) against current venue docs before live use.
