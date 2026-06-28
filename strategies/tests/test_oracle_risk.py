#!/usr/bin/env python3
"""Tests for oracle/resolution-risk scoring + RiskGate gating (C, ADR-014).
Run: `cd strategies && python tests/test_oracle_risk.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    OracleRiskModel, Portfolio, RiskGate, RiskLimits, Side, TIF, Token,
)
from predmkt.sim import binary_market  # noqa: E402
from predmkt.types import LimitOrder, Split  # noqa: E402


def _m(market_id="m", category="politics"):
    return binary_market(market_id, 0.50, category=category)


# --- scoring ---------------------------------------------------------------- #
def test_score_category_base_and_default():
    model = OracleRiskModel()
    assert abs(model.score(_m(category="crypto")) - 0.10) < 1e-9
    assert abs(model.score(_m(category="world")) - 0.55) < 1e-9
    assert abs(model.score(_m(category="unknown_cat")) - 0.30) < 1e-9   # default_base


def test_score_flags_add_and_clamp():
    model = OracleRiskModel(flags={"m": ["active_dispute"]})        # 0.35 + 0.60
    assert abs(model.score(_m()) - 0.95) < 1e-9
    model2 = OracleRiskModel(flags={"m": ["active_dispute", "thin_oracle"]})  # clamps at 1.0
    assert model2.score(_m()) == 1.0


def test_score_override_wins():
    model = OracleRiskModel(overrides={"m": 0.07})
    assert abs(model.score(_m(category="world")) - 0.07) < 1e-9


# --- gating ----------------------------------------------------------------- #
def test_gate_refuses_opening_exposure_in_risky_market():
    model = OracleRiskModel(overrides={"m": 0.70})
    gate = RiskGate(RiskLimits(max_oracle_risk=0.50), oracle_model=model)
    ok, reason = gate.check(
        LimitOrder("", "m", Token.YES, Side.BUY, 0.50, 100, TIF.GTC), Portfolio(), _m())
    assert not ok and "oracle risk" in reason


def test_gate_allows_exit_from_risky_market():
    """A market that turns risky must still be EXITABLE — gating is increase-only."""
    model = OracleRiskModel(overrides={"m": 0.90})
    gate = RiskGate(RiskLimits(max_oracle_risk=0.50), oracle_model=model)
    pf = Portfolio()
    pf.position("m").yes = 1000.0                       # existing long

    # selling DOWN the position (risk-reducing) is allowed despite high oracle risk
    sell = LimitOrder("", "m", Token.YES, Side.SELL, 0.50, 500, TIF.GTC)
    ok, _ = gate.check(sell, pf, _m())
    assert ok, "must be able to exit a risky market"

    # buying MORE (increasing) is refused
    buy = LimitOrder("", "m", Token.YES, Side.BUY, 0.50, 500, TIF.GTC)
    ok, reason = gate.check(buy, pf, _m())
    assert not ok and "oracle risk" in reason


def test_gate_scales_notional_by_risk():
    # score 0.50, base notional cap 10k -> effective cap 5k for new exposure
    model = OracleRiskModel(overrides={"m": 0.50})
    gate = RiskGate(RiskLimits(max_order_notional=10_000, max_position_shares=10**9,
                               max_oracle_risk=0.90), oracle_model=model)
    # notional 6000 (> 5000 effective) -> refused
    big = LimitOrder("", "m", Token.YES, Side.BUY, 1.0, 6000, TIF.GTC)
    ok, reason = gate.check(big, Portfolio(), _m())
    assert not ok and "oracle-risk-scaled" in reason
    # notional 4000 (< 5000 effective) -> allowed
    small = LimitOrder("", "m", Token.YES, Side.BUY, 1.0, 4000, TIF.GTC)
    ok, _ = gate.check(small, Portfolio(), _m())
    assert ok


def test_split_is_gated_as_increasing():
    model = OracleRiskModel(overrides={"m": 0.80})
    gate = RiskGate(RiskLimits(max_oracle_risk=0.50), oracle_model=model)
    ok, reason = gate.check(Split("", "m", 1000.0), Portfolio(), _m())
    assert not ok and "oracle risk" in reason


def test_backward_compatible_without_model():
    # no oracle model / no max_oracle_risk -> behaves exactly as before
    gate = RiskGate(RiskLimits())
    ok, _ = gate.check(
        LimitOrder("", "m", Token.YES, Side.BUY, 0.50, 100, TIF.GTC),
        Portfolio(), _m(category="world"))
    assert ok


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} oracle-risk tests passed.")
