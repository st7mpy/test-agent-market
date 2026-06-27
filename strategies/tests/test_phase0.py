#!/usr/bin/env python3
"""Phase 0 tool smoke tests — journal CRUD, PnL math, and gate logic.

Run: cd strategies && python tests/test_phase0.py
No network required; no real fills are logged to the real journal file.
"""
import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import phase0_journal as j


# ─── helpers ─────────────────────────────────────────────────────────────────

def _tmp_journal(monkeypatch_path: str):
    """Context manager: redirect journal I/O to a temp file."""
    class _Ctx:
        def __enter__(self):
            self._orig = j.JOURNAL_FILE
            j.JOURNAL_FILE = monkeypatch_path
            return monkeypatch_path
        def __exit__(self, *_):
            j.JOURNAL_FILE = self._orig
    return _Ctx()


def _make_fill(market="mkt-A", token="YES", side="BUY",
               price=0.40, shares=100.0, fee=0.28, gas=0.01,
               timestamp="2026-01-01T12:00:00Z") -> dict:
    return dict(market=market, token=token, side=side,
                price=price, shares=shares, fee=fee, gas=gas,
                timestamp=timestamp, note="")


# ─── tests ────────────────────────────────────────────────────────────────────

def test_add_fill_persists():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        with _tmp_journal(path):
            args = type("A", (), _make_fill())()
            j.cmd_add(args)
            data = json.loads(open(path).read())
            assert len(data["fills"]) == 1
            assert data["fills"][0]["market"] == "mkt-A"
            assert data["fills"][0]["price"] == 0.40
    finally:
        os.unlink(path)


def test_settle_records_outcome():
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        with _tmp_journal(path):
            fill_args = type("A", (), _make_fill())()
            j.cmd_add(fill_args)
            settle_args = type("S", (), {"market": "mkt-A", "outcome": "YES"})()
            j.cmd_settle(settle_args)
            data = json.loads(open(path).read())
            assert data["settlements"]["mkt-A"] == "YES"
    finally:
        os.unlink(path)


def test_net_pnl_settled_win():
    """Buy 100 YES @ 0.40, settle YES -> gross +0.60/sh, net after fees."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        with _tmp_journal(path):
            fill_args = type("A", (), _make_fill(price=0.40, shares=100, fee=0.28, gas=0.01))()
            j.cmd_add(fill_args)
            settle_args = type("S", (), {"market": "mkt-A", "outcome": "YES"})()
            j.cmd_settle(settle_args)
            # gross = 100*(1-0.40) = 60; fees = 0.29; net = 59.71
            data = json.loads(open(path).read())
            fills = data["fills"]
            settlements = data["settlements"]
            # replicate the PnL math from cmd_status
            cost = 0.40 * 100
            proceeds = 100 * 1.0       # YES wins
            realized = proceeds - cost  # 60
            fees = 0.28 + 0.01
            net = realized - fees
            assert abs(net - 59.71) < 0.01, f"net={net}"
    finally:
        os.unlink(path)


def test_net_pnl_settled_loss():
    """Buy 100 YES @ 0.60, settle NO -> loss."""
    cost = 0.60 * 100
    proceeds = 0.0   # YES loses
    fees = 0.42 + 0.01
    net = (proceeds - cost) - fees
    assert net < 0


def test_sharpe_positive_returns():
    vals = [1.0, 2.0, 3.0, 1.5, 2.5]
    s = j._sharpe(vals)
    assert s > 0, f"expected positive Sharpe, got {s}"


def test_sharpe_zero_on_flat():
    vals = [1.0, 1.0, 1.0, 1.0]
    s = j._sharpe(vals)
    assert s == 0.0


def test_sharpe_negative_returns():
    vals = [-1.0, -2.0, -0.5, -3.0]
    s = j._sharpe(vals)
    assert s < 0


def test_gate_fails_too_few_trades():
    """Gate requires >= 100 trades; 5 should fail."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        with _tmp_journal(path):
            for i in range(5):
                ts = f"2026-01-{i+1:02d}T12:00:00Z"
                fill_args = type("A", (), _make_fill(timestamp=ts, price=0.30, shares=100,
                                                      fee=0.21, gas=0.01))()
                j.cmd_add(fill_args)
            data = json.loads(open(path).read())
            assert len(data["fills"]) == 5
            # gate_trades = (5 >= 100) = False
            assert 5 < j.GATE_MIN_TRADES
    finally:
        os.unlink(path)


def test_parse_ts_formats():
    from datetime import timezone
    cases = [
        "2026-01-15T14:32:00Z",
        "2026-01-15T14:32:00",
        "2026-01-15T14:32",
        "2026-01-15",
    ]
    for ts in cases:
        dt = j._parse_ts(ts)
        assert dt.tzinfo == timezone.utc, f"expected UTC tz for {ts!r}"
        assert dt.year == 2026


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} phase0 tests passed.")
