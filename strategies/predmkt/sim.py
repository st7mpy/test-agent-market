"""Minimal deterministic simulator + synthetic-data helpers.

This is a *demonstration harness*, not a backtester: it builds order books, feeds
ticks to a strategy, and surfaces the intents it emits (and, for arbitrage, the
locked profit). The platform's real backtester (docs/ARCHITECTURE.md, ADR-010)
replays historical venue data deterministically; this stands in for it so the
samples are runnable offline with no dependencies.
"""
from __future__ import annotations

import random
from typing import List, Tuple

from .types import BinaryMarket, OrderBook, Venue


def book(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> OrderBook:
    bids = sorted(bids, key=lambda x: -x[0])
    asks = sorted(asks, key=lambda x: x[0])
    return OrderBook(bids=bids, asks=asks)


def flat_book(mid: float, spread: float, size: float) -> OrderBook:
    """A simple two-sided book centered on `mid`."""
    half = spread / 2.0
    return book([(round(mid - half, 4), size)], [(round(mid + half, 4), size)])


def binary_market(market_id: str, yes_mid: float, spread: float = 0.01,
                  size: float = 1000.0, category: str = "politics",
                  seconds_to_resolution: float = 86400.0,
                  venue: Venue = Venue.POLYMARKET) -> BinaryMarket:
    """A binary market whose NO book is the complement of the YES book."""
    yes = flat_book(yes_mid, spread, size)
    no = flat_book(1.0 - yes_mid, spread, size)
    return BinaryMarket(market_id, category, yes, no, seconds_to_resolution, venue)


def random_walk_market(market_id: str, start: float, sigma: float, steps: int,
                       seed: int = 7, **kw) -> List[BinaryMarket]:
    """A sequence of market snapshots whose YES mid follows a clamped random walk."""
    rng = random.Random(seed)
    px = start
    out = []
    for _ in range(steps):
        px = min(0.97, max(0.03, px + rng.gauss(0, sigma)))
        out.append(binary_market(market_id, round(px, 4), **kw))
    return out
