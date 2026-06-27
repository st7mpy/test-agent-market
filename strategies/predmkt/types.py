"""Core domain types for prediction-market sample strategies.

These mirror the platform's intent-based execution boundary (see
docs/ARCHITECTURE.md, ADR-002): a strategy never touches keys or funds. It only
reads market state and emits *intents* (declarative desired actions) that the
platform's Risk Gate validates and the Execution/OMS signs and routes.

Prices are in USDC, expressed as a probability in [0, 1]; a YES share pays $1 if
the outcome resolves YES and $0 otherwise (NO is the complement).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

Price = float  # 0..1
Size = float   # number of shares (or USDC for split/merge)

TICK = 0.001   # Polymarket minimum price increment (1/10 cent)


class Venue(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class Token(str, Enum):
    YES = "YES"
    NO = "NO"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TIF(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


# --------------------------------------------------------------------------- #
# Market state
# --------------------------------------------------------------------------- #
@dataclass
class OrderBook:
    """One side-pair of a CLOB. `bids` are descending, `asks` ascending."""
    bids: List[Tuple[Price, Size]] = field(default_factory=list)
    asks: List[Tuple[Price, Size]] = field(default_factory=list)

    def best_bid(self) -> Optional[Price]:
        return self.bids[0][0] if self.bids else None

    def best_ask(self) -> Optional[Price]:
        return self.asks[0][0] if self.asks else None

    def mid(self) -> Optional[Price]:
        b, a = self.best_bid(), self.best_ask()
        if b is None or a is None:
            return None
        return (a + b) / 2.0

    def spread(self) -> Optional[Price]:
        b, a = self.best_bid(), self.best_ask()
        return None if b is None or a is None else a - b

    def microprice(self) -> Optional[Price]:
        """Size-weighted mid: leans toward the side with more depth."""
        if not self.bids or not self.asks:
            return self.mid()
        bp, bs = self.bids[0]
        ap, as_ = self.asks[0]
        denom = bs + as_
        if denom <= 0:
            return self.mid()
        return (ap * bs + bp * as_) / denom

    def fillable_size(self, side: Side, limit: Price) -> Size:
        """Shares executable immediately at `limit` or better by crossing the book."""
        total = 0.0
        if side == Side.BUY:
            for p, s in self.asks:
                if p <= limit + 1e-12:
                    total += s
                else:
                    break
        else:
            for p, s in self.bids:
                if p >= limit - 1e-12:
                    total += s
                else:
                    break
        return total


@dataclass
class BinaryMarket:
    """A single YES/NO market with its two order books."""
    market_id: str
    category: str                       # "sports" | "politics" | "crypto" | ...
    yes_book: OrderBook
    no_book: OrderBook
    time_to_resolution: float           # in model periods; must match the per-tick vol unit
    venue: Venue = Venue.POLYMARKET

    def book(self, token: Token) -> OrderBook:
        return self.yes_book if token == Token.YES else self.no_book


@dataclass
class Event:
    """A mutually-exclusive multi-outcome event (NegRisk): exactly one resolves YES."""
    event_id: str
    markets: List[BinaryMarket]


@dataclass
class CrossVenuePair:
    """The same real-world event listed on two venues, for cross-venue arbitrage."""
    market_a: BinaryMarket
    market_b: BinaryMarket
    resolution_rules_match: bool = True  # if False, this is basis risk, NOT arbitrage


# --------------------------------------------------------------------------- #
# Portfolio
# --------------------------------------------------------------------------- #
@dataclass
class Position:
    yes: Size = 0.0
    no: Size = 0.0

    def net_yes(self) -> Size:
        """Signed YES inventory (a NO share is economically short-YES)."""
        return self.yes - self.no


@dataclass
class Portfolio:
    cash: float = 0.0                                   # USDC
    positions: Dict[str, Position] = field(default_factory=dict)
    realized_pnl_today: float = 0.0

    def position(self, market_id: str) -> Position:
        return self.positions.setdefault(market_id, Position())


# --------------------------------------------------------------------------- #
# Intents — the only thing a strategy may emit (ARCHITECTURE.md, ADR-002)
# --------------------------------------------------------------------------- #
@dataclass
class Intent:
    """Base class. Declarative: the strategy cannot assume execution."""
    note: str = ""


@dataclass
class LimitOrder(Intent):
    market_id: str = ""
    token: Token = Token.YES
    side: Side = Side.BUY
    price: Price = 0.0
    size: Size = 0.0
    tif: TIF = TIF.GTC


@dataclass
class Split(Intent):
    """CTF split: $X USDC -> X YES + X NO (a 'complete set' is always worth $1)."""
    market_id: str = ""
    usdc: float = 0.0


@dataclass
class Merge(Intent):
    """CTF merge: X YES + X NO -> $X USDC."""
    market_id: str = ""
    shares: Size = 0.0


@dataclass
class Convert(Intent):
    """NegRisk convert: 1 NO in one sub-market -> 1 YES in every other sub-market."""
    event_id: str = ""
    from_market_id: str = ""
    shares: Size = 0.0


@dataclass
class CancelAll(Intent):
    market_id: str = ""
