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
    MarketRelation,
    Merge,
    OrderBook,
    Portfolio,
    Position,
    Price,
    RelationKind,
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
from .relation_arb import RelationArbStrategy, RelationArbParams
from .longshot_bias import LongshotBiasStrategy, LongshotParams, debias
from .theta_convergence import ThetaConvergenceStrategy, ThetaParams
from .delta_neutral import DeltaNeutralYieldStrategy, DeltaNeutralParams
from .flow_signal import (
    FlowTrade, SmartMoneyParams, SmartMoneyProvider, WalletScore,
    score_wallets, signed_yes_exposure,
)
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
    kalshi_fee, kalshi_fee_per_share, forecastex_fee_per_share, taker_fee_per_share,
)
from .attestation import (
    Attestation, AttestationService, commit_positions,
    verify_attestation, verify_position_reveal,
)

__all__ = [
    "Context", "Fill", "Strategy",
    "BinaryMarket", "CancelAll", "Convert", "CrossVenuePair", "Event", "Intent",
    "LimitOrder", "MarketRelation", "Merge", "OrderBook", "Portfolio", "Position",
    "Price", "RelationKind", "Side", "Size", "Split", "TICK", "TIF", "Token", "Venue",
    "ArbitrageStrategy", "ArbParams",
    "MarketMakerStrategy", "MMParams",
    "KellyEdgeStrategy", "KellyParams",
    "RelationArbStrategy", "RelationArbParams",
    "LongshotBiasStrategy", "LongshotParams", "debias",
    "ThetaConvergenceStrategy", "ThetaParams",
    "DeltaNeutralYieldStrategy", "DeltaNeutralParams",
    "FlowTrade", "SmartMoneyParams", "SmartMoneyProvider", "WalletScore",
    "score_wallets", "signed_yes_exposure",
    "Signal", "SignalProvider", "MarketImpliedProvider", "ExternalPriorProvider",
    "SignalReport", "as_fair_value_fn", "brier_score", "brier_skill_score",
    "calibration_curve", "expected_calibration_error", "evaluate_provider",
    "OracleRiskModel", "OracleRiskParams", "RiskGate", "RiskLimits",
    "VenueAdapter", "PolymarketAdapter", "KalshiAdapter", "ReplayAdapter", "CrossVenueFeed",
    "polymarket_taker_fee", "polymarket_taker_fee_per_share",
    "kalshi_fee", "kalshi_fee_per_share", "forecastex_fee_per_share",
    "taker_fee_per_share",
    "Attestation", "AttestationService", "commit_positions",
    "verify_attestation", "verify_position_reveal",
]
