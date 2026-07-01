#!/usr/bin/env python3
"""Tests for the config-driven strategy runner (the deployable unit).
Run: `cd strategies && python tests/test_runner.py`.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run as runner  # noqa: E402
from predmkt import (  # noqa: E402
    KellyEdgeStrategy, LongshotBiasStrategy, MarketMakerStrategy, OracleRiskModel,
    ThetaConvergenceStrategy,
)


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
