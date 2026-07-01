"""Venue fee models (approximate — confirm exact schedules against venue docs).

Polymarket: makers pay 0. Takers pay a category fee that scales with
``min(p, 1 - p)`` (cheapest near the 0/1 extremes, most expensive near 0.50)
and is capped per 100 shares by category. Redeeming the winning share at
resolution is free; gas is near-zero (account abstraction / meta-tx).

Kalshi: fee = ceil(0.07 * contracts * P * (1 - P)) rounded up to the cent.

ForecastEx (IBKR ForecastTrader): flat $0.01 per contract, embedded in matching —
YES and NO bids always total $1.01. Posting passive liquidity is free, and 100% of
interest on deposited collateral is passed back as an Incentive Coupon (~3-4% APY
as of mid-2026), which feeds the venue-yield accounting (differentiator B).

The exact Polymarket base rate is not publicly fixed per-category here; we model
the *structure* (min(p,1-p) scaling + per-100 cap) which is what matters for a
strategy's edge thresholds. Treat absolute numbers as placeholders.
"""
from __future__ import annotations

import math

from .types import Venue

# Max taker fee per 100 shares, by category (USD). Source: Polymarket fee docs.
_CATEGORY_CAP_PER_100 = {
    "sports": 0.75,
    "politics": 1.00,
    "finance": 1.00,
    "econ": 1.25,
    "culture": 1.25,
    "crypto": 1.80,
    "world": 0.00,        # some world-event markets are fee-free
}
_DEFAULT_CAP_PER_100 = 1.00
_BASE_TAKER_RATE = 0.07   # per-share coefficient on min(p, 1-p); approximate


def polymarket_taker_fee_per_share(price: float, category: str) -> float:
    """Approximate per-share taker fee in USDC."""
    p = max(0.0, min(1.0, price))
    raw = _BASE_TAKER_RATE * min(p, 1.0 - p)
    cap_per_share = _CATEGORY_CAP_PER_100.get(category, _DEFAULT_CAP_PER_100) / 100.0
    return min(raw, cap_per_share)


def polymarket_taker_fee(price: float, shares: float, category: str) -> float:
    return polymarket_taker_fee_per_share(price, category) * shares


def kalshi_fee(price: float, contracts: float) -> float:
    """Kalshi trading fee, rounded up to the next cent."""
    p = max(0.0, min(1.0, price))
    return math.ceil(0.07 * contracts * p * (1.0 - p) * 100.0) / 100.0


def kalshi_fee_per_share(price: float) -> float:
    """Per-contract Kalshi fee rate (un-rounded), for edge thresholds. Unlike
    Polymarket's min(p,1-p) schedule this peaks at p=0.50 and has no per-100 cap,
    so the two venues' fees differ materially — which is why cross-venue edge must
    be computed venue-by-venue."""
    p = max(0.0, min(1.0, price))
    return 0.07 * p * (1.0 - p)


FORECASTEX_FEE_PER_CONTRACT = 0.01


def forecastex_fee_per_share(price: float = 0.0) -> float:
    """Flat $0.01/contract regardless of price. Unlike Polymarket (cheap at the
    extremes) and Kalshi (peaks at p=0.50), this is price-flat — so ForecastEx is
    relatively expensive for near-certain favorites (theta trades) and relatively
    cheap at mid-range prices."""
    return FORECASTEX_FEE_PER_CONTRACT


def taker_fee_per_share(venue: Venue, price: float, category: str) -> float:
    """Venue-aware per-share taker fee — dispatches to the correct venue model so a
    cross-venue arb leg is charged its own venue's fee, not the other's (ADR-016)."""
    if venue == Venue.KALSHI:
        return kalshi_fee_per_share(price)
    if venue == Venue.FORECASTEX:
        return forecastex_fee_per_share(price)
    return polymarket_taker_fee_per_share(price, category)
