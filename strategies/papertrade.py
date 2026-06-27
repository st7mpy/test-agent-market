#!/usr/bin/env python3
"""Paper-trade the sample strategies behind a real Polymarket venue adapter.

    cd strategies
    python papertrade.py --strategy mm                       # offline replay (fixture)
    python papertrade.py --strategy kelly --steps 200
    python papertrade.py --strategy arb  --source live --query "election"

Wires the Phase-1 execution seams from docs/ARCHITECTURE.md:

    VenueAdapter ──book──▶ Strategy ──intents──▶ RiskGate ──approved──▶ PaperBroker
                                                     │                      │
                                                     └── rejections ◀───────┘ fills ─▶ paper P&L

`--source live` pulls a real market's live L2 books from Polymarket's public CLOB
API (no key). `--source offline` (default) replays the bundled fixture so it runs
without network. The strategy and execution code are identical for both.
"""
from __future__ import annotations

import argparse
import time

from predmkt import (
    ArbitrageStrategy, KellyEdgeStrategy, KellyParams, MarketMakerStrategy,
    MMParams, Portfolio,
)
from predmkt.data import load_fixture
from predmkt.execution import PaperBroker, PaperOMS, RiskGate, RiskLimits
from predmkt.venue import PolymarketAdapter, ReplayAdapter


def build_strategy(name: str, market_id: str, bankroll: float):
    if name == "mm":
        return MarketMakerStrategy(MMParams(market_id=market_id, quote_size=200,
                                            max_inventory=1500))
    if name == "kelly":
        s = KellyEdgeStrategy(bankroll, KellyParams(min_edge=0.015, z_window=50,
                                                    z_enter=1.5, trend_slope_max=0.0015))
        s.fair_value_fn = s.mean_reversion
        return s
    if name == "arb":
        return ArbitrageStrategy()
    raise SystemExit(f"unknown strategy {name!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Polymarket paper trading")
    ap.add_argument("--strategy", choices=["mm", "kelly", "arb"], default="mm")
    ap.add_argument("--source", choices=["offline", "live"], default="offline")
    ap.add_argument("--query", default="election", help="market search (with --source live)")
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--bankroll", type=float, default=100_000.0)
    ap.add_argument("--interval", type=float, default=2.0, help="poll seconds (live)")
    args = ap.parse_args()

    if args.source == "live":
        adapter = PolymarketAdapter(args.query, poll_interval_s=args.interval)
        print(f"LIVE  market: {adapter.market_id!r}")
    else:
        adapter = ReplayAdapter(load_fixture(), market_id="replay", outcome="YES")
        print("OFFLINE replay (fixture; resolves YES) "
              "— egress policy blocked Polymarket; use --source live with network")

    strat = build_strategy(args.strategy, adapter.market_id, args.bankroll)
    broker = PaperBroker(Portfolio(cash=args.bankroll))
    risk = RiskGate(RiskLimits(max_position_shares=5000, max_order_notional=10_000))
    oms = PaperOMS(strat, risk, broker)

    print(f"\n{'step':>5} {'mid':>6} {'intents':>8} {'appr':>5} {'rej':>4} "
          f"{'fills':>6} {'equity':>12}")
    total_rejected = 0
    last_m = None
    for step in range(args.steps):
        m = adapter.fetch_market()
        if m is None:
            break
        last_m = m
        tele = oms.step(m)
        total_rejected += len(tele.rejected)
        if step < 3 or step % max(1, args.steps // 10) == 0:
            mid = f"{tele.mid:.3f}" if tele.mid is not None else "  -  "
            print(f"{step:>5} {mid:>6} {tele.n_intents:>8} {tele.approved:>5} "
                  f"{len(tele.rejected):>4} {tele.fills:>6} {tele.equity:>12,.0f}")
        if args.source == "live":
            time.sleep(args.interval)

    # settle at resolution if known
    outcome = adapter.resolution()
    if outcome and last_m is not None:
        broker.settle(last_m, outcome)
    final_eq = broker.pf.cash + 0.0
    pos = broker.pf.position(last_m.market_id) if last_m else None

    print("\n=== paper session summary ===")
    print(f"  strategy         : {args.strategy}")
    print(f"  steps            : {len(oms.equity)}")
    print(f"  resolution       : {outcome}")
    print(f"  start equity     : ${args.bankroll:,.0f}")
    print(f"  final equity     : ${final_eq:,.0f}")
    print(f"  return           : {(final_eq / args.bankroll - 1) * 100:+.2f}%")
    print(f"  fills            : {broker.n_fills}")
    print(f"  taker fees paid  : ${broker.fees_paid:,.2f}")
    print(f"  risk rejections  : {total_rejected}")
    if pos:
        print(f"  final inventory  : YES={pos.yes:.0f}  NO={pos.no:.0f}")


if __name__ == "__main__":
    main()
