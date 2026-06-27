"""Venue fee models (approximate — confirm exact schedules against venue docs).

Polymarket: makers pay 0. Takers pay a category fee that scales with
``min(p, 1 - p)`` (cheapest near the 0/1 extremes, most expensive near 0.50)
and is capped per 100 shares by category. Redeeming the winning share at
resolution is free; gas is near-zero (account abstraction / meta-tx).

Kalshi: fee = ceil(0.07 * contracts * P * (1 - P)) rounded up to the cent.

The exact Polymarket base rate is not publicly fixed per-category here; we model
the *structure* (min(p,1-p) scaling + per-100 cap) which is what matters for a
strategy's edge thresholds. Treat absolute numbers as placeholders.
"""
from __future__ import annotations

import math

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
