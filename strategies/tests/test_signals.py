#!/usr/bin/env python3
"""Tests for the signal layer (F): providers, the fair_value_fn adapter, and the
Brier/calibration validation harness. Run: `cd strategies && python tests/test_signals.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    BinaryMarket, ExternalPriorProvider, KellyEdgeStrategy, MarketImpliedProvider,
    as_fair_value_fn, brier_score, brier_skill_score, evaluate_provider,
    expected_calibration_error,
)
from predmkt.sim import book  # noqa: E402


def _mkt(mid: float, mid_id: str = "m") -> BinaryMarket:
    """A market whose YES micro-price equals `mid` (symmetric depth around it)."""
    half = 0.01
    return BinaryMarket(mid_id, "politics",
                        book([(mid - half, 100)], [(mid + half, 100)]),
                        book([(1 - mid - half, 100)], [(1 - mid + half, 100)]), 86400.0)


# --- Brier math ------------------------------------------------------------- #
def test_brier_perfect_and_worst():
    assert brier_score([0.0, 1.0], [0, 1]) == 0.0
    assert brier_score([1.0, 0.0], [0, 1]) == 1.0
    assert abs(brier_score([0.5, 0.5], [0, 1]) - 0.25) < 1e-12


def test_brier_skill_sign():
    outcomes = [1, 1, 0, 0]
    good = [0.9, 0.8, 0.2, 0.1]
    ref  = [0.5, 0.5, 0.5, 0.5]
    assert brier_skill_score(good, ref, outcomes) > 0       # beats the reference
    assert brier_skill_score(ref, ref, outcomes) == 0.0     # ties the reference
    bad = [0.1, 0.2, 0.8, 0.9]
    assert brier_skill_score(bad, ref, outcomes) < 0        # worse than reference


def test_ece_zero_when_calibrated():
    # within a bin, observed frequency equals the predicted value -> ECE 0
    preds = [0.5, 0.5, 0.5, 0.5]
    outcomes = [1, 1, 0, 0]            # freq 0.5 == pred 0.5
    assert abs(expected_calibration_error(preds, outcomes, n_bins=10)) < 1e-12


# --- providers -------------------------------------------------------------- #
def test_market_implied_returns_microprice():
    s = MarketImpliedProvider().fair_value(_mkt(0.40))
    assert s is not None and abs(s.p - 0.40) < 1e-9


def test_external_prior_shrinks_to_market():
    # prior 0.80, market 0.50, confidence 0.5 -> 0.5*0.8 + 0.5*0.5 = 0.65
    prov = ExternalPriorProvider({"m": 0.80}, confidence=0.5, shrink_to_market=True)
    s = prov.fair_value(_mkt(0.50))
    assert s is not None and abs(s.p - 0.65) < 1e-9
    # full confidence -> no shrinkage
    prov2 = ExternalPriorProvider({"m": 0.80}, confidence=1.0)
    assert abs(prov2.fair_value(_mkt(0.50)).p - 0.80) < 1e-9
    # unknown market -> abstain
    assert prov.fair_value(_mkt(0.50, "other")) is None


def test_as_fair_value_fn_plugs_into_kelly():
    prov = ExternalPriorProvider({"m": 0.80}, confidence=1.0)
    fn = as_fair_value_fn(prov)
    strat = KellyEdgeStrategy(bankroll=100_000, fair_value_fn=fn)
    # the hook returns the provider's probability for the market
    assert abs(fn(_mkt(0.50), strat) - 0.80) < 1e-9


# --- end-to-end evaluation gate --------------------------------------------- #
def test_evaluate_provider_detects_skill_and_gates():
    # build resolved markets: the market price is biased low; the informed provider
    # (high confidence on the true prob) should beat it and be the trustworthy one.
    samples = []
    informed = {}
    # 20 markets that resolve YES priced at 0.40 (market underprices YES)
    for i in range(20):
        mid_id = f"yes{i}"
        samples.append((_mkt(0.40, mid_id), 1))
        informed[mid_id] = 0.85
    # 20 markets that resolve NO priced at 0.60 (market overprices YES)
    for i in range(20):
        mid_id = f"no{i}"
        samples.append((_mkt(0.60, mid_id), 0))
        informed[mid_id] = 0.15

    informed_prov = ExternalPriorProvider(informed, confidence=1.0, shrink_to_market=False)
    rep_informed = evaluate_provider(informed_prov, samples)
    rep_market = evaluate_provider(MarketImpliedProvider(), samples)

    assert rep_informed.n == 40
    assert rep_informed.has_skill, "informed provider should beat the market"
    assert rep_informed.skill > rep_market.skill
    # the market vs itself has exactly zero skill (the null reference)
    assert abs(rep_market.skill) < 1e-12
    assert not rep_market.trustworthy, "the market is not its own edge"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} signal-layer tests passed.")
