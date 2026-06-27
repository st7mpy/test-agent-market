"""Venue connectivity layer (ARCHITECTURE.md C1 / ADR-008).

A `VenueAdapter` normalises a venue into the platform's `BinaryMarket` model. Two
implementations behind one interface:

  * `PolymarketAdapter` — pulls a real market's live L2 books from the public CLOB
    API (no key needed). This is the path that runs in a networked environment.
  * `ReplayAdapter` — feeds a historical/synthetic price series offline, so paper
    trading is runnable and testable without network access.

The adapter is stateful: it is bound to a single market and `fetch_market()`
returns the current snapshot each time it is called (or None when a replay is
exhausted). The same strategy + execution code runs against either source.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from .sim import binary_market
from .types import BinaryMarket, OrderBook, Venue


class VenueAdapter(ABC):
    market_id: str
    category: str

    @abstractmethod
    def fetch_market(self) -> Optional[BinaryMarket]:
        """Current market snapshot, or None when a finite source is exhausted."""

    @abstractmethod
    def resolution(self) -> Optional[str]:
        """'YES' / 'NO' once resolved, else None."""


# --------------------------------------------------------------------------- #
class PolymarketAdapter(VenueAdapter):
    """Live adapter over Polymarket's public CLOB + Gamma APIs.

    Untested in this session (egress policy blocks polymarket.com); correct and
    ready to run where outbound HTTPS is available.
    """

    def __init__(self, query: str, *, poll_interval_s: float = 2.0,
                 category: str = "politics") -> None:
        from . import data  # local import so offline use never needs network code paths
        self._data = data
        info = data.discover_token(query, closed=False)
        if not info:
            raise RuntimeError(f"no open market matched {query!r}")
        self.market_id = info["question"]
        self.category = category
        self._yes = info["yes_token_id"]
        self._no = info["no_token_id"]
        self._poll = poll_interval_s
        self._end_ts: Optional[float] = info.get("end_ts")

    def fetch_market(self) -> Optional[BinaryMarket]:
        yes_book = self._data.fetch_polymarket_book(self._yes)
        no_book = self._data.fetch_polymarket_book(self._no)
        # time-to-resolution expressed in poll periods so it matches per-tick vol
        if self._end_ts:
            ttr = max(1.0, (self._end_ts - time.time()) / self._poll)
        else:
            ttr = 1000.0
        return BinaryMarket(self.market_id, self.category, yes_book, no_book,
                            ttr, Venue.POLYMARKET)

    def resolution(self) -> Optional[str]:
        info = self._data.discover_token(self.market_id, closed=True)
        return info.get("outcome") if info else None


# --------------------------------------------------------------------------- #
class ReplayAdapter(VenueAdapter):
    """Offline adapter that replays a price series as synthesised books."""

    def __init__(self, series: List[Tuple[int, float]], *, market_id: str = "replay",
                 category: str = "politics", outcome: str = "YES",
                 spread: float = 0.01, depth: float = 1000.0) -> None:
        self.market_id = market_id
        self.category = category
        self._series = series
        self._outcome = outcome
        self._spread = spread
        self._depth = depth
        self._i = 0

    def fetch_market(self) -> Optional[BinaryMarket]:
        if self._i >= len(self._series):
            return None
        _, p = self._series[self._i]
        ttr = float(len(self._series) - self._i)
        self._i += 1
        return binary_market(self.market_id, yes_mid=p, spread=self._spread,
                             size=self._depth, category=self.category,
                             time_to_resolution=ttr)

    def resolution(self) -> Optional[str]:
        return self._outcome if self._i >= len(self._series) else None
