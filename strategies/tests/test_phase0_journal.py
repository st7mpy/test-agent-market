#!/usr/bin/env python3
"""Venue-yield accounting tests for the Phase-0 journal.

Run: `cd strategies && python tests/test_phase0_journal.py`.

Covers the wedge (DIFFERENTIATION.md B): rebates + liquidity rewards are income,
and the Phase-0 gate is judged net of a venue-yield haircut.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phase0_journal import compute_summary  # noqa: E402


def _fill(market, token, side, price, shares, fee=0.0, gas=0.0, ts="2026-01-01T00:00:00"):
    return {"ts": ts, "market": market, "token": token, "side": side,
            "price": price, "shares": shares, "fee": fee, "gas": gas, "note": ""}


def _inc(kind, amount, ts="2026-01-01T00:00:00"):
    return {"ts": ts, "kind": kind, "amount": amount, "note": ""}


def test_venue_yield_sums_rebates_and_liquidity():
    j = {"fills": [_fill("m", "YES", "BUY", 0.5, 100)], "settlements": {},
         "income": [_inc("rebate", 12.0), _inc("liquidity_reward", 8.0), _inc("other", 3.0)]}
    s = compute_summary(j, haircut=0.5)
    assert s["rebate_income"] == 12.0
    assert s["liq_income"] == 8.0
    assert s["venue_yield"] == 20.0          # rebate + liquidity only
    assert s["other_income"] == 3.0
    assert s["total_income"] == 23.0


def test_haircut_only_discounts_venue_yield():
    # flat trade book (buy then sell same price, no fee) -> zero trade PnL
    j = {"fills": [_fill("m", "YES", "BUY", 0.50, 100, ts="2026-01-01T00:00:00"),
                   _fill("m", "YES", "SELL", 0.50, 100, ts="2026-01-02T00:00:00")],
         "settlements": {},
         "income": [_inc("rebate", 100.0), _inc("other", 10.0)]}
    s = compute_summary(j, haircut=0.5)
    assert abs(s["gross_pnl"]) < 1e-9, "flat round-trip has no trade PnL"
    # as earned: full income
    assert abs(s["net_pnl"] - 110.0) < 1e-9
    # haircut hits venue_yield (100 -> 50) but not other_income (10 stays)
    assert abs(s["net_pnl_haircut"] - 60.0) < 1e-9


def test_gate_uses_haircut_basis():
    # venue-yield is the only edge; a 100% haircut wipes it out -> gate fails on PnL
    fills = [_fill("m", "YES", "BUY", 0.50, 10, ts=f"2026-01-{d:02d}T00:00:00")
             for d in range(1, 15)]
    income = [_inc("rebate", 5.0, ts=f"2026-01-{d:02d}T00:00:00") for d in range(1, 15)]
    # close the position flat so trade PnL is ~0 and only yield remains
    fills += [_fill("m", "YES", "SELL", 0.50, 140, ts="2026-01-15T00:00:00")]
    j = {"fills": fills, "settlements": {}, "income": income}

    soft = compute_summary(j, haircut=0.0)     # keep all yield
    assert soft["net_pnl_haircut"] > 0
    hard = compute_summary(j, haircut=1.0)     # assume all yield vanishes
    assert hard["net_pnl_haircut"] <= 0
    assert hard["gate_pnl"] is False, "gate must fail when haircut wipes the only edge"


def test_backward_compatible_without_income_key():
    j = {"fills": [_fill("m", "YES", "BUY", 0.40, 100)], "settlements": {"m": "YES"}}
    s = compute_summary(j)                     # no 'income' key at all
    assert s["venue_yield"] == 0.0
    # bought 100 YES @ .40 = $40 cost, resolves YES -> $100 payout -> +$60 realized
    assert abs(s["gross_pnl"] - 60.0) < 1e-9


def test_directional_settlement_pnl():
    j = {"fills": [_fill("m", "NO", "BUY", 0.30, 100)], "settlements": {"m": "YES"}, "income": []}
    s = compute_summary(j)
    # bought NO @ .30 = $30 cost, market resolves YES -> NO pays 0 -> -$30
    assert abs(s["gross_pnl"] + 30.0) < 1e-9
    assert s["gate_pnl"] is False


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} venue-yield journal tests passed.")
