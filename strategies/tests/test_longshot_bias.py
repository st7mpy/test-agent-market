#!/usr/bin/env python3
"""Tests for the favorite-longshot bias harvester.
Run: `cd strategies && python tests/test_longshot_bias.py`.
"""
import os
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    Context, LongshotBiasStrategy, LongshotParams, OracleRiskModel, Side, Token, debias,
)
from predmkt.sim import binary_market  # noqa: E402


def _ctx(*markets):
    return Context(markets={m.market_id: m for m in markets})


# --- the debias map ----------------------------------------------------------- #
def test_debias_shrinks_tails_and_keeps_center():
    assert debias(0.05, 1.4) < 0.05              # longshot overpriced -> true prob lower
    assert debias(0.95, 1.4) > 0.95              # favorite underpriced -> true prob higher
    assert abs(debias(0.50, 1.4) - 0.50) < 1e-12
    assert abs(debias(0.30, 1.0) - 0.30) < 1e-12  # beta=1 is the identity
    assert debias(0.0, 1.4) == 0.0 and debias(1.0, 1.4) == 1.0


# --- entry logic --------------------------------------------------------------- #
def test_buys_favorite_against_overpriced_longshot():
    m = binary_market("m", 0.05)                  # 5c longshot: NO is the favorite
    intents = LongshotBiasStrategy(100_000.0).on_tick(_ctx(m))
    assert len(intents) == 1
    it = intents[0]
    assert it.token == Token.NO and it.side == Side.BUY
    assert it.market_id == "m"


def test_symmetric_yes_favorite():
    m = binary_market("m", 0.95)                  # YES is the favorite side
    intents = LongshotBiasStrategy(100_000.0).on_tick(_ctx(m))
    assert len(intents) == 1
    assert intents[0].token == Token.YES


def test_mid_range_market_is_skipped():
    m = binary_market("m", 0.50)
    assert LongshotBiasStrategy(100_000.0).on_tick(_ctx(m)) == []


def test_momentum_veto_blocks_strengthening_tail():
    """If the YES tail rallied from 3c to 9c, the NO favorite lost 6c — that's news."""
    strat = LongshotBiasStrategy(100_000.0)
    strat._hist["m"] = deque([0.03, 0.05, 0.09], maxlen=30)
    m = binary_market("m", 0.09)
    assert strat.on_tick(_ctx(m)) == []


def test_oracle_risk_gate_blocks_disputed_market():
    model = OracleRiskModel(overrides={"m": 0.90})
    m = binary_market("m", 0.05)
    strat = LongshotBiasStrategy(100_000.0, oracle_model=model)
    assert strat.on_tick(_ctx(m)) == []


def test_one_bite_per_market():
    m = binary_market("m", 0.05)
    ctx = _ctx(m)
    ctx.portfolio.position("m").no = 100.0        # already long the favorite
    assert LongshotBiasStrategy(100_000.0).on_tick(ctx) == []


# --- sizing --------------------------------------------------------------------- #
def test_risk_budget_bounds_notional():
    """A full tail loss must cost <= risk_per_market of bankroll."""
    bankroll = 100_000.0
    p = LongshotParams(risk_per_market=0.02)
    m = binary_market("m", 0.05, size=1_000_000.0)   # deep book: budget binds, not depth
    intents = LongshotBiasStrategy(bankroll, p).on_tick(_ctx(m))
    assert len(intents) == 1
    it = intents[0]
    assert it.size * it.price <= p.risk_per_market * bankroll + 1e-6


def test_max_entries_per_tick():
    p = LongshotParams(max_entries_per_tick=2)
    markets = [binary_market(f"m{i}", 0.05) for i in range(5)]
    intents = LongshotBiasStrategy(100_000.0, p).on_tick(_ctx(*markets))
    assert len(intents) == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} longshot-bias tests passed.")
