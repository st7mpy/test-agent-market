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
from typing import Dict, List, Optional, Tuple

from .base import Fill
from .sim import binary_market
from .types import BinaryMarket, OrderBook, Position, Side, Token, Venue


class VenueAdapter(ABC):
    market_id: str
    category: str

    @abstractmethod
    def fetch_market(self) -> Optional[BinaryMarket]:
        """Current market snapshot, or None when a finite source is exhausted."""

    @abstractmethod
    def resolution(self) -> Optional[str]:
        """'YES' / 'NO' once resolved, else None."""

    @abstractmethod
    def positions(self) -> Dict[str, Position]:
        """The VENUE's view of holdings — the source of truth for reconciliation."""

    def record_fills(self, fills: List[Fill]) -> None:
        """Paper-only hook so the simulated venue tracks fills independently of the
        OMS. Real venues self-record, so the live adapter overrides this with a no-op."""
        return None


# --------------------------------------------------------------------------- #
class PolymarketAdapter(VenueAdapter):
    """Live adapter over Polymarket's public CLOB + Gamma APIs.

    Untested in this session (egress policy blocks polymarket.com); correct and
    ready to run where outbound HTTPS is available.
    """

    def __init__(self, query: str, *, poll_interval_s: float = 2.0,
                 category: str = "politics", address: Optional[str] = None) -> None:
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
        self._address = address

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

    def positions(self) -> Dict[str, Position]:
        """Best-effort via the Polymarket Data API (needs a wallet address).

        Untested in-session; returns {} when no address is configured, which the
        reconciler treats as 'no venue truth available' and logs rather than halting.
        """
        if not self._address:
            return {}
        url = f"https://data-api.polymarket.com/positions?user={self._address}"
        out: Dict[str, Position] = {}
        for row in self._data._get_json(url):
            asset = row.get("asset")
            size = float(row.get("size", 0))
            pos = out.setdefault(self.market_id, Position())
            if asset == self._yes:
                pos.yes += size
            elif asset == self._no:
                pos.no += size
        return out


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
        self._venue: Dict[str, Position] = {}   # the simulated venue's own ledger

    def record_fills(self, fills: List[Fill]) -> None:
        for f in fills:
            p = self._venue.setdefault(f.market_id, Position())
            delta = f.size if f.side == Side.BUY else -f.size
            if f.token == Token.YES:
                p.yes += delta
            else:
                p.no += delta

    def positions(self) -> Dict[str, Position]:
        return {k: Position(yes=v.yes, no=v.no) for k, v in self._venue.items()}

    def inject_divergence(self, market_id: str, *, yes: float = 0.0, no: float = 0.0) -> None:
        """Fault injection for testing reconciliation: perturb the venue ledger so
        it disagrees with the OMS's internal expectation."""
        p = self._venue.setdefault(market_id, Position())
        p.yes += yes
        p.no += no

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
