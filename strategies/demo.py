#!/usr/bin/env python3
"""Runnable demo of the sample strategies.

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
    FlowTrade,
    KellyEdgeStrategy,
    KellyParams,
    LongshotBiasStrategy,
    MarketMakerStrategy,
    MarketRelation,
    MMParams,
    Portfolio,
    RelationArbStrategy,
    RelationKind,
    Side,
    SmartMoneyProvider,
    ThetaConvergenceStrategy,
    Token,
    Venue,
    score_wallets,
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
        time_to_resolution=100.0,
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
                                category="crypto", time_to_resolution=80.0)
    last = []
    for t, m in enumerate(series):
        m.time_to_resolution = float(len(series) - t)   # decay toward resolution
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


def demo_relation_arb() -> None:
    hr("4 · RELATION ARBITRAGE (logical consistency)")
    # "X wins presidency" implies "X wins nomination", yet presidency trades ABOVE
    # nomination — buy NO(presidency) + YES(nomination): min payoff $1 for < $1.
    pres = binary_market("x-presidency", 0.60, category="politics")
    nom = binary_market("x-nomination", 0.50, category="politics")
    rel = MarketRelation(RelationKind.IMPLIES, "x-presidency", "x-nomination",
                         verified=True)
    ctx = Context(markets={m.market_id: m for m in (pres, nom)}, relations=[rel])
    show(RelationArbStrategy().on_tick(ctx))


def demo_longshot_bias() -> None:
    hr("5 · FAVORITE-LONGSHOT BIAS HARVESTER")
    # a 5c longshot is empirically worth ~2c -> its 95c favorite is underpriced
    tail = binary_market("mkt-longshot", 0.05, category="sports")
    mid = binary_market("mkt-midrange", 0.50, category="sports")   # no bias here
    strat = LongshotBiasStrategy(bankroll=100_000.0)
    show(strat.on_tick(Context(markets={m.market_id: m for m in (tail, mid)})))


def demo_theta() -> None:
    hr("6 · RESOLUTION-CONVERGENCE (theta carry)")
    # a 95.5c favorite 10 periods from resolution annualizes far above the hurdle
    near = binary_market("mkt-near", 0.955, category="sports", time_to_resolution=10.0)
    far = binary_market("mkt-far", 0.955, category="sports", time_to_resolution=200.0)
    strat = ThetaConvergenceStrategy(bankroll=100_000.0)
    show(strat.on_tick(Context(markets={m.market_id: m for m in (near, far)})))


def demo_smart_money() -> None:
    hr("7 · SMART-MONEY FLOW SIGNAL")
    # score wallets on resolved history, then read their current positioning
    history = [FlowTrade("0xsharp", f"r{i}", Token.YES, Side.BUY, 0.60, 500)
               for i in range(40)]
    scores = score_wallets(history, {f"r{i}": 1 for i in range(40)})
    prov = SmartMoneyProvider(scores)
    prov.observe(FlowTrade("0xsharp", "mkt-flow", Token.YES, Side.BUY, 0.50, 20_000))
    m = binary_market("mkt-flow", 0.50, category="politics")
    s = prov.fair_value(m)
    print(f"  wallet 0xsharp: skill={scores['0xsharp'].skill:+.3f} "
          f"over {scores['0xsharp'].n_trades} resolved trades")
    print(f"  market mid 0.500 -> signal p={s.p:.3f} confidence={s.confidence:.2f}")
    print(f"  rationale: {s.rationale}")


if __name__ == "__main__":
    demo_arbitrage()
    demo_market_maker()
    demo_kelly()
    demo_relation_arb()
    demo_longshot_bias()
    demo_theta()
    demo_smart_money()
    print("\nAll seven sample strategies ran. See strategies/README.md for details.\n")
