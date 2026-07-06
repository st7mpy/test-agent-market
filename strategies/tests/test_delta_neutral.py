#!/usr/bin/env python3
"""Tests for the delta-neutral set-minting yield strategy (strategy 8).
Run: `cd strategies && python tests/test_delta_neutral.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    CancelAll, Context, DeltaNeutralParams, DeltaNeutralYieldStrategy, LimitOrder,
    Merge, Portfolio, RiskGate, RiskLimits, Side, Token,
)
from predmkt.execution import PaperBroker, PaperOMS  # noqa: E402
from predmkt.sim import binary_market  # noqa: E402


def _strat(**over):
    return DeltaNeutralYieldStrategy(100_000.0, DeltaNeutralParams(market_id="m", **over))


def _ctx(mid=0.50, yes=0.0, no=0.0):
    pf = Portfolio()
    pos = pf.position("m")
    pos.yes, pos.no = yes, no
    return Context(markets={"m": binary_market("m", mid)}, portfolio=pf)


def test_quotes_both_sides_summing_below_one():
    out = _strat().on_tick(_ctx())
    buys = [i for i in out if isinstance(i, LimitOrder)]
    assert {b.token for b in buys} == {Token.YES, Token.NO}
    assert all(b.side == Side.BUY for b in buys)
    total = sum(b.price for b in buys)
    assert abs(total - (1.0 - 2 * 0.01)) < 1e-9, "prices must sum to 1 - 2*half_spread"


def test_merge_realizes_matched_sets():
    out = _strat().on_tick(_ctx(yes=500, no=300))
    merges = [i for i in out if isinstance(i, Merge)]
    assert len(merges) == 1 and abs(merges[0].shares - 300) < 1e-9, \
        "matched inventory (min(yes,no)) should be merged back to cash"


def test_delta_band_gates_heavy_side_only():
    out = _strat(delta_band=300).on_tick(_ctx(yes=1000, no=0))
    tokens = {i.token for i in out if isinstance(i, LimitOrder)}
    assert tokens == {Token.NO}, "long-YES imbalance beyond the band must stop YES bids"
    out2 = _strat(delta_band=300).on_tick(_ctx(yes=0, no=1000))
    tokens2 = {i.token for i in out2 if isinstance(i, LimitOrder)}
    assert tokens2 == {Token.YES}


def test_out_of_range_market_pulls_quotes():
    out = _strat().on_tick(_ctx(mid=0.97))
    assert not [i for i in out if isinstance(i, LimitOrder)]
    assert [i for i in out if isinstance(i, CancelAll)], "extreme mids: cancel, don't quote"


def test_gross_cap_stops_new_exposure():
    s = DeltaNeutralYieldStrategy(1_000.0, DeltaNeutralParams(market_id="m", gross_cap=0.10))
    # unmatched YES leg worth ~$400 >> 10% of $1k bankroll
    out = s.on_tick(_ctx(yes=800, no=0))
    assert not [i for i in out if isinstance(i, LimitOrder)], "over cap: no new quotes"


def test_oscillating_market_harvests_spread_end_to_end():
    # alternate the mid around 0.50 so each side's passive bid fills in turn,
    # then merges convert matched sets into cash at the 2*delta discount.
    strat = _strat(quote_size=100, delta_band=1000)
    broker = PaperBroker(Portfolio(cash=100_000.0))
    gate = RiskGate(RiskLimits(max_position_shares=100_000, max_order_notional=100_000))
    oms = PaperOMS(strat, gate, broker)
    mids = [0.50, 0.485, 0.50, 0.515, 0.50] * 12          # cross both bids repeatedly
    for i, mid in enumerate(mids):
        oms.step(binary_market("m", mid, time_to_resolution=float(len(mids) - i)))
    assert broker.n_fills > 10, "both legs should fill across the oscillation"
    pos = broker.pf.position("m")
    assert min(pos.yes, pos.no) < 1.0, "matched sets should have been merged away"
    assert oms.equity[-1] > 100_000.0, "harvested spread should net positive equity"


def test_runner_session_reconciles_through_merges():
    # regression: Merge/Split must be mirrored to the venue ledger, or the
    # reconciler (ADR-011) reads the internal position change as a divergence
    # and trips the kill-switch (this exact failure was observed pre-fix).
    import json
    import tempfile

    import run as runner
    with tempfile.TemporaryDirectory() as d:
        cfg_path = os.path.join(d, "cfg.json")
        json.dump({"strategy": {"name": "deltaneutral", "params": {"quote_size": 100}},
                   "loop": {"steps": 120, "reconcile_every": 20},
                   "report_path": os.path.join(d, "r.json")}, open(cfg_path, "w"))
        report = runner.run_session(runner.load_config(cfg_path), verbose=False)
    assert report["halted"] is False and report["kill_switch"] is False, \
        "set merges must reconcile cleanly against the venue ledger"
    assert report["fills"] > 0, "the bot should have traded on the fixture"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} delta-neutral tests passed.")
