#!/usr/bin/env python3
"""Tests for the config-driven strategy runner (the deployable unit).
Run: `cd strategies && python tests/test_runner.py`.
"""
import contextlib
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run as runner  # noqa: E402
from predmkt import (  # noqa: E402
    Context, KellyEdgeStrategy, LongshotBiasStrategy, MarketMakerStrategy,
    OracleRiskModel, ThetaConvergenceStrategy,
)
from predmkt.sim import binary_market  # noqa: E402


def _write_cfg(d):
    f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(d, f)
    f.close()
    return f.name


def _cfg(**over):
    base = {"strategy": {"name": "mm", "params": {}}}
    base.update(over)
    return runner.load_config(_write_cfg(base))


# --- config loading ------------------------------------------------------------ #
def test_defaults_are_merged():
    cfg = _cfg()
    assert cfg["mode"] == "replay"
    assert cfg["risk"]["max_order_notional"] == 10_000.0
    assert cfg["loop"]["steps"] == 400


def test_partial_nested_override_keeps_other_defaults():
    cfg = _cfg(risk={"max_order_notional": 500})
    assert cfg["risk"]["max_order_notional"] == 500
    assert cfg["risk"]["max_position_shares"] == 5000.0     # untouched default


def test_unknown_top_level_key_rejected():
    try:
        _cfg(bogus=1)
    except ValueError as e:
        assert "bogus" in str(e)
    else:
        raise AssertionError("unknown key should be rejected")


def test_unknown_strategy_rejected():
    try:
        _cfg(strategy={"name": "moon"})
    except ValueError:
        pass
    else:
        raise AssertionError("unknown strategy should be rejected")


# --- strategy factory ------------------------------------------------------------ #
def test_factory_applies_param_overrides():
    cfg = _cfg(strategy={"name": "theta", "params": {"hurdle_apr": 0.99}})
    s = runner.build_strategy(cfg, "m")
    assert isinstance(s, ThetaConvergenceStrategy)
    assert s.p.hurdle_apr == 0.99


def test_factory_rejects_unknown_params():
    cfg = _cfg(strategy={"name": "longshot", "params": {"betta": 2.0}})
    try:
        runner.build_strategy(cfg, "m")
    except ValueError as e:
        assert "betta" in str(e)
    else:
        raise AssertionError("typo'd param should fail fast")


def test_factory_builds_each_strategy():
    for name, cls in (("mm", MarketMakerStrategy), ("kelly", KellyEdgeStrategy),
                      ("longshot", LongshotBiasStrategy), ("theta", ThetaConvergenceStrategy)):
        cfg = _cfg(strategy={"name": name, "params": {}})
        assert isinstance(runner.build_strategy(cfg, "m"), cls)


def test_oracle_model_threads_into_gate_and_strategy():
    cfg = _cfg(risk={"max_oracle_risk": 0.5}, oracle={"overrides": {"m": 0.9}})
    gate, model = runner.build_risk(cfg)
    assert isinstance(model, OracleRiskModel)
    assert gate.oracle_model is model
    cfg2 = _cfg(strategy={"name": "theta", "params": {}},
                risk={"max_oracle_risk": 0.5}, oracle={"overrides": {"m": 0.9}})
    _, model2 = runner.build_risk(cfg2)
    strat2 = runner.build_strategy(cfg2, "m", oracle_model=model2)
    assert strat2.oracle_model is model2


# --- oracle-gated strategies never run ungated (ADR-014) --------------------------- #
def test_gated_strategies_get_default_oracle_model():
    # no oracle config anywhere -> theta/longshot still get a category-based model
    for name in runner.ORACLE_GATED:
        cfg = _cfg(strategy={"name": name, "params": {}})
        s = runner.build_strategy(cfg, "m")
        assert isinstance(s.oracle_model, OracleRiskModel), f"{name} must never be ungated"


def test_default_oracle_gate_blocks_risky_market():
    # identical carry setups; only the category (=> default oracle score) differs.
    # crypto base 0.10 <= theta's 0.25 -> tradeable; world base 0.55 > 0.25 -> refused.
    cfg = _cfg(strategy={"name": "theta", "params": {}})
    s = runner.build_strategy(cfg, "m")
    safe = binary_market("safe", 0.90, category="crypto", time_to_resolution=5.0)
    risky = binary_market("risky", 0.90, category="world", time_to_resolution=5.0)
    assert s.on_tick(Context(markets={"safe": safe})), "low-oracle-risk carry should trade"
    assert s.on_tick(Context(markets={"risky": risky})) == [], \
        "default gate must refuse a dispute-prone (world) market"


def test_default_gate_note_emitted():
    with tempfile.TemporaryDirectory() as d:
        cfg = _cfg(strategy={"name": "theta", "params": {}},
                   loop={"steps": 5, "reconcile_every": 100},
                   report_path=os.path.join(d, "r.json"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            runner.run_session(cfg, verbose=False)
        assert "default OracleRiskModel" in err.getvalue(), \
            "operator note must appear even in quiet mode"


# --- end-to-end replay session ----------------------------------------------------- #
def test_replay_session_produces_report():
    with tempfile.TemporaryDirectory() as d:
        report_path = os.path.join(d, "report.json")
        cfg = _cfg(strategy={"name": "mm", "params": {"quote_size": 100}},
                   loop={"steps": 500, "reconcile_every": 20},   # > fixture length (400)
                   report_path=report_path)
        report = runner.run_session(cfg, verbose=False)
        assert report["steps_run"] > 0
        assert report["halted"] is False and report["kill_switch"] is False
        assert report["resolution"] == "YES"                 # exhausted fixture resolves YES
        assert abs(report["return_pct"]) < 50                # sane paper number
        with open(report_path) as f:
            on_disk = json.load(f)
        assert on_disk["market_id"] == "replay"
        assert on_disk["breaches"] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} runner tests passed.")
