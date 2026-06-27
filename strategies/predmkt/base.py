"""Strategy base class and the per-tick context.

A strategy is a pure decision function: given a `Context` (market state +
portfolio), return a list of `Intent`s. It maintains its own internal state
(inventory estimates, price history) across ticks and is notified of fills via
`on_fill`. It never holds keys, never calls a venue directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .types import (
    BinaryMarket,
    CrossVenuePair,
    Event,
    Intent,
    Portfolio,
    Side,
    Token,
)


@dataclass
class Fill:
    market_id: str
    token: Token
    side: Side
    price: float
    size: float


@dataclass
class Context:
    now: float = 0.0
    markets: Dict[str, BinaryMarket] = field(default_factory=dict)
    events: Dict[str, Event] = field(default_factory=dict)
    cross_pairs: List[CrossVenuePair] = field(default_factory=list)
    portfolio: Portfolio = field(default_factory=Portfolio)


class Strategy:
    """Base class. Subclasses implement `on_tick`."""

    name: str = "strategy"

    def on_tick(self, ctx: Context) -> List[Intent]:
        raise NotImplementedError

    def on_fill(self, fill: Fill) -> None:  # pragma: no cover - default no-op
        """Optional hook so stateful strategies can track inventory."""
        return None


def depth_capped_size(book, side: Side, limit: float, fraction: float, hard_cap: float) -> float:
    """Cap an order to a fraction of immediately-fillable depth and a hard ceiling."""
    fillable = book.fillable_size(side, limit)
    return max(0.0, min(fillable * fraction, hard_cap))
