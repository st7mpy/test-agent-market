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
from .signals import (
    Signal,
    SignalProvider,
    MarketImpliedProvider,
    ExternalPriorProvider,
    SignalReport,
    as_fair_value_fn,
    brier_score,
    brier_skill_score,
    calibration_curve,
    expected_calibration_error,
    evaluate_provider,
)
from .oracle_risk import OracleRiskModel, OracleRiskParams
from .execution import RiskGate, RiskLimits
from .venue import (
    VenueAdapter, PolymarketAdapter, KalshiAdapter, ReplayAdapter, CrossVenueFeed,
)
from .fees import (
    polymarket_taker_fee, polymarket_taker_fee_per_share,
    kalshi_fee, kalshi_fee_per_share, taker_fee_per_share,
)

__all__ = [
    "Context", "Fill", "Strategy",
    "BinaryMarket", "CancelAll", "Convert", "CrossVenuePair", "Event", "Intent",
    "LimitOrder", "Merge", "OrderBook", "Portfolio", "Position", "Price", "Side",
    "Size", "Split", "TICK", "TIF", "Token", "Venue",
    "ArbitrageStrategy", "ArbParams",
    "MarketMakerStrategy", "MMParams",
    "KellyEdgeStrategy", "KellyParams",
    "Signal", "SignalProvider", "MarketImpliedProvider", "ExternalPriorProvider",
    "SignalReport", "as_fair_value_fn", "brier_score", "brier_skill_score",
    "calibration_curve", "expected_calibration_error", "evaluate_provider",
    "OracleRiskModel", "OracleRiskParams", "RiskGate", "RiskLimits",
    "VenueAdapter", "PolymarketAdapter", "KalshiAdapter", "ReplayAdapter", "CrossVenueFeed",
    "polymarket_taker_fee", "polymarket_taker_fee_per_share",
    "kalshi_fee", "kalshi_fee_per_share", "taker_fee_per_share",
]
