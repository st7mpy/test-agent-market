#!/usr/bin/env python3
"""Tests for the smart-money flow signal provider.
Run: `cd strategies && python tests/test_flow_signal.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    FlowTrade, Side, SmartMoneyParams, SmartMoneyProvider, Token, WalletScore,
    evaluate_provider, score_wallets, signed_yes_exposure,
)
from predmkt.sim import binary_market  # noqa: E402


# --- normalization -------------------------------------------------------------- #
def test_signed_yes_exposure_all_four_quadrants():
    assert signed_yes_exposure(FlowTrade("w", "m", Token.YES, Side.BUY, 0.60, 10)) == (10, 0.60)
    assert signed_yes_exposure(FlowTrade("w", "m", Token.YES, Side.SELL, 0.60, 10)) == (-10, 0.60)
    signed, px = signed_yes_exposure(FlowTrade("w", "m", Token.NO, Side.BUY, 0.30, 10))
    assert signed == -10 and abs(px - 0.70) < 1e-12       # buying NO = short YES at 1-q
    signed, px = signed_yes_exposure(FlowTrade("w", "m", Token.NO, Side.SELL, 0.30, 10))
    assert signed == 10 and abs(px - 0.70) < 1e-12


# --- wallet scoring --------------------------------------------------------------- #
def test_score_wallets_rewards_realized_edge():
    trades = (
        # sharp: bought YES at 60c on markets that resolved YES (edge +0.40/trade)
        [FlowTrade("sharp", f"m{i}", Token.YES, Side.BUY, 0.60, 100) for i in range(30)]
        # dull: bought YES at 60c on markets that resolved NO (edge -0.60/trade)
        + [FlowTrade("dull", f"n{i}", Token.YES, Side.BUY, 0.60, 100) for i in range(30)]
    )
    outcomes = {f"m{i}": 1 for i in range(30)}
    outcomes.update({f"n{i}": 0 for i in range(30)})
    scores = score_wallets(trades, outcomes)
    assert scores["sharp"].skill > 0.1
    assert scores["dull"].skill < -0.1
    assert abs(scores["sharp"].raw_edge - 0.40) < 1e-9


def test_shrinkage_discounts_small_samples():
    lucky = [FlowTrade("lucky", "m0", Token.YES, Side.BUY, 0.60, 100)]
    proven = [FlowTrade("proven", f"m{i}", Token.YES, Side.BUY, 0.60, 100) for i in range(100)]
    outcomes = {f"m{i}": 1 for i in range(100)}
    scores = score_wallets(lucky + proven, outcomes)
    assert abs(scores["lucky"].raw_edge - scores["proven"].raw_edge) < 1e-9   # same per-trade edge
    assert scores["lucky"].skill < scores["proven"].skill / 3                 # but far less trusted


def test_unresolved_markets_are_not_scored():
    trades = [FlowTrade("w", "open", Token.YES, Side.BUY, 0.60, 100)]
    assert score_wallets(trades, {}) == {}


# --- the provider ------------------------------------------------------------------ #
def _provider(skill=0.10, **params):
    scores = {"sharp": WalletScore("sharp", 50, skill * 2, skill)}
    return SmartMoneyProvider(scores, SmartMoneyParams(**params) if params else None)


def test_no_flow_falls_back_to_market():
    prov = _provider()
    m = binary_market("m", 0.50)
    s = prov.fair_value(m)
    assert s is not None and s.confidence == 0.0
    assert abs(s.p - 0.50) < 1e-9


def test_smart_buying_tilts_probability_up():
    prov = _provider()
    prov.observe(FlowTrade("sharp", "m", Token.YES, Side.BUY, 0.50, 40_000))
    s = prov.fair_value(binary_market("m", 0.50))
    assert s.p > 0.50 and s.confidence > 0.0


def test_smart_selling_tilts_probability_down():
    prov = _provider()
    prov.observe(FlowTrade("sharp", "m", Token.YES, Side.SELL, 0.50, 40_000))
    s = prov.fair_value(binary_market("m", 0.50))
    assert s.p < 0.50


def test_tilt_is_bounded_by_max_tilt():
    prov = _provider(max_tilt=0.08)
    prov.observe(FlowTrade("sharp", "m", Token.YES, Side.BUY, 0.50, 10_000_000))
    s = prov.fair_value(binary_market("m", 0.50))
    assert s.p <= 0.50 + 0.08 + 1e-9


def test_unproven_wallets_are_ignored():
    prov = SmartMoneyProvider({"noob": WalletScore("noob", 2, 0.4, 0.005)})
    prov.observe(FlowTrade("noob", "m", Token.YES, Side.BUY, 0.50, 40_000))
    s = prov.fair_value(binary_market("m", 0.50))
    assert abs(s.p - 0.50) < 1e-9 and s.confidence == 0.0


def test_provider_shows_brier_skill_when_smart_money_is_right():
    """End-to-end through the ADR-013 gate: when proven wallets lean the right way,
    the provider beats the market-implied null model on resolved markets."""
    prov = _provider()
    samples = []
    for i in range(20):
        mid = f"m{i}"
        outcome = 1 if i % 2 == 0 else 0
        m = binary_market(mid, 0.50)
        side = Side.BUY if outcome == 1 else Side.SELL
        prov.observe(FlowTrade("sharp", mid, Token.YES, side, 0.50, 40_000))
        samples.append((m, outcome))
    report = evaluate_provider(prov, samples)
    assert report.has_skill and report.skill > 0.0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} flow-signal tests passed.")
