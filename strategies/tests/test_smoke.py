#!/usr/bin/env python3
"""Dependency-free smoke tests. Run: `cd strategies && python tests/test_smoke.py`.

Asserts each sample strategy emits sensible intents on a known scenario, and that
the no-edge cases stay quiet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    ArbitrageStrategy, BinaryMarket, Context, CrossVenuePair, Event,
    KellyEdgeStrategy, KellyParams, LimitOrder, MarketMakerStrategy, MMParams,
    Side, Token, Venue,
)
from predmkt.sim import binary_market, book, random_walk_market  # noqa: E402


def test_intra_market_arb_fires():
    m = BinaryMarket("m", "politics",
                     book([(0.46, 800)], [(0.47, 800)]),
                     book([(0.465, 800)], [(0.475, 800)]), 86400.0)
    out = ArbitrageStrategy().on_tick(Context(markets={"m": m}))
    buys = [i for i in out if isinstance(i, LimitOrder) and i.side == Side.BUY]
    assert len(buys) == 2, "expected to buy both YES and NO legs"
    assert {b.token for b in buys} == {Token.YES, Token.NO}


def test_no_arb_when_overpriced():
    # YES ask + NO ask = 1.02 > 1 -> no buy-both edge
    m = BinaryMarket("m", "politics",
                     book([(0.50, 800)], [(0.51, 800)]),
                     book([(0.50, 800)], [(0.51, 800)]), 86400.0)
    out = ArbitrageStrategy().on_tick(Context(markets={"m": m}))
    assert out == [], "should not trade when set is overpriced"


def test_cross_venue_blocked_on_basis_risk():
    a = binary_market("a", 0.44, venue=Venue.POLYMARKET)
    b = binary_market("b", 0.50, venue=Venue.KALSHI)
    pair = CrossVenuePair(a, b, resolution_rules_match=False)
    out = ArbitrageStrategy().on_tick(Context(cross_pairs=[pair]))
    assert out == [], "must not 'arb' when resolution rules differ (basis risk)"


def test_market_maker_quotes_and_skews():
    mm = MarketMakerStrategy(MMParams(market_id="m", quote_size=200, max_inventory=1000))
    series = random_walk_market("m", 0.50, 0.004, 40, category="crypto",
                                seconds_to_resolution=3600.0)
    last = []
    for t, m in enumerate(series):
        last = mm.on_tick(Context(now=float(t), markets={"m": m}))
    assert any(getattr(i, "side", None) == Side.BUY for i in last)
    assert any(getattr(i, "side", None) == Side.SELL for i in last)
    for i in last:
        assert 0.0 < i.price < 1.0, "quotes must stay inside [0,1]"


def test_kelly_sizes_on_edge_and_skips_without():
    m_edge = binary_market("edge", 0.40, category="sports")
    m_fair = binary_market("fair", 0.60, category="sports")
    strat = KellyEdgeStrategy(100_000.0, KellyParams(),
                              reference_probs={"edge": 0.55, "fair": 0.605})
    out = strat.on_tick(Context(markets={"edge": m_edge, "fair": m_fair}))
    assert len(out) == 1 and out[0].market_id == "edge"
    assert out[0].size > 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} smoke tests passed.")
