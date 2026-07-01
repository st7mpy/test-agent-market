#!/usr/bin/env python3
"""Tests for cross-market relation arbitrage (implication/exclusivity/exhaustivity).
Run: `cd strategies && python tests/test_relation_arb.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    Context, MarketRelation, RelationArbStrategy, RelationKind, Side, TIF, Token,
)
from predmkt.sim import binary_market  # noqa: E402


def _ctx(markets, relations):
    return Context(markets={m.market_id: m for m in markets}, relations=relations)


# --- IMPLIES: A => B requires P(A) <= P(B) ----------------------------------- #
def test_implies_violation_trades_no_a_yes_b():
    a = binary_market("A", 0.60)                 # P(A) = 0.60
    b = binary_market("B", 0.50)                 # P(B) = 0.50 < P(A): violation
    rel = MarketRelation(RelationKind.IMPLIES, "A", "B", verified=True)
    intents = RelationArbStrategy().on_tick(_ctx([a, b], [rel]))
    assert len(intents) == 2
    by_market = {i.market_id: i for i in intents}
    assert by_market["A"].token == Token.NO and by_market["A"].side == Side.BUY
    assert by_market["B"].token == Token.YES and by_market["B"].side == Side.BUY
    assert all(i.tif == TIF.FOK for i in intents)        # basket fills together or not at all
    assert by_market["A"].size == by_market["B"].size


def test_implies_consistent_prices_do_not_trade():
    a = binary_market("A", 0.40)
    b = binary_market("B", 0.60)                 # P(A) <= P(B): consistent
    rel = MarketRelation(RelationKind.IMPLIES, "A", "B", verified=True)
    assert RelationArbStrategy().on_tick(_ctx([a, b], [rel])) == []


def test_unverified_relation_is_refused():
    """An asserted-but-unverified constraint is basis risk, not arbitrage."""
    a = binary_market("A", 0.60)
    b = binary_market("B", 0.50)
    rel = MarketRelation(RelationKind.IMPLIES, "A", "B", verified=False)
    assert RelationArbStrategy().on_tick(_ctx([a, b], [rel])) == []


# --- EXCLUSIVE: P(A) + P(B) <= 1 --------------------------------------------- #
def test_exclusive_violation_buys_both_nos():
    a = binary_market("A", 0.60)
    b = binary_market("B", 0.55)                 # sum 1.15 > 1: violation
    rel = MarketRelation(RelationKind.EXCLUSIVE, "A", "B", verified=True)
    intents = RelationArbStrategy().on_tick(_ctx([a, b], [rel]))
    assert len(intents) == 2
    assert all(i.token == Token.NO and i.side == Side.BUY for i in intents)


# --- EXHAUSTIVE: P(A) + P(B) >= 1 -------------------------------------------- #
def test_exhaustive_violation_buys_both_yeses():
    a = binary_market("A", 0.40)
    b = binary_market("B", 0.45)                 # sum 0.85 < 1: violation
    rel = MarketRelation(RelationKind.EXHAUSTIVE, "A", "B", verified=True)
    intents = RelationArbStrategy().on_tick(_ctx([a, b], [rel]))
    assert len(intents) == 2
    assert all(i.token == Token.YES and i.side == Side.BUY for i in intents)


def test_exhaustive_consistent_prices_do_not_trade():
    a = binary_market("A", 0.60)
    b = binary_market("B", 0.55)                 # sum >= 1: consistent
    rel = MarketRelation(RelationKind.EXHAUSTIVE, "A", "B", verified=True)
    assert RelationArbStrategy().on_tick(_ctx([a, b], [rel])) == []


# --- sizing + robustness ------------------------------------------------------ #
def test_size_capped_by_thinner_leg():
    a = binary_market("A", 0.60, size=200.0)     # thin leg
    b = binary_market("B", 0.50, size=10_000.0)
    rel = MarketRelation(RelationKind.IMPLIES, "A", "B", verified=True)
    intents = RelationArbStrategy().on_tick(_ctx([a, b], [rel]))
    assert len(intents) == 2
    # depth_fraction 0.30 of the 200-share leg
    assert abs(intents[0].size - 60.0) < 1e-9
    assert intents[0].size == intents[1].size


def test_missing_market_is_skipped():
    a = binary_market("A", 0.60)
    rel = MarketRelation(RelationKind.IMPLIES, "A", "B", verified=True)
    assert RelationArbStrategy().on_tick(_ctx([a], [rel])) == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} relation-arb tests passed.")
