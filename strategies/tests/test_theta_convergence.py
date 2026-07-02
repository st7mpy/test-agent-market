#!/usr/bin/env python3
"""Tests for the resolution-convergence "theta" strategy.
Run: `cd strategies && python tests/test_theta_convergence.py`.
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    Context, OracleRiskModel, Side, ThetaConvergenceStrategy, ThetaParams, Token,
)
from predmkt.sim import binary_market  # noqa: E402


def _ctx(*markets):
    return Context(markets={m.market_id: m for m in markets})


def _fav(mid=0.955, ttr=10.0, market_id="m", **kw):
    return binary_market(market_id, mid, time_to_resolution=ttr, **kw)


# --- the carry math ------------------------------------------------------------ #
def test_annualized_return_compounds_per_trade_yield():
    # 96c favorite, no fee, 10 days out (periods=days, ppy=365):
    # per-trade 4/96 = 4.167%, ~36.5 turns/year -> ~344% APR
    apr = ThetaConvergenceStrategy.annualized_return(0.96, 0.0, 10.0, 365.0)
    assert 3.0 < apr < 4.0


def test_annualized_return_degenerate_inputs():
    assert ThetaConvergenceStrategy.annualized_return(1.0, 0.0, 10.0, 365.0) == 0.0
    assert ThetaConvergenceStrategy.annualized_return(0.99, 0.02, 10.0, 365.0) == 0.0  # cost > 1
    assert ThetaConvergenceStrategy.annualized_return(0.96, 0.0, 0.0, 365.0) == 0.0


# --- entry logic ----------------------------------------------------------------- #
def test_buys_near_resolution_favorite():
    intents = ThetaConvergenceStrategy(100_000.0).on_tick(_ctx(_fav()))
    assert len(intents) == 1
    it = intents[0]
    assert it.token == Token.YES and it.side == Side.BUY


def test_no_side_favorite_is_bought_too():
    m = _fav(mid=0.04)                            # YES at 4c -> NO is the 96c favorite
    intents = ThetaConvergenceStrategy(100_000.0).on_tick(_ctx(m))
    assert len(intents) == 1
    assert intents[0].token == Token.NO


def test_skips_outside_carry_zone():
    m = _fav(ttr=100.0)                           # too far from resolution
    assert ThetaConvergenceStrategy(100_000.0).on_tick(_ctx(m)) == []


def test_skips_below_min_price():
    m = _fav(mid=0.70)                            # not a near-certain favorite
    assert ThetaConvergenceStrategy(100_000.0).on_tick(_ctx(m)) == []


def test_skips_when_apr_below_hurdle():
    # 99.5c favorite 30 days out yields ~6% APR net of fees — below the 30% hurdle
    m = _fav(mid=0.99, ttr=30.0)
    p = ThetaParams(hurdle_apr=0.30)
    assert ThetaConvergenceStrategy(100_000.0, p).on_tick(_ctx(m)) == []


def test_oracle_risk_gate_is_strict():
    # 0.35 would pass the longshot strategy's default cap but not theta's 0.25
    model = OracleRiskModel(overrides={"m": 0.35})
    strat = ThetaConvergenceStrategy(100_000.0, oracle_model=model)
    assert strat.on_tick(_ctx(_fav())) == []


def test_repricing_guard_blocks_slipping_favorite():
    """A favorite that was 99c and is now 95.5c is repricing on news, not decaying."""
    strat = ThetaConvergenceStrategy(100_000.0)
    strat._hist["m"] = deque([0.99, 0.98], maxlen=30)
    assert strat.on_tick(_ctx(_fav(mid=0.955))) == []


# --- sizing ------------------------------------------------------------------------ #
def test_risk_budget_bounds_notional():
    bankroll = 100_000.0
    p = ThetaParams(risk_per_market=0.02)
    m = _fav(size=1_000_000.0)                    # deep book: budget binds, not depth
    intents = ThetaConvergenceStrategy(bankroll, p).on_tick(_ctx(m))
    assert len(intents) == 1
    it = intents[0]
    assert it.size * it.price <= p.risk_per_market * bankroll + 1e-6


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} theta-convergence tests passed.")
