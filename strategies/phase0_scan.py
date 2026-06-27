#!/usr/bin/env python3
"""Phase 0 edge screener — scan live Polymarket markets for strategy signals.

Run this in a networked environment (no egress restrictions) to find markets
where the sample strategies see edge above your minimum threshold.

Usage
-----
    cd strategies

    # Scan top-volume open markets; print where any strategy sees edge > 2%
    python phase0_scan.py

    # Filter by keyword; lower edge threshold
    python phase0_scan.py --query "election" --min-edge 0.01

    # Show order books alongside signals
    python phase0_scan.py --verbose

    # Fetch only closed markets (for backtest sanity check)
    python phase0_scan.py --closed --limit 20

Output
------
One row per (market, strategy) pair where computed edge exceeds --min-edge.
Columns: edge (net-of-fees), strategy, YES ask, NO ask, spread, market question.
Sort: edge descending.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Tuple

from predmkt.data import CLOB_BOOK, GAMMA, _get_json
from predmkt.fees import polymarket_taker_fee_per_share
from predmkt.types import BinaryMarket, OrderBook, Token, Venue
from predmkt.kelly_edge import KellyMeanReversion
from predmkt.market_maker import AvellanedaStoikov
from predmkt.arbitrage import ArbitrageStrategy

import json, urllib.parse


# ─────────────────────────── market fetching ─────────────────────────────────

def _fetch_book(token_id: str) -> OrderBook:
    data = _get_json(f"{CLOB_BOOK}?token_id={urllib.parse.quote(str(token_id))}")
    bids = sorted(((float(l["price"]), float(l["size"])) for l in data.get("bids", [])),
                  key=lambda x: -x[0])
    asks = sorted(((float(l["price"]), float(l["size"])) for l in data.get("asks", [])),
                  key=lambda x: x[0])
    return OrderBook(bids=bids, asks=asks)


def _fetch_markets(query: Optional[str], closed: bool, limit: int) -> List[dict]:
    params: dict = {"limit": str(limit), "order": "volumeNum", "ascending": "false"}
    if closed:
        params["closed"] = "true"
    else:
        params["active"] = "true"
    url = f"{GAMMA}?{urllib.parse.urlencode(params)}"
    markets = _get_json(url)
    if query:
        q = query.lower()
        markets = [m for m in markets if q in m.get("question", "").lower()]
    return markets


def _market_from_api(m: dict) -> Optional[BinaryMarket]:
    """Build a BinaryMarket from Gamma metadata + live CLOB books."""
    token_ids = m.get("clobTokenIds")
    if isinstance(token_ids, str):
        try:
            token_ids = json.loads(token_ids)
        except Exception:
            return None
    if not token_ids or len(token_ids) < 2:
        return None
    try:
        yes_book = _fetch_book(token_ids[0])
        no_book  = _fetch_book(token_ids[1])
    except Exception:
        return None
    category = m.get("category", "world").lower() or "world"
    return BinaryMarket(
        market_id=m.get("conditionId") or m.get("id") or token_ids[0],
        category=category,
        yes_book=yes_book,
        no_book=no_book,
        time_to_resolution=1.0,  # placeholder; strategies use this for vol scaling
        venue=Venue.POLYMARKET,
    )


# ─────────────────────────── edge computation ────────────────────────────────

def _kelly_edge(mkt: BinaryMarket) -> Optional[float]:
    """Net-of-fee edge for Kelly strategy (forecast vs best ask)."""
    strat = KellyMeanReversion(market_id=mkt.market_id, bankroll=10_000.0)
    intents = strat.on_tick(mkt)  # type: ignore[arg-type]
    if not intents:
        return None
    # Pull the 'edge' out of the note field
    for intent in intents:
        note = getattr(intent, "note", "")
        for part in note.split():
            if part.startswith("edge="):
                try:
                    raw_edge = float(part.split("=")[1])
                    # deduct taker fee at best ask
                    best_ask = mkt.yes_book.best_ask()
                    if best_ask is None:
                        return None
                    fee = polymarket_taker_fee_per_share(best_ask, mkt.category)
                    return raw_edge - fee
                except (ValueError, IndexError):
                    pass
    return None


def _mm_spread_edge(mkt: BinaryMarket) -> Optional[float]:
    """MM edge proxy: half-spread minus taker fee at mid."""
    mid = mkt.yes_book.mid()
    spread = mkt.yes_book.spread()
    if mid is None or spread is None or spread <= 0:
        return None
    half = spread / 2.0
    fee = polymarket_taker_fee_per_share(mid, mkt.category)
    return half - fee


def _arb_edge(mkt: BinaryMarket) -> Optional[float]:
    """Intra-market arb edge (YES ask + NO ask < 1 net of fees)."""
    ya = mkt.yes_book.best_ask()
    na = mkt.no_book.best_ask()
    if ya is None or na is None:
        return None
    total = ya + na
    if total >= 1.0:
        return None
    fee_yes = polymarket_taker_fee_per_share(ya, mkt.category)
    fee_no  = polymarket_taker_fee_per_share(na, mkt.category)
    return (1.0 - total) - fee_yes - fee_no


# ─────────────────────────── main ────────────────────────────────────────────

Signal = Tuple[float, str, str, str]  # (edge, strategy, mkt_id, question)


def scan(query: Optional[str], closed: bool, limit: int,
         min_edge: float, verbose: bool) -> List[Signal]:
    print(f"Fetching up to {limit} {'closed' if closed else 'open'} markets"
          + (f" matching '{query}'" if query else "") + " ...")

    try:
        raw = _fetch_markets(query, closed, limit)
    except Exception as e:
        print(f"ERROR fetching market list: {e}")
        print("Are you in a networked environment? Polymarket API requires network access.")
        sys.exit(1)

    print(f"  {len(raw)} markets found; fetching live order books ...")
    signals: List[Signal] = []

    for i, m in enumerate(raw):
        question = m.get("question", "?")[:64]
        sys.stdout.write(f"\r  [{i+1}/{len(raw)}] {question:<64}")
        sys.stdout.flush()

        mkt = _market_from_api(m)
        if mkt is None:
            continue

        if verbose:
            ya = mkt.yes_book.best_ask()
            nb = mkt.yes_book.best_bid()
            print(f"\n    book: bid={nb} ask={ya} spread={mkt.yes_book.spread()}")

        for name, fn in [("kelly", _kelly_edge), ("mm", _mm_spread_edge), ("arb", _arb_edge)]:
            try:
                edge = fn(mkt)
            except Exception:
                edge = None
            if edge is not None and edge >= min_edge:
                signals.append((edge, name, mkt.market_id, question))

    print()
    return sorted(signals, key=lambda x: -x[0])


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 0 live edge screener")
    ap.add_argument("--query",    default=None, help="Keyword filter on market question")
    ap.add_argument("--closed",   action="store_true", help="Scan closed (resolved) markets")
    ap.add_argument("--limit",    type=int, default=50, help="Max markets to fetch (default 50)")
    ap.add_argument("--min-edge", type=float, default=0.02,
                    help="Min net-of-fee edge to display (default 0.02 = 2 cents/share)")
    ap.add_argument("--verbose",  action="store_true", help="Show order books")
    args = ap.parse_args()

    signals = scan(args.query, args.closed, args.limit, args.min_edge, args.verbose)

    if not signals:
        print(f"No signals above min-edge {args.min_edge:.3f}. Try --min-edge 0.01 or broader --query.")
        return

    print(f"\n{'EDGE':>7}  {'STRATEGY':<8}  {'QUESTION'}")
    print("─" * 80)
    for edge, strategy, mkt_id, question in signals:
        print(f"  {edge:>+.4f}  {strategy:<8}  {question}")
    print(f"\n{len(signals)} signal(s) above {args.min_edge:.3f}.")
    print("\nNext step: trade these manually on Polymarket and log fills with:")
    print("  python phase0_journal.py add --market '...' --token YES --side BUY "
          "--price 0.42 --shares 100 --fee 0.35 --gas 0.01")


if __name__ == "__main__":
    main()
