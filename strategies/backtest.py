#!/usr/bin/env python3
"""Tiny Polymarket backtest harness (price-replay).

    cd strategies
    python backtest.py --strategy mm           # market maker on the bundled fixture
    python backtest.py --strategy kelly        # Kelly mean-reversion on the fixture
    python backtest.py --strategy mm --live --query "election"   # real Polymarket data
    python backtest.py --strategy mm --file series.json          # replay a captured series

It replays a single market's historical YES mid-price, synthesises an order book
around each mid (configurable spread/depth), runs a strategy, simulates fills,
marks to market, settles at the known resolution, and reports metrics.

LIMITATIONS (be honest — see docs/ARCHITECTURE.md ADR-010):
  * price-replay only. The public API gives a mid series, not full L2 depth, so
    books are SYNTHESISED — slippage beyond top-of-book and queue position are
    not modelled. Maker fills are optimistic (filled whenever the mid touches
    the quote). Treat results as directional, not a verified track record.
  * arbitrage needs multiple token books / true L2 data, so it is not covered by
    this single-series harness (only `mm` and `kelly`).
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from typing import List, Tuple

from predmkt import (
    Context, Fill, KellyEdgeStrategy, KellyParams, LimitOrder, MarketMakerStrategy,
    MMParams, Portfolio, Side, Split, Merge, TIF, Token,
)
from predmkt.data import DEFAULT_FIXTURE, discover_token, fetch_polymarket_history, load_fixture
from predmkt.fees import polymarket_taker_fee
from predmkt.sim import binary_market

PricePoint = Tuple[int, float]


@dataclass
class Resting:
    side: Side
    price: float
    size: float


@dataclass
class Result:
    bankroll: float
    equity: List[float] = field(default_factory=list)
    n_trades: int = 0
    fees_paid: float = 0.0
    final_pos_yes: float = 0.0
    final_pos_no: float = 0.0

    def total_return(self) -> float:
        return self.equity[-1] / self.bankroll - 1.0 if self.equity else 0.0

    def max_drawdown(self) -> float:
        peak, mdd = -1e18, 0.0
        for e in self.equity:
            peak = max(peak, e)
            mdd = max(mdd, (peak - e) / peak if peak > 0 else 0.0)
        return mdd

    def sharpe(self) -> float:
        rets = [self.equity[i] / self.equity[i - 1] - 1.0
                for i in range(1, len(self.equity)) if self.equity[i - 1] > 0]
        if len(rets) < 2:
            return 0.0
        mu = sum(rets) / len(rets)
        var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        return (mu / sd) if sd > 1e-12 else 0.0   # per-step, not annualised


def run_backtest(strategy, history: List[PricePoint], *, outcome: str = "YES",
                 bankroll: float = 100_000.0, category: str = "politics",
                 spread: float = 0.01, depth: float = 1000.0) -> Result:
    pf = Portfolio(cash=bankroll)
    res = Result(bankroll=bankroll)
    mid_key = "m"
    resting: List[Resting] = []
    n = len(history)

    def position():
        return pf.position(mid_key)

    for i, (t, p) in enumerate(history):
        # --- 1. fill resting maker quotes against the new mid (optimistic) ---
        still: List[Resting] = []
        for r in resting:
            if r.side == Side.BUY and p <= r.price:          # price came down to our bid
                position().yes += r.size
                pf.cash -= r.size * r.price                   # maker fee = 0 on Polymarket
                strategy.on_fill(Fill(mid_key, Token.YES, Side.BUY, r.price, r.size))
                res.n_trades += 1
            elif r.side == Side.SELL and p >= r.price:        # price rose to our ask
                position().yes -= r.size
                pf.cash += r.size * r.price
                strategy.on_fill(Fill(mid_key, Token.YES, Side.SELL, r.price, r.size))
                res.n_trades += 1
            else:
                still.append(r)
        resting = still

        # --- 2. ask the strategy for intents on the current snapshot ---
        m = binary_market(mid_key, yes_mid=p, spread=spread, size=depth,
                          category=category, time_to_resolution=float(n - i))
        intents = strategy.on_tick(Context(now=float(t), markets={mid_key: m},
                                           portfolio=pf))

        # --- 3. execute intents (GTC quotes cancel-replace the prior tick's) ---
        new_resting: List[Resting] = []
        for it in intents:
            if isinstance(it, Split):
                pf.cash -= it.usdc
                position().yes += it.usdc
                position().no += it.usdc
            elif isinstance(it, Merge):
                position().yes -= it.shares
                position().no -= it.shares
                pf.cash += it.shares
            elif isinstance(it, LimitOrder):
                if it.tif in (TIF.IOC, TIF.FOK):             # taker: fill now at limit
                    fee = polymarket_taker_fee(it.price, it.size, category)
                    res.fees_paid += fee
                    res.n_trades += 1
                    pos = position()
                    delta = it.size if it.side == Side.BUY else -it.size
                    if it.side == Side.BUY:
                        pf.cash -= it.size * it.price + fee
                    else:
                        pf.cash += it.size * it.price - fee
                    if it.token == Token.YES:
                        pos.yes += delta
                    else:
                        pos.no += delta
                    strategy.on_fill(Fill(mid_key, it.token, it.side, it.price, it.size))
                elif it.token == Token.YES:                  # GTC maker quote: rest it
                    new_resting.append(Resting(it.side, it.price, it.size))
            # CancelAll (or simply emitting fresh quotes) cancels stale resting orders
        resting = new_resting

        # --- 4. mark to market ---
        pos = position()
        equity = pf.cash + pos.yes * p + pos.no * (1.0 - p)
        res.equity.append(equity)

    # --- 5. settle at resolution ---
    pos = position()
    payoff = pos.yes if outcome == "YES" else pos.no
    pf.cash += payoff                                        # winning shares pay $1
    res.equity.append(pf.cash)
    res.final_pos_yes, res.final_pos_no = pos.yes, pos.no
    return res


def report(name: str, res: Result) -> None:
    print(f"\n=== {name} ===")
    print(f"  ticks            : {len(res.equity) - 1}")
    print(f"  start equity     : ${res.bankroll:,.0f}")
    print(f"  final equity     : ${res.equity[-1]:,.0f}")
    print(f"  total return     : {res.total_return() * 100:+.2f}%")
    print(f"  max drawdown     : {res.max_drawdown() * 100:.2f}%")
    print(f"  per-step Sharpe  : {res.sharpe():.3f}")
    print(f"  trades           : {res.n_trades}")
    print(f"  taker fees paid  : ${res.fees_paid:,.2f}")
    print(f"  final inventory  : YES={res.final_pos_yes:.0f}  NO={res.final_pos_no:.0f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Polymarket price-replay backtest")
    ap.add_argument("--strategy", choices=["mm", "kelly"], default="mm")
    ap.add_argument("--live", action="store_true", help="fetch real Polymarket data")
    ap.add_argument("--query", default="election", help="market search (with --live)")
    ap.add_argument("--pages", type=int, default=6, help="search depth for --live (pages of 50 by volume)")
    ap.add_argument("--file", default=None, help="replay a captured history JSON (see capture_history.py)")
    ap.add_argument("--outcome", choices=["YES", "NO"], default=None, help="assumed resolution (override / for --file)")
    ap.add_argument("--bankroll", type=float, default=100_000.0)
    args = ap.parse_args()

    outcome = "YES"
    if args.live:
        info = discover_token(args.query, max_pages=args.pages)
        if not info:
            raise SystemExit(
                f"no resolved market matched {args.query!r} in the top {args.pages * 50} by "
                f"volume — try a more specific --query or a higher --pages.")
        print(f"market: {info['question']!r}  outcome={info['outcome']}")
        history = fetch_polymarket_history(info["yes_token_id"])
        outcome = info["outcome"] or "YES"
        if not history:
            raise SystemExit(
                f"'{info['question']}' returned 0 price points from the free prices-history "
                f"endpoint (common for older / low-liquidity markets). Try another --query, or "
                f"capture a live series instead:\n"
                f"    python capture_history.py --query {args.query!r} --out series.json\n"
                f"    python backtest.py --strategy {args.strategy} --file series.json --outcome YES")
    elif args.file:
        history = load_fixture(args.file)
        print(f"replay: {args.file} ({len(history)} points)")
    else:
        history = load_fixture(DEFAULT_FIXTURE)
        print(f"fixture: {DEFAULT_FIXTURE} ({len(history)} points; resolves YES)")
        print("  [offline fixture — for real data use --live (headers now clear Cloudflare) or --file]")

    if args.outcome:
        outcome = args.outcome

    if args.strategy == "mm":
        strat = MarketMakerStrategy(MMParams(market_id="m", quote_size=200,
                                             max_inventory=1500))
        run = run_backtest(strat, history, outcome=outcome, bankroll=args.bankroll)
        report("market_maker", run)
    else:
        strat = KellyEdgeStrategy(
            args.bankroll,
            KellyParams(min_edge=0.015, z_window=50, z_enter=1.5, trend_slope_max=0.0015),
            fair_value_fn=None)
        strat.fair_value_fn = strat.mean_reversion         # own-price signal, no external data
        run = run_backtest(strat, history, outcome=outcome, bankroll=args.bankroll)
        report("kelly_mean_reversion", run)


if __name__ == "__main__":
    main()
