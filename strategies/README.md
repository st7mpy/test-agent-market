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

## Backtest on real Polymarket data

A tiny **price-replay** backtester (`backtest.py`) replays one market's historical
YES mid-price, synthesises a book around each mid, runs a strategy, simulates fills,
settles at resolution, and reports metrics:

```bash
python backtest.py --strategy mm                      # market maker on bundled fixture
python backtest.py --strategy kelly                   # Kelly mean-reversion on fixture
python backtest.py --strategy mm --live --query "election"   # real Polymarket data
```

Data comes from Polymarket's public endpoints (`predmkt/data.py`): Gamma for market
discovery and the CLOB `prices-history` series. **No API key needed.** With `--live`
it pulls a real resolved market; without it, it uses a bundled, schema-accurate
fixture (`data/sample_history.json`) so it runs offline.

> The fixture is **synthetic-but-schema-accurate** (an election-style market resolving
> YES). Real data couldn't be fetched at authoring time because this environment's egress
> policy blocks `polymarket.com`; run `--live` where network is available to use a real series.

Sample run (fixture) — note the results are deliberately unremarkable, which is the
point: the market maker is **adversely selected** on a strongly trending market (it ends
short YES and can't flatten because nothing sells to it into a rising market — exactly the
resolution risk the strategy docstring warns about), and Kelly's guard suppresses most fades:

```
market_maker : total return -0.27%  | trades 29 | final inventory YES=-1400
kelly        : total return +0.13%  | trades  2 | final inventory YES=+400
```

> **These are NOT a verified track record.** Price-replay synthesises books (no true L2
> depth, optimistic maker fills, no queue position). Per `../docs/PLAN.md` Phase 0, only a
> real-money, signed track record gates capital — backtests never do. Arbitrage needs
> multiple token books / true L2 data, so the single-series harness covers only `mm` and `kelly`.

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
  data.py          # live Polymarket public API (Gamma + CLOB) + fixture loader
data/sample_history.json  # offline price-history fixture (Polymarket schema)
demo.py            # runnable demonstration
backtest.py        # price-replay backtester (real data via --live, else fixture)
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
