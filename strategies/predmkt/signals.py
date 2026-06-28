"""Signal layer (differentiator F) — calibrated fair-value probabilities, off the hot path.

A *signal* is an estimate of P(YES) for a market, produced by a `SignalProvider`.
In production the high-value provider is an **LLM research agent** (news / base-rates /
sentiment → a calibrated probability); here we ship the **seam** plus deterministic
reference providers, so the system runs and is testable without any model call.

Two rules make this safe (ADR-012):
  1. The provider runs **off the execution hot path** — it only *proposes* a probability.
     Every order it ultimately motivates still passes the Risk Gate (ADR-002); a bad
     signal cannot move funds on its own.
  2. A signal is **not trusted until validated** (ADR-013): it must show positive Brier
     *skill* over the market's own implied probability AND be well-calibrated, measured on
     resolved real-money markets. A miscalibrated or no-skill signal is worse than the
     market price, so the harness below is the gate before a provider is allowed to size.

Plug a provider into the Kelly strategy with `as_fair_value_fn(provider)`.
Dependency-free (stdlib only), matching the rest of `predmkt`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .types import BinaryMarket


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ─────────────────────────── the signal + provider seam ──────────────────────

@dataclass
class Signal:
    """A provider's view of a market. The hot path consumes only `p`."""
    p: float                      # P(YES) in [0, 1]
    confidence: float = 1.0       # [0, 1]; used to shrink toward market + gate sizing
    rationale: str = ""           # human-readable; useful for audit/disclosure


class SignalProvider:
    """Base class. A production LLM agent subclasses this and implements `fair_value`."""
    name: str = "signal"

    def fair_value(self, m: BinaryMarket) -> Optional[Signal]:
        raise NotImplementedError


class MarketImpliedProvider(SignalProvider):
    """Null model: the market's own micro-price. Zero skill by construction — it *is*
    the market — so it's the reference every other provider must beat (ADR-013)."""
    name = "market_implied"

    def fair_value(self, m: BinaryMarket) -> Optional[Signal]:
        mp = m.yes_book.microprice()
        if mp is None:
            return None
        return Signal(p=_clamp01(mp), confidence=1.0, rationale="market-implied (null model)")


class ExternalPriorProvider(SignalProvider):
    """The drop-in seam for an off-hot-path source (LLM agent, devigged sportsbook, other
    venue). Takes per-market priors and **shrinks toward the live market by confidence**:
    `p = c*prior + (1-c)*market`. Low confidence ⇒ barely deviates from the market, which
    is the conservative default for an estimated edge."""
    name = "external_prior"

    def __init__(self, priors: Dict[str, float], confidence: float = 0.5,
                 shrink_to_market: bool = True) -> None:
        self.priors = priors
        self.confidence = _clamp01(confidence)
        self.shrink_to_market = shrink_to_market

    def fair_value(self, m: BinaryMarket) -> Optional[Signal]:
        prior = self.priors.get(m.market_id)
        if prior is None:
            return None
        c = self.confidence
        p = prior
        if self.shrink_to_market:
            mp = m.yes_book.microprice()
            if mp is not None:
                p = c * prior + (1.0 - c) * mp
        return Signal(p=_clamp01(p), confidence=c,
                      rationale=f"prior={prior:.3f} shrunk to market (c={c:.2f})")


# Structural type of KellyEdgeStrategy.fair_value_fn — no import (avoids a cycle).
FairValueFn = Callable[[BinaryMarket, object], Optional[float]]


def as_fair_value_fn(provider: SignalProvider) -> FairValueFn:
    """Adapt a provider into the `fair_value_fn` hook KellyEdgeStrategy expects."""
    def fn(m: BinaryMarket, _strategy: object) -> Optional[float]:
        s = provider.fair_value(m)
        return None if s is None else s.p
    return fn


# ─────────────────────────── validation harness (the gate) ───────────────────
# A signal earns the right to size capital only by proving skill + calibration on
# resolved real-money markets (ADR-013). All pure stdlib so it's unit-testable.

def brier_score(preds: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error of probabilistic forecasts; 0 = perfect, 0.25 = always-0.5,
    1 = confidently wrong. Lower is better."""
    if len(preds) != len(outcomes):
        raise ValueError("preds and outcomes must align")
    if not preds:
        raise ValueError("no observations")
    return sum((p - y) ** 2 for p, y in zip(preds, outcomes)) / len(preds)


def brier_skill_score(preds: Sequence[float], ref_preds: Sequence[float],
                      outcomes: Sequence[int]) -> float:
    """1 - BS(model)/BS(reference). >0 ⇒ the signal beats the reference (the market);
    0 ⇒ no better; <0 ⇒ worse. This is the core 'does it add information?' metric."""
    bs = brier_score(preds, outcomes)
    ref = brier_score(ref_preds, outcomes)
    if ref == 0.0:
        return 0.0 if bs == 0.0 else float("-inf")
    return 1.0 - bs / ref


@dataclass
class CalibrationBin:
    lo: float
    hi: float
    count: int
    mean_pred: float       # average predicted probability in the bin
    obs_freq: float        # observed YES frequency in the bin


def calibration_curve(preds: Sequence[float], outcomes: Sequence[int],
                      n_bins: int = 10) -> List[CalibrationBin]:
    """Reliability curve: bin predictions and compare mean predicted vs observed frequency.
    A well-calibrated signal has obs_freq ≈ mean_pred in every populated bin."""
    if len(preds) != len(outcomes):
        raise ValueError("preds and outcomes must align")
    bins: List[CalibrationBin] = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        members = [(p, y) for p, y in zip(preds, outcomes)
                   if (lo <= p < hi) or (i == n_bins - 1 and p == 1.0)]
        if not members:
            continue
        ps = [p for p, _ in members]
        ys = [y for _, y in members]
        bins.append(CalibrationBin(lo, hi, len(members),
                                   sum(ps) / len(ps), sum(ys) / len(ys)))
    return bins


def expected_calibration_error(preds: Sequence[float], outcomes: Sequence[int],
                               n_bins: int = 10) -> float:
    """Count-weighted mean |obs_freq - mean_pred| across bins. 0 = perfectly calibrated."""
    bins = calibration_curve(preds, outcomes, n_bins)
    n = len(preds)
    if n == 0:
        raise ValueError("no observations")
    return sum(b.count * abs(b.obs_freq - b.mean_pred) for b in bins) / n


@dataclass
class SignalReport:
    n: int
    brier: float
    ref_brier: float
    skill: float
    ece: float
    bins: List[CalibrationBin] = field(default_factory=list)
    # gate thresholds (ADR-013)
    max_ece: float = 0.10

    @property
    def has_skill(self) -> bool:
        return self.skill > 0.0

    @property
    def well_calibrated(self) -> bool:
        return self.ece <= self.max_ece

    @property
    def trustworthy(self) -> bool:
        """The gate: a provider may size capital only if it beats the market AND is calibrated."""
        return self.has_skill and self.well_calibrated


def evaluate_provider(provider: SignalProvider,
                      samples: Sequence[Tuple[BinaryMarket, int]],
                      reference: Optional[SignalProvider] = None,
                      n_bins: int = 10, max_ece: float = 0.10) -> SignalReport:
    """Score a provider on resolved markets. `samples` are (market_snapshot, outcome∈{0,1}).
    Reference defaults to the market-implied null model, so `skill > 0` means the provider
    extracted information the market price did not already contain."""
    reference = reference or MarketImpliedProvider()
    preds: List[float] = []
    ref_preds: List[float] = []
    outcomes: List[int] = []
    for m, y in samples:
        s = provider.fair_value(m)
        r = reference.fair_value(m)
        if s is None or r is None:
            continue                      # provider abstained — not scored
        preds.append(s.p)
        ref_preds.append(r.p)
        outcomes.append(int(y))
    if not preds:
        raise ValueError("provider produced no scorable signals")
    return SignalReport(
        n=len(preds),
        brier=brier_score(preds, outcomes),
        ref_brier=brier_score(ref_preds, outcomes),
        skill=brier_skill_score(preds, ref_preds, outcomes),
        ece=expected_calibration_error(preds, outcomes, n_bins),
        bins=calibration_curve(preds, outcomes, n_bins),
        max_ece=max_ece,
    )
