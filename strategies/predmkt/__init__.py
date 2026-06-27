"""predmkt — clean-room sample trading strategies for the prediction-market vault platform.

Strategies implement the intent-based execution boundary from docs/ARCHITECTURE.md:
they read market state and emit declarative Intents; they never hold keys or funds.
"""
from .base import Context, Fill, Strategy
from .types import (
    BinaryMarket,
    CancelAll,
    Convert,
    CrossVenuePair,
    Event,
    Intent,
    LimitOrder,
    Merge,
    OrderBook,
    Portfolio,
    Position,
    Price,
    Side,
    Size,
    Split,
    TICK,
    TIF,
    Token,
    Venue,
)
from .arbitrage import ArbitrageStrategy, ArbParams
from .market_maker import MarketMakerStrategy, MMParams
from .kelly_edge import KellyEdgeStrategy, KellyParams

__all__ = [
    "Context", "Fill", "Strategy",
    "BinaryMarket", "CancelAll", "Convert", "CrossVenuePair", "Event", "Intent",
    "LimitOrder", "Merge", "OrderBook", "Portfolio", "Position", "Price", "Side",
    "Size", "Split", "TICK", "TIF", "Token", "Venue",
    "ArbitrageStrategy", "ArbParams",
    "MarketMakerStrategy", "MMParams",
    "KellyEdgeStrategy", "KellyParams",
]
