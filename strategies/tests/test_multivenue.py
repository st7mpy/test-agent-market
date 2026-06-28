#!/usr/bin/env python3
"""Tests for multi-venue (D): venue-aware fees, the CrossVenueFeed aggregator, and
cross-venue arb across two venues. Run: `cd strategies && python tests/test_multivenue.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    ArbitrageStrategy, ArbParams, Context, CrossVenueFeed, LimitOrder, ReplayAdapter,
    Side, Token, Venue, kalshi_fee_per_share, polymarket_taker_fee_per_share,
    taker_fee_per_share,
)


# --- venue-aware fees ------------------------------------------------------- #
def test_taker_fee_dispatches_by_venue():
    # at p=0.50, Kalshi (0.07*0.25=0.0175) and Polymarket (capped) differ materially
    poly = taker_fee_per_share(Venue.POLYMARKET, 0.50, "politics")
    kal = taker_fee_per_share(Venue.KALSHI, 0.50, "politics")
    assert abs(poly - polymarket_taker_fee_per_share(0.50, "politics")) < 1e-12
    assert abs(kal - kalshi_fee_per_share(0.50)) < 1e-12
    assert poly != kal, "the two venues must price the same fill differently"


def test_kalshi_fee_peaks_at_half_and_vanishes_at_extremes():
    assert kalshi_fee_per_share(0.50) > kalshi_fee_per_share(0.90)
    assert abs(kalshi_fee_per_share(1.0)) < 1e-12


# --- CrossVenueFeed --------------------------------------------------------- #
def test_cross_venue_feed_builds_pair_from_two_venues():
    a = ReplayAdapter([(0, 0.45)], market_id="evt@poly", venue=Venue.POLYMARKET)
    b = ReplayAdapter([(0, 0.49)], market_id="evt@kalshi", venue=Venue.KALSHI)
    feed = CrossVenueFeed(a, b, resolution_rules_match=True)
    pair = feed.fetch_pair()
    assert pair is not None
    assert pair.market_a.venue == Venue.POLYMARKET
    assert pair.market_b.venue == Venue.KALSHI
    assert pair.resolution_rules_match is True
    # exhausted source -> None
    assert feed.fetch_pair() is None


def test_cross_venue_feed_defaults_to_basis_risk():
    a = ReplayAdapter([(0, 0.45)], market_id="evt@poly", venue=Venue.POLYMARKET)
    b = ReplayAdapter([(0, 0.49)], market_id="evt@kalshi", venue=Venue.KALSHI)
    feed = CrossVenueFeed(a, b)                      # no assertion that rules match
    assert feed.fetch_pair().resolution_rules_match is False


# --- cross-venue arbitrage across the two venues ---------------------------- #
def _pair(yes_a_mid, yes_b_mid, rules_match=True):
    # venue A (Polymarket) priced so YES is cheap; venue B (Kalshi) so NO is cheap
    a = ReplayAdapter([(0, yes_a_mid)], market_id="evt@poly",
                      venue=Venue.POLYMARKET, depth=5000.0, spread=0.01)
    b = ReplayAdapter([(0, yes_b_mid)], market_id="evt@kalshi",
                      venue=Venue.KALSHI, depth=5000.0, spread=0.01)
    return CrossVenueFeed(a, b, resolution_rules_match=rules_match).fetch_pair()


def test_cross_venue_arb_fires_when_legs_diverge():
    # YES cheap on A (~0.40 ask), NO cheap on B (B's YES ~0.50 -> NO ask ~0.51)
    # YES_ask(A) + NO_ask(B) well below 1 -> locked edge after fees
    pair = _pair(0.40, 0.50)
    out = ArbitrageStrategy(ArbParams(min_edge=0.01)).on_tick(Context(cross_pairs=[pair]))
    buys = [i for i in out if isinstance(i, LimitOrder) and i.side == Side.BUY]
    assert len(buys) == 2, "should buy YES on one venue and NO on the other"
    assert {b.token for b in buys} == {Token.YES, Token.NO}
    venues_touched = {b.market_id for b in buys}
    assert venues_touched == {"evt@poly", "evt@kalshi"}, "legs span both venues"


def test_cross_venue_blocked_on_basis_risk():
    pair = _pair(0.40, 0.50, rules_match=False)      # rules don't match
    out = ArbitrageStrategy(ArbParams(min_edge=0.01)).on_tick(Context(cross_pairs=[pair]))
    assert out == [], "different resolution rules => basis risk, not arbitrage"


def test_cross_venue_no_arb_when_no_edge():
    # both legs near 0.50 -> YES_ask + NO_ask ~ 1.02 > 1, no locked edge
    pair = _pair(0.50, 0.50)
    out = ArbitrageStrategy(ArbParams(min_edge=0.01)).on_tick(Context(cross_pairs=[pair]))
    assert out == [], "no edge when the two venues agree near the middle"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} multi-venue tests passed.")
