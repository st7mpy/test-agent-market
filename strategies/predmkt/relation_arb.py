"""Relation arbitrage (clean-room) — logical-consistency violations across markets.

Related markets are constrained by logic, not just by the complete-set identity
that drives `arbitrage.py`. For an asserted `MarketRelation` between markets A
and B (A = "market_a resolves YES"):

  IMPLIES     A => B                =>  P(A) <= P(B)
              violation trade: buy NO(A) + YES(B).
              If A happens, B must too: payoff 1 (YES(B)) + 0 (NO(A)) = 1.
              If neither happens:          1 (NO(A))            = 1.
              If only B happens:           1 + 1                = 2.
              Minimum payoff is $1, so cost + fees < 1 - theta locks >= theta.

  EXCLUSIVE   not (A and B)         =>  P(A) + P(B) <= 1
              violation trade: buy NO(A) + NO(B). At most one YES resolves,
              so at least one NO pays: minimum payoff $1.

  EXHAUSTIVE  A or B                =>  P(A) + P(B) >= 1
              violation trade: buy YES(A) + YES(B). At least one resolves YES:
              minimum payoff $1.

All three reduce to the same shape: a two-leg basket whose minimum payoff is $1
bought for less than $1 net of fees. The upside beyond $1 (when the "free" leg
also pays) is kept but never counted in the edge.

The constraint itself cannot be derived from order-book data — resolution wording
decides whether an implication truly holds — so `MarketRelation.verified` is an
asserted flag (default False) and unverified relations are refused, mirroring
`CrossVenuePair.resolution_rules_match` (ADR-016).

Technique references (read-only, not copied): arXiv:2508.03474 "Arbitrage in
Prediction Markets" (logical-dependency mispricings on Polymarket). Original
implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .base import Context, Strategy, depth_capped_size
from .fees import taker_fee_per_share
from .types import (
    BinaryMarket,
    Intent,
    LimitOrder,
    MarketRelation,
    RelationKind,
    Side,
    TIF,
    Token,
)


@dataclass
class RelationArbParams:
    min_edge: float = 0.015          # theta: min net edge per share after fees
    slippage_buffer: float = 0.005   # per-leg price cushion
    depth_fraction: float = 0.30     # take at most 30% of fillable top-of-book depth
    max_shares: float = 5000.0       # hard per-signal size cap


# token to buy on each leg, per relation kind: (token_on_A, token_on_B)
_LEGS = {
    RelationKind.IMPLIES: (Token.NO, Token.YES),
    RelationKind.EXCLUSIVE: (Token.NO, Token.NO),
    RelationKind.EXHAUSTIVE: (Token.YES, Token.YES),
}


class RelationArbStrategy(Strategy):
    name = "relation_arb"

    def __init__(self, params: RelationArbParams | None = None) -> None:
        self.p = params or RelationArbParams()

    def on_tick(self, ctx: Context) -> List[Intent]:
        intents: List[Intent] = []
        for rel in ctx.relations:
            intents += self._check(rel, ctx)
        return intents

    # ------------------------------------------------------------------ #
    def _check(self, rel: MarketRelation, ctx: Context) -> List[Intent]:
        if not rel.verified:
            return []            # unverified constraint = basis risk, not arbitrage
        ma = ctx.markets.get(rel.market_a_id)
        mb = ctx.markets.get(rel.market_b_id)
        if ma is None or mb is None:
            return []
        tok_a, tok_b = _LEGS[rel.kind]
        leg_a = self._executable(ma, tok_a)
        leg_b = self._executable(mb, tok_b)
        if leg_a is None or leg_b is None:
            return []
        ask_a, ask_b = leg_a, leg_b

        fees = (taker_fee_per_share(ma.venue, ask_a, ma.category)
                + taker_fee_per_share(mb.venue, ask_b, mb.category))
        edge = 1.0 - ask_a - ask_b - fees
        if edge <= self.p.min_edge:
            return []

        # basket must fill together: size to the thinner leg
        size = min(
            depth_capped_size(ma.book(tok_a), Side.BUY, ask_a + self.p.slippage_buffer,
                              self.p.depth_fraction, self.p.max_shares),
            depth_capped_size(mb.book(tok_b), Side.BUY, ask_b + self.p.slippage_buffer,
                              self.p.depth_fraction, self.p.max_shares),
        )
        if size <= 0:
            return []
        note = f"relation {rel.kind.value} edge={edge:.4f}/sh"
        return [
            LimitOrder(note, ma.market_id, tok_a, Side.BUY,
                       ask_a + self.p.slippage_buffer, size, TIF.FOK),
            LimitOrder(note, mb.market_id, tok_b, Side.BUY,
                       ask_b + self.p.slippage_buffer, size, TIF.FOK),
        ]

    @staticmethod
    def _executable(m: BinaryMarket, token: Token) -> Optional[float]:
        return m.book(token).best_ask()
