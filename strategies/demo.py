#!/usr/bin/env python3
"""Runnable demo of the three sample strategies.

    cd strategies && python demo.py

Builds synthetic scenarios offline (no network, no dependencies) and prints the
intents each strategy emits, so you can see the decision logic working.
"""
from __future__ import annotations

from predmkt import (
    ArbitrageStrategy,
    BinaryMarket,
    Context,
    CrossVenuePair,
    Event,
    Fill,
    KellyEdgeStrategy,
    KellyParams,
    MarketMakerStrategy,
    MMParams,
    Portfolio,
    Side,
    Token,
    Venue,
)
from predmkt.sim import binary_market, book, random_walk_market


def hr(title: str) -> None:
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def show(intents) -> None:
    if not intents:
        print("  (no intents — no edge)")
    for i in intents:
        print(f"  · {type(i).__name__:11s} {i.note}")
        for f in ("market_id", "token", "side", "price", "size", "usdc", "shares"):
            v = getattr(i, f, None)
            if v not in (None, "", 0, 0.0):
                print(f"        {f}={v if not isinstance(v,float) else round(v,4)}")


# --------------------------------------------------------------------------- #
def demo_arbitrage() -> None:
    hr("1 · ARBITRAGE")
    strat = ArbitrageStrategy()

    # (a) intra-market: independently-quoted books where YES ask 0.47 + NO ask 0.475
    #     = 0.945 < 1  -> buy both legs; ~5.5c/share gross, ~3.5c net after fees
    m = BinaryMarket(
        market_id="mkt-intra", category="politics",
        yes_book=book(bids=[(0.46, 800)], asks=[(0.47, 800)]),
        no_book=book(bids=[(0.465, 800)], asks=[(0.475, 800)]),
        seconds_to_resolution=86400.0,
    )
    # (b) NegRisk event: three exclusive outcomes whose YES asks sum to ~0.95
    ev = Event("evt-1", [
        binary_market("cand-A", 0.40, category="politics"),
        binary_market("cand-B", 0.345, category="politics"),
        binary_market("cand-C", 0.175, category="politics"),
    ])
    # (c) cross-venue: same event cheaper YES on Polymarket, cheaper NO on Kalshi
    poly = binary_market("evt-x@poly", 0.44, category="politics", venue=Venue.POLYMARKET)
    kal = binary_market("evt-x@kalshi", 0.50, category="politics", venue=Venue.KALSHI)
    pair = CrossVenuePair(poly, kal, resolution_rules_match=True)

    ctx = Context(
        markets={m.market_id: m},
        events={ev.event_id: ev},
        cross_pairs=[pair],
    )
    show(strat.on_tick(ctx))


def demo_market_maker() -> None:
    hr("2 · MARKET MAKER (Avellaneda-Stoikov)")
    mm = MarketMakerStrategy(MMParams(market_id="mkt-mm", gamma=0.3, k=1.5,
                                      quote_size=200, max_inventory=1000))
    series = random_walk_market("mkt-mm", start=0.50, sigma=0.004, steps=80,
                                category="crypto", seconds_to_resolution=3600.0)
    last = []
    for t, m in enumerate(series):
        ctx = Context(now=float(t), markets={m.market_id: m})
        intents = mm.on_tick(ctx)
        # toy fill model: assume the resting bid fills when price ticks down, ask when up
        if t > 0 and intents:
            prev_mid = series[t - 1].yes_book.mid()
            cur_mid = m.yes_book.mid()
            for i in intents:
                if getattr(i, "side", None) == Side.BUY and cur_mid < prev_mid:
                    mm.on_fill(Fill(m.market_id, Token.YES, Side.BUY, i.price, i.size))
                elif getattr(i, "side", None) == Side.SELL and cur_mid > prev_mid:
                    mm.on_fill(Fill(m.market_id, Token.YES, Side.SELL, i.price, i.size))
        last = intents
    print(f"  fed {len(series)} ticks; final inventory q = {mm.q:.0f} shares")
    print("  last quotes:")
    show(last)


def demo_kelly() -> None:
    hr("3 · FORECAST-EDGE + FRACTIONAL KELLY")
    # market trades YES at ~0.40; our reference model says fair prob = 0.55 -> edge
    m_edge = binary_market("mkt-edge", yes_mid=0.40, spread=0.01, category="sports")
    # a second market with no edge (fair == price) -> no intent
    m_noedge = binary_market("mkt-fair", yes_mid=0.60, spread=0.01, category="sports")
    strat = KellyEdgeStrategy(
        bankroll=100_000.0,
        params=KellyParams(kelly_fraction=0.25, min_edge=0.03),
        reference_probs={"mkt-edge": 0.55, "mkt-fair": 0.605},
    )
    ctx = Context(
        markets={m_edge.market_id: m_edge, m_noedge.market_id: m_noedge},
        portfolio=Portfolio(cash=100_000.0),
    )
    show(strat.on_tick(ctx))


if __name__ == "__main__":
    demo_arbitrage()
    demo_market_maker()
    demo_kelly()
    print("\nAll three sample strategies ran. See strategies/README.md for details.\n")
