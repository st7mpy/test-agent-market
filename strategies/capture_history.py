#!/usr/bin/env python3
"""Capture a live Polymarket market's mid-price into a backtestable series.

    cd strategies
    # sample every 30s for 2h, into btc1m.json:
    python capture_history.py --query "bitcoin hit $1m" --out btc1m.json --interval 30 --steps 240
    # ...then replay it:
    python backtest.py --strategy mm --file btc1m.json --outcome YES

Why: the free CLOB `prices-history` endpoint is sparse for many markets (see
DEPLOY_DATA.md / ADR-010). Polling a live market forward is the honest way to build
real backtest data. Output matches the bundled-fixture schema
(``{"history": [{"t": unix, "p": mid}, ...]}``) so `backtest.py --file` replays it.
Appends/resumes if --out already exists; save is incremental (crash-safe).
"""
from __future__ import annotations

import argparse
import json
import os
import time

from predmkt import data


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture a live Polymarket mid-price series")
    ap.add_argument("--query", required=True, help="market search (substring of the question)")
    ap.add_argument("--out", required=True, help="output JSON path (fixture schema)")
    ap.add_argument("--interval", type=float, default=30.0, help="seconds between samples")
    ap.add_argument("--steps", type=int, default=120, help="number of samples to collect")
    ap.add_argument("--pages", type=int, default=6, help="market-search depth (pages of 50 by volume)")
    ap.add_argument("--closed", action="store_true", help="search resolved markets instead of active")
    args = ap.parse_args()

    info = data.discover_token(args.query, closed=args.closed, max_pages=args.pages)
    if not info:
        raise SystemExit(
            f"no {'resolved' if args.closed else 'active'} market matched {args.query!r} in the "
            f"top {args.pages * 50} by volume — try a more specific --query or a higher --pages.")
    token = info["yes_token_id"]
    print(f"capturing: {info['question']!r}")
    print(f"  -> {args.out}   ({args.steps} samples @ {args.interval:g}s ~ "
          f"{args.steps * args.interval / 60:.1f} min)")

    history: list = []
    if os.path.exists(args.out):
        try:
            history = json.load(open(args.out)).get("history", [])
            print(f"  resuming: {len(history)} existing points")
        except Exception:
            history = []

    def save() -> None:
        with open(args.out, "w") as f:
            json.dump({"question": info["question"], "captured": True, "history": history}, f, indent=0)

    try:
        for i in range(args.steps):
            try:
                mid = data.fetch_polymarket_book(token).mid()
            except Exception as e:  # noqa: BLE001
                print(f"  [{i + 1}/{args.steps}] fetch error: {str(e).splitlines()[0][:90]}")
                mid = None
            if mid is not None:
                history.append({"t": int(time.time()), "p": round(mid, 4)})
                save()
                print(f"  [{i + 1}/{args.steps}] mid={mid:.3f}   (saved {len(history)} pts)")
            if i < args.steps - 1:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n  interrupted — series saved so far.")

    print(f"done: {len(history)} points -> {args.out}")


if __name__ == "__main__":
    main()
