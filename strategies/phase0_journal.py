#!/usr/bin/env python3
"""Phase 0 trade journal — log every real fill, rebate, and reward; compute net PnL.

The Phase-0 wedge is **venue-yield market-making** (DIFFERENTIATION.md B): makers
earn 20-25% of taker fees as **rebates** plus **liquidity rewards** for resting
orders near mid. That income is the edge being proven — so it is logged alongside
fills, and the Phase-0 gate is judged on PnL **net of a venue-yield haircut**
(assume the rebate/reward program tightens), not on the as-earned number.

Usage
-----
    cd strategies

    # Log a fill:
    python phase0_journal.py add \
        --market "Will candidate X win?" \
        --token YES --side BUY \
        --price 0.42 --shares 100 \
        --fee 0.35 --gas 0.01 \
        --timestamp "2026-01-15T14:32:00Z"

    # Log venue-yield income (the wedge):
    python phase0_journal.py income --kind rebate --amount 12.40
    python phase0_journal.py income --kind liquidity_reward --amount 5.00

    # Record a settlement (market resolved):
    python phase0_journal.py settle --market "Will candidate X win?" --outcome YES

    # Print running P&L + gate status (default 50% venue-yield haircut):
    python phase0_journal.py status
    python phase0_journal.py status --haircut 0.7    # stress harder

Journal is stored in phase0_journal.json (override with $PHASE0_JOURNAL_FILE).
All monetary amounts are in USDC.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List

JOURNAL_FILE = os.environ.get("PHASE0_JOURNAL_FILE") or os.path.join(
    os.path.dirname(__file__), "phase0_journal.json")

# Phase 0 gate thresholds (PLAN.md §0)
GATE_MIN_TRADES  = 100
GATE_MIN_WEEKS   = 6
GATE_MIN_NET_PNL = 0.0     # net-of-haircut PnL must be strictly positive
GATE_MIN_SHARPE  = 0.0     # daily Sharpe must be strictly positive

DEFAULT_HAIRCUT  = 0.5     # assume half the venue-yield could vanish if the program tightens


# ─────────────────────────── data model ──────────────────────────────────────

def _load() -> dict:
    j = {"fills": [], "settlements": {}, "income": []}
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE) as f:
            content = f.read().strip()
            if content:
                j.update(json.loads(content))
    j.setdefault("fills", [])
    j.setdefault("settlements", {})
    j.setdefault("income", [])
    return j


def _save(j: dict) -> None:
    with open(JOURNAL_FILE, "w") as f:
        json.dump(j, f, indent=2)


# ─────────────────────────── commands ────────────────────────────────────────

def cmd_add(args) -> None:
    j = _load()
    ts = args.timestamp or datetime.now(timezone.utc).isoformat()
    j["fills"].append({
        "ts": ts, "market": args.market, "token": args.token, "side": args.side,
        "price": args.price, "shares": args.shares, "fee": args.fee,
        "gas": args.gas, "note": args.note or "",
    })
    _save(j)
    notional = args.price * args.shares
    print(f"  logged fill: {args.side} {args.shares:.0f}x {args.token} @ {args.price:.3f} "
          f"on '{args.market}' | notional ${notional:.2f} | fee ${args.fee:.4f} gas ${args.gas:.4f}")


def cmd_income(args) -> None:
    j = _load()
    ts = args.timestamp or datetime.now(timezone.utc).isoformat()
    j["income"].append({"ts": ts, "kind": args.kind, "amount": args.amount, "note": args.note or ""})
    _save(j)
    tail = f"  ({args.note})" if args.note else ""
    print(f"  logged income: {args.kind} ${args.amount:+.4f} at {ts[:19]}{tail}")


def cmd_settle(args) -> None:
    j = _load()
    j["settlements"][args.market] = args.outcome
    _save(j)
    print(f"  settled: '{args.market}' -> {args.outcome}")


def cmd_status(args) -> None:
    j = _load()
    if not j["fills"]:
        print("No fills logged yet. Use: python phase0_journal.py add ...")
        return

    s = compute_summary(j, haircut=args.haircut)

    def _tick(ok: bool) -> str:
        return "PASS" if ok else "----"

    print()
    print("=" * 60)
    print("  PHASE 0 JOURNAL STATUS  (wedge: venue-yield market-making)")
    print("=" * 60)
    print(f"  Trades logged   : {s['trade_count']:>8}   (need >= {GATE_MIN_TRADES})")
    print(f"  Span            : {s['span_weeks']:>7.1f} wk (need >= {GATE_MIN_WEEKS} wk)")
    print(f"  Gross trade PnL : ${s['gross_pnl']:>+10.2f}")
    print(f"  Fees + gas      : ${-s['total_fees']:>+10.2f}")
    print(f"  Venue yield     : ${s['venue_yield']:>+10.2f}  "
          f"(rebates ${s['rebate_income']:+.2f} + liq ${s['liq_income']:+.2f})")
    if s["other_income"]:
        print(f"  Other income    : ${s['other_income']:>+10.2f}")
    print(f"  Net PnL         : ${s['net_pnl']:>+10.2f}   (venue-yield as earned)")
    print(f"  Net PnL (-{s['haircut']:.0%} yield): ${s['net_pnl_haircut']:>+10.2f}   <- GATE BASIS (need > $0)")
    print(f"  Daily Sharpe    : {s['sharpe']:>+8.3f}   (need > 0)")
    print()
    print("  Gate criteria:")
    print(f"    [{_tick(s['gate_trades'])}]  >= {GATE_MIN_TRADES} trades")
    print(f"    [{_tick(s['gate_weeks'])}]  >= {GATE_MIN_WEEKS} weeks of data")
    print(f"    [{_tick(s['gate_pnl'])}]  net PnL > $0 (after {s['haircut']:.0%} venue-yield haircut)")
    print(f"    [{_tick(s['gate_sharpe'])}]  daily Sharpe > 0")
    print()
    if s["gate_pass"]:
        print("  >> PHASE 0 GATE: PASS — positive net (haircut) edge documented.")
        print("     Proceed to Phase 1 (automate + hosted bot).")
    else:
        need = []
        if not s["gate_trades"]:
            need.append(f"{GATE_MIN_TRADES - s['trade_count']} more trades")
        if not s["gate_weeks"]:
            need.append(f"{GATE_MIN_WEEKS - s['span_weeks']:.1f} more weeks")
        if not s["gate_pnl"]:
            need.append("positive net-of-haircut PnL")
        if not s["gate_sharpe"]:
            need.append("positive Sharpe")
        print(f"  .. PHASE 0 GATE: NOT YET. Still need: {', '.join(need)}.")
    print("=" * 60)
    print()

    open_lines = [
        (tok, pos, mkt)
        for mkt, toks in s["position"].items() if mkt not in j["settlements"]
        for tok, pos in toks.items() if abs(pos["shares"]) > 1e-9
    ]
    if open_lines:
        print("  Open positions:")
        for tok, pos, mkt in open_lines:
            print(f"    {tok:<3}  {pos['shares']:>+8.0f} sh   cost ${pos['cost']:>+.2f}  mkt: {mkt[:48]}")
        print()


def cmd_list(args) -> None:
    j = _load()
    rows = ([("fill", f) for f in j["fills"]] + [("inc ", e) for e in j["income"]])
    rows.sort(key=lambda r: r[1]["ts"])
    for i, (kind, r) in enumerate(rows[-50:], 1):
        if kind == "fill":
            print(f"  {i:>3}. {r['ts'][:19]}  FILL {r['side']:<4} {r['shares']:>6.0f}x "
                  f"{r['token']:<3} @ {r['price']:.3f}  fee ${r['fee']:.4f}  {r['market'][:36]}")
        else:
            print(f"  {i:>3}. {r['ts'][:19]}  INCOME {r['kind']:<16} ${r['amount']:+.4f}  {r.get('note','')[:30]}")


# ─────────────────────────── accounting (pure) ───────────────────────────────

def compute_summary(j: dict, haircut: float = DEFAULT_HAIRCUT) -> dict:
    """Pure accounting over a journal dict. Returns every figure cmd_status prints.

    Venue yield (rebates + liquidity rewards) is added to PnL as earned, but the
    Phase-0 *gate* is judged on `net_pnl_haircut`, which discounts venue yield by
    `haircut` to stress the assumption that the program tightens.
    """
    fills: List[dict] = j.get("fills", [])
    settlements: Dict[str, str] = j.get("settlements", {})
    income: List[dict] = j.get("income", [])
    haircut = max(0.0, min(1.0, haircut))

    # per-market position accounting
    position: Dict[str, Dict[str, dict]] = {}
    total_fees = 0.0
    trade_count = 0
    for f in fills:
        pos = position.setdefault(f["market"], {}).setdefault(f["token"], {"shares": 0.0, "cost": 0.0})
        sign = 1 if f["side"] == "BUY" else -1
        pos["shares"] += sign * f["shares"]
        pos["cost"]   += sign * f["price"] * f["shares"]
        total_fees    += f["fee"] + f["gas"]
        trade_count   += 1

    # realized PnL on settled markets
    realized = 0.0
    for mkt, outcome in settlements.items():
        for tok, pos in position.get(mkt, {}).items():
            if pos["shares"]:
                realized += pos["shares"] * (1.0 if tok == outcome else 0.0) - pos["cost"]

    # unrealized PnL on open markets, marked at the last fill price
    unrealized = 0.0
    for mkt, toks in position.items():
        if mkt in settlements:
            continue
        for tok, pos in toks.items():
            if not pos["shares"]:
                continue
            last_price = next((f["price"] for f in reversed(fills)
                               if f["market"] == mkt and f["token"] == tok), 0.5)
            unrealized += pos["shares"] * last_price - pos["cost"]

    # venue-yield income (the wedge)
    rebate_income = sum(e["amount"] for e in income if e["kind"] == "rebate")
    liq_income    = sum(e["amount"] for e in income if e["kind"] == "liquidity_reward")
    other_income  = sum(e["amount"] for e in income if e["kind"] not in ("rebate", "liquidity_reward"))
    venue_yield   = rebate_income + liq_income
    total_income  = venue_yield + other_income

    gross_pnl       = realized + unrealized
    net_pnl         = gross_pnl - total_fees + total_income
    net_pnl_haircut = gross_pnl - total_fees + other_income + venue_yield * (1.0 - haircut)

    # time span
    stamps = [_parse_ts(f["ts"]) for f in fills] + [_parse_ts(e["ts"]) for e in income]
    span_days  = max((max(stamps) - min(stamps)).days, 1) if stamps else 1
    span_weeks = span_days / 7.0

    # daily cash-flow series for Sharpe (fills, settlements, income)
    daily: Dict[str, float] = {}
    for f in fills:
        day = _parse_ts(f["ts"]).strftime("%Y-%m-%d")
        sign = 1 if f["side"] == "BUY" else -1
        daily[day] = daily.get(day, 0.0) - (sign * f["price"] * f["shares"]) - f["fee"] - f["gas"]
    last_day = max(stamps).strftime("%Y-%m-%d") if stamps else "1970-01-01"
    for mkt, outcome in settlements.items():
        for tok, pos in position.get(mkt, {}).items():
            if pos["shares"]:
                daily[last_day] = daily.get(last_day, 0.0) + pos["shares"] * (1.0 if tok == outcome else 0.0)
    for e in income:
        day = _parse_ts(e["ts"]).strftime("%Y-%m-%d")
        daily[day] = daily.get(day, 0.0) + e["amount"]
    sharpe = _sharpe(list(daily.values()))

    gate_trades = trade_count >= GATE_MIN_TRADES
    gate_weeks  = span_weeks  >= GATE_MIN_WEEKS
    gate_pnl    = net_pnl_haircut > GATE_MIN_NET_PNL
    gate_sharpe = sharpe          > GATE_MIN_SHARPE

    return {
        "trade_count": trade_count, "span_weeks": span_weeks,
        "gross_pnl": gross_pnl, "total_fees": total_fees,
        "rebate_income": rebate_income, "liq_income": liq_income,
        "other_income": other_income, "venue_yield": venue_yield, "total_income": total_income,
        "net_pnl": net_pnl, "net_pnl_haircut": net_pnl_haircut, "haircut": haircut,
        "sharpe": sharpe, "position": position,
        "gate_trades": gate_trades, "gate_weeks": gate_weeks,
        "gate_pnl": gate_pnl, "gate_sharpe": gate_sharpe,
        "gate_pass": gate_trades and gate_weeks and gate_pnl and gate_sharpe,
    }


# ─────────────────────────── helpers ─────────────────────────────────────────

def _parse_ts(ts: str) -> datetime:
    ts = ts.rstrip("Z")
    if "." in ts:                       # drop fractional seconds / tz tails
        ts = ts.split(".")[0]
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
    return (mu / std) * math.sqrt(252) if std else 0.0   # annualised


# ─────────────────────────── CLI ─────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Phase 0 trade journal — log fills/income, compute net PnL, check gate")
    sub = ap.add_subparsers(dest="cmd", required=True)

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

    p_inc = sub.add_parser("income", help="Log venue-yield income (rebate / liquidity reward)")
    p_inc.add_argument("--kind",      choices=["rebate", "liquidity_reward", "other"], required=True)
    p_inc.add_argument("--amount",    type=float, required=True, help="USDC received")
    p_inc.add_argument("--timestamp", default=None, help="ISO-8601; defaults to now")
    p_inc.add_argument("--note",      default="")

    p_settle = sub.add_parser("settle", help="Record a market resolution")
    p_settle.add_argument("--market",  required=True)
    p_settle.add_argument("--outcome", choices=["YES", "NO"], required=True)

    p_status = sub.add_parser("status", help="Print PnL summary and gate check")
    p_status.add_argument("--haircut", type=float, default=DEFAULT_HAIRCUT,
                          help=f"Fraction of venue-yield assumed to vanish (gate basis). Default {DEFAULT_HAIRCUT}")

    sub.add_parser("list", help="List last 50 fills + income, time-ordered")

    args = ap.parse_args()
    {"add": cmd_add, "income": cmd_income, "settle": cmd_settle,
     "status": cmd_status, "list": cmd_list}[args.cmd](args)


if __name__ == "__main__":
    main()
