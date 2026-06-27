"""Position reconciliation (ARCHITECTURE.md ADR-011).

The OMS's internal expectation of positions is a *derived view*; the venue is the
source of truth. Any material divergence is a bug or an exploit, so the platform
reconciles them and **halts on divergence** (trips the kill-switch) rather than
trusting a drifting internal ledger.

This is the position-level version of the NAV reconciliation invariant; the same
mechanism extends to cash/NAV in the full system.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .types import Position


@dataclass
class MarketDiff:
    market_id: str
    internal_yes: float
    venue_yes: float
    internal_no: float
    venue_no: float

    def max_abs(self) -> float:
        return max(abs(self.internal_yes - self.venue_yes),
                   abs(self.internal_no - self.venue_no))


@dataclass
class ReconResult:
    ok: bool
    diffs: List[MarketDiff] = field(default_factory=list)

    def breaches(self, tol: float) -> List[MarketDiff]:
        return [d for d in self.diffs if d.max_abs() > tol]


class Reconciler:
    def __init__(self, tolerance: float = 1e-6) -> None:
        self.tolerance = tolerance

    def reconcile(self, internal: Dict[str, Position],
                  venue: Dict[str, Position]) -> ReconResult:
        ok = True
        diffs: List[MarketDiff] = []
        for k in set(internal) | set(venue):
            i = internal.get(k, Position())
            v = venue.get(k, Position())
            d = MarketDiff(k, i.yes, v.yes, i.no, v.no)
            if d.max_abs() > self.tolerance:
                ok = False
            diffs.append(d)
        return ReconResult(ok, diffs)
