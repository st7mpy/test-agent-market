#!/usr/bin/env python3
"""Live/poll trading loop with position reconciliation (Phase-1 reconcile invariant).

    cd strategies
    python live.py --strategy mm                              # offline replay
    python live.py --strategy mm --inject-divergence-at 100   # demo the halt
    python live.py --strategy mm --source live --query "election"

Each cycle: fetch the book, run one OMS step, let the (simulated) venue record the
fills, and PERIODICALLY reconcile the OMS's internal positions against the venue's.
On any divergence beyond tolerance it trips the kill-switch and halts — the
position-level form of ARCHITECTURE.md ADR-011 (reconcile to reality or stop).

NOTE on WebSockets: production should consume Polymarket's market WSS feed
(wss://ws-subscriptions-clob.polymarket.com/ws/market) for push book updates. That
needs an async WS client (extra dependency) and a network this session blocks, so
this skeleton polls the REST CLOB `/book` instead; the loop body is identical.
"""
from __future__ import annotations

import argparse
import time
from typing import Optional

from predmkt import Portfolio
from predmkt.data import load_fixture
from predmkt.execution import PaperBroker, PaperOMS, RiskGate, RiskLimits
from predmkt.reconcile import Reconciler
from predmkt.venue import PolymarketAdapter, ReplayAdapter, VenueAdapter
from papertrade import build_strategy


def run(adapter: VenueAdapter, strategy, broker: PaperBroker, risk: RiskGate, *,
        steps: int = 400, reconcile_every: int = 25, tolerance: float = 1e-6,
        inject_at: Optional[int] = None, inject_yes: float = 500.0,
        live: bool = False, interval: float = 2.0, verbose: bool = True) -> dict:
    oms = PaperOMS(strategy, risk, broker)
    recon = Reconciler(tolerance)
    halted, breach = False, []
    last_m = None
    skipped_recon = 0

    for step in range(steps):
        m = adapter.fetch_market()
        if m is None:
            break
        last_m = m
        tele = oms.step(m)
        adapter.record_fills(tele.fill_list)

        if inject_at is not None and step == inject_at and hasattr(adapter, "inject_divergence"):
            adapter.inject_divergence(m.market_id, yes=inject_yes)
            if verbose:
                print(f"  [fault injected at step {step}: venue YES +{inject_yes:.0f}]")

        if step % reconcile_every == 0:
            venue_pos = adapter.positions()
            internal_nonzero = any(p.yes or p.no for p in broker.pf.positions.values())
            if not venue_pos and internal_nonzero:
                skipped_recon += 1                       # no venue truth (e.g. live w/o address)
            else:
                res = recon.reconcile(broker.pf.positions, venue_pos)
                if not res.ok:
                    risk.kill_switch = True
                    halted = True
                    breach = res.breaches(tolerance)
                    if verbose:
                        for d in breach:
                            print(f"  !! RECON BREACH {d.market_id}: "
                                  f"internal YES={d.internal_yes:.0f} venue YES={d.venue_yes:.0f} "
                                  f"(|Δ|={d.max_abs():.0f}) -> kill-switch, HALT (ADR-011)")
                    break

        if verbose and (step < 3 or step % max(1, steps // 8) == 0):
            mid = f"{tele.mid:.3f}" if tele.mid is not None else "  -  "
            print(f"  step {step:>4} mid {mid} fills {tele.fills:>3} "
                  f"equity ${tele.equity:,.0f}")
        if live:
            time.sleep(interval)

    outcome = adapter.resolution()
    if outcome and last_m is not None and not halted:
        broker.settle(last_m, outcome)
    return {
        "halted": halted,
        "breach": breach,
        "steps_run": len(oms.equity),
        "skipped_reconciliations": skipped_recon,
        "final_equity": broker.pf.cash if (outcome and not halted) else (oms.equity[-1] if oms.equity else broker.pf.cash),
        "resolution": outcome,
        "kill_switch": risk.kill_switch,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Live loop + reconciliation")
    ap.add_argument("--strategy", choices=["mm", "kelly", "arb"], default="mm")
    ap.add_argument("--source", choices=["offline", "live"], default="offline")
    ap.add_argument("--query", default="election")
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--reconcile-every", type=int, default=25)
    ap.add_argument("--inject-divergence-at", type=int, default=None)
    ap.add_argument("--bankroll", type=float, default=100_000.0)
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    if args.source == "live":
        adapter: VenueAdapter = PolymarketAdapter(args.query, poll_interval_s=args.interval)
        print(f"LIVE market: {adapter.market_id!r}")
    else:
        adapter = ReplayAdapter(load_fixture(), market_id="replay", outcome="YES")
        print("OFFLINE replay (fixture; resolves YES)")

    strat = build_strategy(args.strategy, adapter.market_id, args.bankroll)
    broker = PaperBroker(Portfolio(cash=args.bankroll))
    risk = RiskGate(RiskLimits(max_position_shares=5000, max_order_notional=10_000))

    print(f"\nreconciling internal vs venue every {args.reconcile_every} steps "
          f"(ADR-011: halt on divergence)\n")
    out = run(adapter, strat, broker, risk, steps=args.steps,
              reconcile_every=args.reconcile_every,
              inject_at=args.inject_divergence_at,
              live=(args.source == "live"), interval=args.interval)

    print("\n=== live session summary ===")
    print(f"  strategy           : {args.strategy}")
    print(f"  steps run          : {out['steps_run']}")
    print(f"  halted on recon    : {out['halted']}")
    print(f"  kill-switch        : {out['kill_switch']}")
    print(f"  skipped recons     : {out['skipped_reconciliations']}")
    print(f"  resolution         : {out['resolution']}")
    print(f"  final equity       : ${out['final_equity']:,.0f}")
    if out["halted"]:
        print("  -> trading halted on position divergence; no settlement (positions untrusted)")


if __name__ == "__main__":
    main()
