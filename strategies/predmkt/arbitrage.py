"""Arbitrage strategy (clean-room).

Three near-risk-free sub-types, all driven by the identity that a *complete set*
(1 YES + 1 NO) is always worth exactly $1 at resolution:

1. Intra-market YES/NO:
     buy both legs when  ask_YES + ask_NO + fees < 1 - theta   (locked profit)
     mint & sell  when   bid_YES + bid_NO - fees > 1 + theta   (split $1 -> set, sell both)
2. Combinatorial / NegRisk (multi-outcome, exactly one resolves YES):
     buy one YES of each outcome when  sum(ask_YES_i) + fees < 1 - theta
3. Cross-venue (same event on two venues):
     buy YES on the cheaper-YES venue + NO on the cheaper-NO venue when the
     combined cost + fees < 1 - theta  AND  resolution rules genuinely match.

Technique references (read-only, not copied): Polymarket CTF split/merge and
NegRisk adapter mechanics (MIT-licensed docs in Polymarket/ctf-exchange and
Polymarket/neg-risk-ctf-adapter); arXiv:2508.03474 "Arbitrage in Prediction
Markets". This is an original implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .base import Context, Strategy, depth_capped_size
from .fees import polymarket_taker_fee_per_share
from .types import (
    BinaryMarket,
    Intent,
    LimitOrder,
    Side,
    Split,
    TIF,
    Token,
)


@dataclass
class ArbParams:
    min_edge: float = 0.015          # theta: min net edge per share after fees (1.5c)
    slippage_buffer: float = 0.005   # per-leg price cushion
    depth_fraction: float = 0.30     # take at most 30% of fillable top-of-book depth
    max_shares: float = 5000.0       # hard per-signal size cap
    max_event_legs: int = 12         # bound combinatorial execution risk


class ArbitrageStrategy(Strategy):
    name = "arbitrage"

    def __init__(self, params: ArbParams | None = None) -> None:
        self.p = params or ArbParams()

    # ------------------------------------------------------------------ #
    def on_tick(self, ctx: Context) -> List[Intent]:
        intents: List[Intent] = []
        for m in ctx.markets.values():
            intents += self._intra_market(m)
        for ev in ctx.events.values():
            intents += self._combinatorial(ev)
        for pair in ctx.cross_pairs:
            intents += self._cross_venue(pair)
        return intents

    # --- 1. intra-market YES/NO ---------------------------------------- #
    def _intra_market(self, m: BinaryMarket) -> List[Intent]:
        ay, an = m.yes_book.best_ask(), m.no_book.best_ask()
        by, bn = m.yes_book.best_bid(), m.no_book.best_bid()
        out: List[Intent] = []

        if ay is not None and an is not None:
            fees = (polymarket_taker_fee_per_share(ay, m.category)
                    + polymarket_taker_fee_per_share(an, m.category))
            edge = 1.0 - ay - an - fees
            if edge > self.p.min_edge:
                size = min(
                    depth_capped_size(m.yes_book, Side.BUY, ay + self.p.slippage_buffer,
                                      self.p.depth_fraction, self.p.max_shares),
                    depth_capped_size(m.no_book, Side.BUY, an + self.p.slippage_buffer,
                                      self.p.depth_fraction, self.p.max_shares),
                )
                if size > 0:
                    note = f"intra buy-both edge={edge:.4f}/sh"
                    out.append(LimitOrder(note, m.market_id, Token.YES, Side.BUY,
                                          ay + self.p.slippage_buffer, size, TIF.FOK))
                    out.append(LimitOrder(note, m.market_id, Token.NO, Side.BUY,
                                          an + self.p.slippage_buffer, size, TIF.FOK))

        if by is not None and bn is not None:
            fees = (polymarket_taker_fee_per_share(by, m.category)
                    + polymarket_taker_fee_per_share(bn, m.category))
            edge = by + bn - 1.0 - fees
            if edge > self.p.min_edge:
                size = min(
                    depth_capped_size(m.yes_book, Side.SELL, by - self.p.slippage_buffer,
                                      self.p.depth_fraction, self.p.max_shares),
                    depth_capped_size(m.no_book, Side.SELL, bn - self.p.slippage_buffer,
                                      self.p.depth_fraction, self.p.max_shares),
                )
                if size > 0:
                    note = f"intra mint+sell edge={edge:.4f}/sh"
                    # split $size of USDC into a complete set, then sell both legs
                    out.append(Split(note, m.market_id, usdc=size))
                    out.append(LimitOrder(note, m.market_id, Token.YES, Side.SELL,
                                          by - self.p.slippage_buffer, size, TIF.FOK))
                    out.append(LimitOrder(note, m.market_id, Token.NO, Side.SELL,
                                          bn - self.p.slippage_buffer, size, TIF.FOK))
        return out

    # --- 2. combinatorial / NegRisk ------------------------------------ #
    def _combinatorial(self, ev) -> List[Intent]:
        legs = ev.markets
        if not legs or len(legs) > self.p.max_event_legs:
            return []
        asks, fees, ok = [], 0.0, True
        for m in legs:
            a = m.yes_book.best_ask()
            if a is None:
                ok = False
                break
            asks.append((m, a))
            fees += polymarket_taker_fee_per_share(a, m.category)
        if not ok:
            return []
        total = sum(a for _, a in asks) + fees
        edge = 1.0 - total
        if edge <= self.p.min_edge:
            return []
        # size = min fillable depth across all legs (basket must fill together)
        size = self.p.max_shares
        for m, a in asks:
            size = min(size, depth_capped_size(m.yes_book, Side.BUY,
                                               a + self.p.slippage_buffer,
                                               self.p.depth_fraction, self.p.max_shares))
        if size <= 0:
            return []
        note = f"negrisk basket n={len(legs)} edge={edge:.4f}/sh"
        return [
            LimitOrder(note, m.market_id, Token.YES, Side.BUY,
                       a + self.p.slippage_buffer, size, TIF.FOK)
            for m, a in asks
        ]

    # --- 3. cross-venue ------------------------------------------------- #
    def _cross_venue(self, pair) -> List[Intent]:
        if not pair.resolution_rules_match:
            return []  # different settlement => basis risk, not arbitrage
        a, b = pair.market_a, pair.market_b
        ay_a, ay_b = a.yes_book.best_ask(), b.yes_book.best_ask()
        an_a, an_b = a.no_book.best_ask(), b.no_book.best_ask()
        if None in (ay_a, ay_b, an_a, an_b):
            return []
        # cheapest YES and cheapest NO across the two venues
        yes_m, yes_px = (a, ay_a) if ay_a <= ay_b else (b, ay_b)
        no_m, no_px = (a, an_a) if an_a <= an_b else (b, an_b)
        if yes_m is no_m:
            return []  # both legs same venue -> that's intra-market, handled elsewhere
        fees = (polymarket_taker_fee_per_share(yes_px, yes_m.category)
                + polymarket_taker_fee_per_share(no_px, no_m.category))
        edge = 1.0 - yes_px - no_px - fees
        if edge <= self.p.min_edge:
            return []
        size = min(
            depth_capped_size(yes_m.yes_book, Side.BUY, yes_px + self.p.slippage_buffer,
                              self.p.depth_fraction, self.p.max_shares),
            depth_capped_size(no_m.no_book, Side.BUY, no_px + self.p.slippage_buffer,
                              self.p.depth_fraction, self.p.max_shares),
        )
        if size <= 0:
            return []
        note = (f"cross-venue YES@{yes_m.venue.value} NO@{no_m.venue.value} "
                f"edge={edge:.4f}/sh")
        return [
            LimitOrder(note, yes_m.market_id, Token.YES, Side.BUY,
                       yes_px + self.p.slippage_buffer, size, TIF.IOC),
            LimitOrder(note, no_m.market_id, Token.NO, Side.BUY,
                       no_px + self.p.slippage_buffer, size, TIF.IOC),
        ]
