#!/usr/bin/env python3
"""Demo multi-venue (D): a cross-venue arb across two (offline) venues.

    cd strategies
    python multivenue_demo.py

Builds a Polymarket replay venue (YES cheap) and a Kalshi replay venue (NO cheap)
for the same event, aggregates them with CrossVenueFeed, and runs the arbitrage
strategy — which buys the cheap YES on one venue and the cheap NO on the other,
priced with each venue's OWN fee model. No network: replay adapters stand in for
the live PolymarketAdapter / KalshiAdapter.
"""
from __future__ import annotations

from predmkt import (
    ArbitrageStrategy, ArbParams, Context, CrossVenueFeed, ReplayAdapter, Venue,
    kalshi_fee_per_share, polymarket_taker_fee_per_share,
)


def main() -> None:
    poly = ReplayAdapter([(0, 0.40)], market_id="PRES-2028@polymarket",
                         venue=Venue.POLYMARKET, depth=5000.0)
    kalshi = ReplayAdapter([(0, 0.50)], market_id="PRES-2028@kalshi",
                           venue=Venue.KALSHI, depth=5000.0)

    feed = CrossVenueFeed(poly, kalshi, resolution_rules_match=True)
    pair = feed.fetch_pair()

    print("=" * 64)
    print("  MULTI-VENUE (D) — cross-venue arbitrage demo")
    print("=" * 64)
    print(f"  venue A: {pair.market_a.market_id}  YES ask {pair.market_a.yes_book.best_ask():.3f}"
          f"  NO ask {pair.market_a.no_book.best_ask():.3f}  ({pair.market_a.venue.value})")
    print(f"  venue B: {pair.market_b.market_id}  YES ask {pair.market_b.yes_book.best_ask():.3f}"
          f"  NO ask {pair.market_b.no_book.best_ask():.3f}  ({pair.market_b.venue.value})")
    print(f"  resolution rules asserted to match: {pair.resolution_rules_match}")
    print(f"  per-share fee @0.40: polymarket {polymarket_taker_fee_per_share(0.40, 'politics'):.4f}"
          f"  vs kalshi {kalshi_fee_per_share(0.40):.4f}  (priced per venue)")
    print()

    intents = ArbitrageStrategy(ArbParams(min_edge=0.01)).on_tick(Context(cross_pairs=[pair]))
    if not intents:
        print("  no cross-venue edge.")
    else:
        print("  cross-venue intents emitted:")
        for it in intents:
            print(f"    BUY {it.size:>6.0f} {it.token.value:<3} @ {it.price:.3f}  on {it.market_id}")
        print(f"\n  {intents[0].note}")
    print()
    print("  Read: buy the cheap YES on one venue + the cheap NO on the other; the")
    print("  complete set pays $1 at resolution, so locking it below $1 (net of EACH")
    print("  venue's fee) is the arb — but only if the two markets truly resolve alike.\n")


if __name__ == "__main__":
    main()
