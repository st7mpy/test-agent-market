"""Oracle / resolution-risk model (differentiator C) — pricing the #1 systemic risk.

A prediction-market payout is only as good as the oracle that resolves it. On
Polymarket that's UMA, and it has failed in the wild: a holder of ~25% of UMA
voting power falsely settled a ~$7M contract. No competitor prices this risk, and
nobody insures depositors against it (DIFFERENTIATION.md C).

This model assigns each market an **oracle-risk score in [0, 1]** that the RiskGate
uses to cap or refuse *new* exposure to dispute-prone / thin-oracle / ambiguous
markets. It is deliberately transparent and configurable:

  score = clamp( category_base  +  Σ flag_weights[flag]  )         (overrides win)

Objective, machine-checkable resolutions (sports scores, crypto prices) score low;
subjective or geopolitical ones score high. On-chain or order-book data cannot tell
you a market's *criteria* are ambiguous — an off-chain monitor flags that — so the
model turns monitor flags into a bounded, auditable number the hot path can act on.

The insurance-fund side of C (a depositor backstop funded by protocol fee + slashing
proceeds) is the heavier, vault-side follow-on; this module is the pre-trade control.
Dependency-free, matching the rest of `predmkt`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .types import BinaryMarket


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# Per-category base risk. Rationale: how mechanically the outcome resolves.
DEFAULT_CATEGORY_BASE: Dict[str, float] = {
    "crypto":   0.10,   # price feeds — objective
    "sports":   0.10,   # final scores — objective
    "finance":  0.20,   # data prints, occasional revisions
    "econ":     0.20,
    "politics": 0.35,   # election calls can be slow / contested
    "culture":  0.45,   # often subjective
    "world":    0.55,   # geopolitical, ambiguous wording — most UMA-dispute-prone
}

# Additive risk from monitor-set flags (an off-chain process sets these per market).
DEFAULT_FLAG_WEIGHTS: Dict[str, float] = {
    "active_dispute":        0.60,   # a live UMA dispute right now
    "subjective_resolution": 0.30,   # "will X be considered a success" — judgment call
    "ambiguous_criteria":    0.30,   # resolution source/wording unclear
    "thin_oracle":           0.25,   # few/concentrated resolvers
    "low_liquidity":         0.15,   # thin market, easier to manipulate into a dispute
}


@dataclass
class OracleRiskParams:
    category_base: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CATEGORY_BASE))
    default_base: float = 0.30
    flag_weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_FLAG_WEIGHTS))


class OracleRiskModel:
    """Maps a market to an oracle-risk score in [0, 1]. Higher = more dispute/failure risk."""

    def __init__(self, params: Optional[OracleRiskParams] = None,
                 flags: Optional[Dict[str, List[str]]] = None,
                 overrides: Optional[Dict[str, float]] = None) -> None:
        self.p = params or OracleRiskParams()
        self.flags = flags or {}          # market_id -> [flag, ...]
        self.overrides = overrides or {}  # market_id -> explicit score (takes precedence)

    def score(self, m: BinaryMarket) -> float:
        if m.market_id in self.overrides:
            return _clamp01(self.overrides[m.market_id])
        base = self.p.category_base.get(m.category, self.p.default_base)
        bump = sum(self.p.flag_weights.get(f, 0.0) for f in self.flags.get(m.market_id, []))
        return _clamp01(base + bump)

    def reasons(self, m: BinaryMarket) -> List[str]:
        """Human-readable contributors, for telemetry / depositor disclosure."""
        if m.market_id in self.overrides:
            return [f"override={self.overrides[m.market_id]:.2f}"]
        out = [f"category:{m.category}={self.p.category_base.get(m.category, self.p.default_base):.2f}"]
        out += [f"{f}+{self.p.flag_weights.get(f, 0.0):.2f}" for f in self.flags.get(m.market_id, [])]
        return out
