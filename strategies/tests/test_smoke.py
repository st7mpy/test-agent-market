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
                                time_to_resolution=40.0)
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


def test_risk_gate_enforces_limits():
    from predmkt import LimitOrder, Portfolio, TIF
    from predmkt.execution import RiskGate, RiskLimits
    m = binary_market("m", 0.50, category="politics", size=1000)
    pf = Portfolio(cash=100_000)
    gate = RiskGate(RiskLimits(max_position_shares=100, max_order_notional=10_000))
    small = LimitOrder(market_id="m", token=Token.YES, side=Side.BUY,
                       price=0.5, size=50, tif=TIF.GTC)
    big = LimitOrder(market_id="m", token=Token.YES, side=Side.BUY,
                     price=0.5, size=500, tif=TIF.GTC)
    assert gate.check(small, pf, m)[0] is True
    assert gate.check(big, pf, m)[0] is False        # 500 > max_position_shares
    gate.kill_switch = True
    assert gate.check(small, pf, m)[0] is False        # kill-switch blocks all


def test_paper_oms_runs_over_fixture():
    from predmkt import Portfolio
    from predmkt.data import load_fixture
    from predmkt.execution import PaperBroker, PaperOMS, RiskGate
    from predmkt.venue import ReplayAdapter
    adapter = ReplayAdapter(load_fixture()[:120], market_id="replay", outcome="YES")
    oms = PaperOMS(MarketMakerStrategy(MMParams(market_id="replay")),
                   RiskGate(), PaperBroker(Portfolio(cash=100_000)))
    n = 0
    while True:
        m = adapter.fetch_market()
        if m is None:
            break
        oms.step(m)
        n += 1
    assert n == 120 and len(oms.equity) == 120
    assert adapter.resolution() == "YES"


def test_reconciler_detects_divergence():
    from predmkt import Position
    from predmkt.reconcile import Reconciler
    r = Reconciler(tolerance=1e-6)
    a = {"m": Position(yes=200, no=0)}
    assert r.reconcile(a, {"m": Position(yes=200, no=0)}).ok is True
    bad = r.reconcile(a, {"m": Position(yes=700, no=0)})
    assert bad.ok is False and bad.breaches(1e-6)[0].max_abs() == 500


def test_live_loop_halts_on_injected_divergence():
    import live
    from predmkt import Portfolio
    from predmkt.data import load_fixture
    from predmkt.execution import PaperBroker, RiskGate
    from predmkt.venue import ReplayAdapter
    adapter = ReplayAdapter(load_fixture(), market_id="replay", outcome="YES")
    broker = PaperBroker(Portfolio(cash=100_000))
    risk = RiskGate()
    out = live.run(adapter, MarketMakerStrategy(MMParams(market_id="replay")),
                   broker, risk, steps=200, reconcile_every=25,
                   inject_at=100, inject_yes=500.0, verbose=False)
    assert out["halted"] is True and out["kill_switch"] is True
    assert out["steps_run"] <= 101            # stopped at/around the injection
    assert out["resolution"] is None          # no settlement when positions untrusted


def test_live_loop_clean_when_no_fault():
    import live
    from predmkt import Portfolio
    from predmkt.data import load_fixture
    from predmkt.execution import PaperBroker, RiskGate
    from predmkt.venue import ReplayAdapter
    adapter = ReplayAdapter(load_fixture(), market_id="replay", outcome="YES")
    broker = PaperBroker(Portfolio(cash=100_000))
    out = live.run(adapter, MarketMakerStrategy(MMParams(market_id="replay")),
                   broker, RiskGate(), steps=400, reconcile_every=25, verbose=False)
    assert out["halted"] is False and out["kill_switch"] is False


def test_backtest_runs_on_fixture():
    import backtest
    from predmkt.data import load_fixture
    hist = load_fixture()
    assert len(hist) > 50
    res = backtest.run_backtest(
        MarketMakerStrategy(MMParams(market_id="m")), hist, outcome="YES")
    assert len(res.equity) == len(hist) + 1   # one mark per tick + settlement
    assert res.equity[0] > 0 and res.bankroll > 0


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} smoke tests passed.")
