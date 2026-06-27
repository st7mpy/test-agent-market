#!/usr/bin/env python3
"""Phase 0 trade journal — log every real fill and compute net PnL.

Usage
-----
    cd strategies

    # Log a fill (interactive or scripted):
    python phase0_journal.py add \
        --market "Will candidate X win?" \
        --token YES --side BUY \
        --price 0.42 --shares 100 \
        --fee 0.35 --gas 0.01 \
        --timestamp "2026-01-15T14:32:00Z"

    # Add a settlement (market resolved):
    python phase0_journal.py settle \
        --market "Will candidate X win?" --outcome YES

    # Print running P&L and gate status:
    python phase0_journal.py status

Journal is stored in phase0_journal.json (same directory).
All monetary amounts are in USDC.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

JOURNAL_FILE = os.path.join(os.path.dirname(__file__), "phase0_journal.json")

# Phase 0 gate thresholds (PLAN.md §0)
GATE_MIN_TRADES     = 100
GATE_MIN_WEEKS      = 6
GATE_MIN_NET_PNL    = 0.0     # must be strictly positive
GATE_MIN_SHARPE     = 0.0     # must be strictly positive


# ─────────────────────────── data model ──────────────────────────────────────

def _load() -> dict:
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE) as f:
            content = f.read().strip()
            if content:
                return json.loads(content)
    return {"fills": [], "settlements": {}}


def _save(j: dict) -> None:
    with open(JOURNAL_FILE, "w") as f:
        json.dump(j, f, indent=2)


# ─────────────────────────── commands ────────────────────────────────────────

def cmd_add(args) -> None:
    j = _load()
    ts = args.timestamp or datetime.now(timezone.utc).isoformat()
    entry = {
        "ts":      ts,
        "market":  args.market,
        "token":   args.token,
        "side":    args.side,
        "price":   args.price,
        "shares":  args.shares,
        "fee":     args.fee,
        "gas":     args.gas,
        "note":    args.note or "",
    }
    j["fills"].append(entry)
    _save(j)
    notional = args.price * args.shares
    print(f"  logged: {args.side} {args.shares:.0f}x {args.token} @ {args.price:.3f} "
          f"on '{args.market}' | notional ${notional:.2f} | fee ${args.fee:.4f} gas ${args.gas:.4f}")


def cmd_settle(args) -> None:
    j = _load()
    j["settlements"][args.market] = args.outcome
    _save(j)
    print(f"  settled: '{args.market}' -> {args.outcome}")


def cmd_status(args) -> None:
    j = _load()
    fills: List[dict] = j["fills"]
    settlements: Dict[str, str] = j["settlements"]

    if not fills:
        print("No fills logged yet. Use: python phase0_journal.py add ...")
        return

    # ── per-market position accounting ───────────────────────────────────────
    # position[mkt][token] = {shares, cost_basis, fees_paid}
    position: Dict[str, Dict[str, dict]] = {}
    total_fees = 0.0
    trade_count = 0

    for f in fills:
        mkt = f["market"]
        tok = f["token"]
        pos = position.setdefault(mkt, {}).setdefault(tok, {"shares": 0.0, "cost": 0.0})
        sign = 1 if f["side"] == "BUY" else -1
        pos["shares"] += sign * f["shares"]
        pos["cost"]   += sign * f["price"] * f["shares"]
        total_fees    += f["fee"] + f["gas"]
        trade_count   += 1

    # ── realized PnL (settled markets) ───────────────────────────────────────
    realized = 0.0
    for mkt, outcome in settlements.items():
        if mkt not in position:
            continue
        for tok, pos in position[mkt].items():
            if pos["shares"] == 0:
                continue
            payout_per_share = 1.0 if tok == outcome else 0.0
            proceeds = pos["shares"] * payout_per_share
            cost     = pos["cost"]
            realized += proceeds - cost

    # ── unrealized PnL (mark at last fill price) ──────────────────────────────
    unrealized = 0.0
    for mkt, toks in position.items():
        if mkt in settlements:
            continue
        for tok, pos in toks.items():
            if pos["shares"] == 0:
                continue
            # last fill price for this token as mark
            last_price = next(
                (f["price"] for f in reversed(fills)
                 if f["market"] == mkt and f["token"] == tok),
                0.5,
            )
            mark_value = pos["shares"] * last_price
            unrealized += mark_value - pos["cost"]

    gross_pnl = realized + unrealized
    net_pnl   = gross_pnl - total_fees

    # ── time span ────────────────────────────────────────────────────────────
    timestamps = [_parse_ts(f["ts"]) for f in fills]
    t_first = min(timestamps)
    t_last  = max(timestamps)
    span_days  = max((t_last - t_first).days, 1)
    span_weeks = span_days / 7.0

    # ── per-day PnL for Sharpe ────────────────────────────────────────────────
    daily: Dict[str, float] = {}
    for f in fills:
        day = _parse_ts(f["ts"]).strftime("%Y-%m-%d")
        sign = 1 if f["side"] == "BUY" else -1
        cash_flow = -(sign * f["price"] * f["shares"]) - f["fee"] - f["gas"]
        daily[day] = daily.get(day, 0.0) + cash_flow
    # add settlements
    for mkt, outcome in settlements.items():
        if mkt not in position:
            continue
        for tok, pos in position[mkt].items():
            if pos["shares"] == 0:
                continue
            payout = pos["shares"] * (1.0 if tok == outcome else 0.0)
            settle_day = t_last.strftime("%Y-%m-%d")  # approximate
            daily[settle_day] = daily.get(settle_day, 0.0) + payout

    vals = list(daily.values())
    sharpe = _sharpe(vals)

    # ── gate check ───────────────────────────────────────────────────────────
    gate_trades  = trade_count >= GATE_MIN_TRADES
    gate_weeks   = span_weeks  >= GATE_MIN_WEEKS
    gate_pnl     = net_pnl     >  GATE_MIN_NET_PNL
    gate_sharpe  = sharpe       >  GATE_MIN_SHARPE
    gate_pass    = gate_trades and gate_weeks and gate_pnl and gate_sharpe

    def _tick(ok: bool) -> str:
        return "✅" if ok else "❌"

    print()
    print("═" * 56)
    print("  PHASE 0 JOURNAL STATUS")
    print("═" * 56)
    print(f"  Trades logged   : {trade_count:>6}   (need ≥ {GATE_MIN_TRADES})")
    print(f"  Span            : {span_weeks:>5.1f} wk  (need ≥ {GATE_MIN_WEEKS} wk)")
    print(f"  Gross PnL       : ${gross_pnl:>+9.2f}")
    print(f"  Fees + gas      : ${total_fees:>+9.2f}")
    print(f"  Net PnL         : ${net_pnl:>+9.2f}  (need > $0)")
    print(f"  Daily Sharpe    : {sharpe:>+7.3f}   (need > 0)")
    print()
    print("  Gate criteria:")
    print(f"    {_tick(gate_trades)}  ≥ {GATE_MIN_TRADES} trades")
    print(f"    {_tick(gate_weeks)}  ≥ {GATE_MIN_WEEKS} weeks of data")
    print(f"    {_tick(gate_pnl)}  net PnL > $0")
    print(f"    {_tick(gate_sharpe)}  daily Sharpe > 0")
    print()
    if gate_pass:
        print("  ██ PHASE 0 GATE: PASS — positive net edge documented.")
        print("     Proceed to Phase 1 (automate + hosted bot).")
    else:
        remaining = []
        if not gate_trades:
            remaining.append(f"{GATE_MIN_TRADES - trade_count} more trades")
        if not gate_weeks:
            remaining.append(f"{GATE_MIN_WEEKS - span_weeks:.1f} more weeks")
        if not gate_pnl:
            remaining.append("positive net PnL")
        if not gate_sharpe:
            remaining.append("positive Sharpe")
        print(f"  ░░ PHASE 0 GATE: NOT YET. Still need: {', '.join(remaining)}.")
    print("═" * 56)
    print()

    # ── per-market breakdown ──────────────────────────────────────────────────
    if fills:
        print("  Open positions:")
        for mkt, toks in position.items():
            if mkt in settlements:
                continue
            for tok, pos in toks.items():
                if abs(pos["shares"]) > 1e-9:
                    print(f"    {tok:<3}  {pos['shares']:>+8.0f} sh   cost ${pos['cost']:>+.2f}  "
                          f"mkt: {mkt[:48]}")
        print()


def cmd_list(args) -> None:
    j = _load()
    for i, f in enumerate(j["fills"][-50:], 1):
        notional = f["price"] * f["shares"]
        print(f"  {i:>3}. {f['ts'][:19]}  {f['side']:<4} {f['shares']:>6.0f}x "
              f"{f['token']:<3} @ {f['price']:.3f}  "
              f"fee ${f['fee']:.4f}  gas ${f['gas']:.4f}  "
              f"{f['market'][:40]}")


# ─────────────────────────── helpers ─────────────────────────────────────────

def _parse_ts(ts: str) -> datetime:
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {ts!r}")


def _sharpe(daily_returns: List[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    n = len(daily_returns)
    mu = sum(daily_returns) / n
    var = sum((x - mu) ** 2 for x in daily_returns) / (n - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    return (mu / std) * math.sqrt(252)   # annualised


# ─────────────────────────── CLI ─────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Phase 0 trade journal — log fills, compute net PnL, check gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # add
    p_add = sub.add_parser("add", help="Log one real fill")
    p_add.add_argument("--market",    required=True, help="Market question (unique identifier)")
    p_add.add_argument("--token",     choices=["YES", "NO"], required=True)
    p_add.add_argument("--side",      choices=["BUY", "SELL"], required=True)
    p_add.add_argument("--price",     type=float, required=True, help="Fill price [0,1]")
    p_add.add_argument("--shares",    type=float, required=True)
    p_add.add_argument("--fee",       type=float, default=0.0, help="Taker fee paid (USDC)")
    p_add.add_argument("--gas",       type=float, default=0.0, help="Gas cost (USDC)")
    p_add.add_argument("--timestamp", default=None, help="ISO-8601; defaults to now")
    p_add.add_argument("--note",      default="", help="Free-text note")

    # settle
    p_settle = sub.add_parser("settle", help="Record a market resolution")
    p_settle.add_argument("--market",  required=True)
    p_settle.add_argument("--outcome", choices=["YES", "NO"], required=True)

    # status
    sub.add_parser("status", help="Print PnL summary and gate check")

    # list
    sub.add_parser("list", help="List last 50 fills")

    args = ap.parse_args()
    {
        "add":    cmd_add,
        "settle": cmd_settle,
        "status": cmd_status,
        "list":   cmd_list,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
