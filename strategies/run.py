#!/usr/bin/env python3
"""Config-driven strategy runner — the deployable unit.

    cd strategies
    python run.py --config ../deploy/config.example.json
    python run.py --config cfg.json --print-config     # show the resolved config

One JSON config declares everything a session needs: data source, market,
strategy + params, bankroll, risk limits, oracle-risk policy, and loop cadence.
The runner wires the same seams as `live.py` (VenueAdapter → Strategy → RiskGate →
PaperOMS, with reconcile-or-halt, ADR-011) and writes a machine-readable session
report on exit. Exit code 2 signals a kill-switch halt so a supervisor
(systemd/Docker/orchestrator) can alert instead of blindly restarting.

This is the artifact both deployment framings share (see deploy/README.md):
the platform runs it per-vault on hosted, sandboxed infra (the B-on-C model);
a power user can run the identical container against their own config.

Honesty note: execution is the PAPER broker in both modes — `mode=live` means
live *market data* with simulated fills. Real order placement (EIP-712 signing,
key custody) is deliberately absent from strategy-adjacent code (ADR-002); it
arrives platform-side with Phase 1's KMS-backed OMS.

Secrets never live in the config file: the Polymarket wallet address used for
position reconciliation is read from $POLYMARKET_ADDRESS.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from typing import Any, Dict

from predmkt import (
    ArbitrageStrategy, ArbParams,
    KellyEdgeStrategy, KellyParams,
    LongshotBiasStrategy, LongshotParams,
    MarketMakerStrategy, MMParams,
    OracleRiskModel,
    Portfolio,
    ThetaConvergenceStrategy, ThetaParams,
)
from predmkt.data import load_fixture
from predmkt.execution import PaperBroker, RiskGate, RiskLimits
from predmkt.venue import KalshiAdapter, PolymarketAdapter, ReplayAdapter, VenueAdapter
from live import run as run_loop

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_HALTED = 2       # kill-switch tripped (reconciliation breach) — do not auto-restart

DEFAULT_CONFIG: Dict[str, Any] = {
    "mode": "replay",                      # replay | live
    "venue": "polymarket",                 # live only: polymarket | kalshi
    "market": {"query": "election"},       # polymarket: query; kalshi: ticker
    "strategy": {"name": "mm", "params": {}},
    "bankroll": 100_000.0,
    "risk": {
        "max_position_shares": 5000.0,
        "max_order_notional": 10_000.0,
        "max_oracle_risk": None,           # set to gate on oracle risk (ADR-014)
    },
    "oracle": {"flags": {}, "overrides": {}},
    "loop": {"steps": 400, "reconcile_every": 25, "interval_s": 2.0},
    "report_path": "session_report.json",
}

# strategies runnable in the single-market loop; relation/cross-venue arb need a
# multi-market feed and run through their own harnesses (multivenue_demo.py)
STRATEGIES = ("mm", "kelly", "arb", "longshot", "theta")


def load_config(path: str) -> Dict[str, Any]:
    with open(path) as f:
        user = json.load(f)
    cfg: Dict[str, Any] = {}
    for key, default in DEFAULT_CONFIG.items():
        val = user.get(key, default)
        if isinstance(default, dict) and isinstance(val, dict):
            cfg[key] = {**default, **val}
        else:
            cfg[key] = val
    unknown = set(user) - set(DEFAULT_CONFIG)
    if unknown:
        raise ValueError(f"unknown config keys: {sorted(unknown)}")
    if cfg["strategy"].get("name") not in STRATEGIES:
        raise ValueError(f"strategy.name must be one of {STRATEGIES}")
    if cfg["mode"] not in ("replay", "live"):
        raise ValueError("mode must be 'replay' or 'live'")
    return cfg


def _params(cls, overrides: Dict[str, Any], **fixed):
    """Build a params dataclass from config overrides, rejecting unknown fields."""
    valid = {f.name for f in dataclasses.fields(cls)}
    unknown = set(overrides) - valid
    if unknown:
        raise ValueError(f"unknown {cls.__name__} fields: {sorted(unknown)}")
    return cls(**{**overrides, **fixed})


def build_strategy(cfg: Dict[str, Any], market_id: str, *,
                   oracle_model: OracleRiskModel | None = None):
    name = cfg["strategy"]["name"]
    overrides = dict(cfg["strategy"].get("params") or {})
    bankroll = float(cfg["bankroll"])
    if name == "mm":
        return MarketMakerStrategy(_params(MMParams, overrides, market_id=market_id))
    if name == "kelly":
        fair_value = overrides.pop("fair_value", "mean_reversion")
        reference_probs = overrides.pop("reference_probs", None)
        s = KellyEdgeStrategy(bankroll, _params(KellyParams, overrides),
                              reference_probs=reference_probs)
        if fair_value == "mean_reversion":
            s.fair_value_fn = s.mean_reversion
        elif fair_value != "reference":
            raise ValueError("kelly fair_value must be 'mean_reversion' or 'reference'")
        return s
    if name == "arb":
        return ArbitrageStrategy(_params(ArbParams, overrides))
    if name == "longshot":
        return LongshotBiasStrategy(bankroll, _params(LongshotParams, overrides),
                                    oracle_model=oracle_model)
    if name == "theta":
        return ThetaConvergenceStrategy(bankroll, _params(ThetaParams, overrides),
                                        oracle_model=oracle_model)
    raise ValueError(f"unknown strategy {name!r}")


def build_adapter(cfg: Dict[str, Any]) -> VenueAdapter:
    if cfg["mode"] == "replay":
        return ReplayAdapter(load_fixture(), market_id="replay", outcome="YES")
    interval = float(cfg["loop"]["interval_s"])
    if cfg["venue"] == "polymarket":
        return PolymarketAdapter(cfg["market"]["query"], poll_interval_s=interval,
                                 address=os.environ.get("POLYMARKET_ADDRESS"))
    if cfg["venue"] == "kalshi":
        return KalshiAdapter(cfg["market"]["ticker"], poll_interval_s=interval)
    raise ValueError(f"unknown venue {cfg['venue']!r}")


def build_risk(cfg: Dict[str, Any]) -> tuple[RiskGate, OracleRiskModel | None]:
    r = cfg["risk"]
    oracle_cfg = cfg["oracle"]
    model = None
    if oracle_cfg.get("flags") or oracle_cfg.get("overrides") or r.get("max_oracle_risk") is not None:
        model = OracleRiskModel(flags=oracle_cfg.get("flags") or {},
                                overrides=oracle_cfg.get("overrides") or {})
    limits = RiskLimits(
        max_position_shares=float(r["max_position_shares"]),
        max_order_notional=float(r["max_order_notional"]),
        max_oracle_risk=r.get("max_oracle_risk"),
    )
    return RiskGate(limits, oracle_model=model), model


def run_session(cfg: Dict[str, Any], *, verbose: bool = True) -> Dict[str, Any]:
    adapter = build_adapter(cfg)
    risk, oracle_model = build_risk(cfg)
    strategy = build_strategy(cfg, adapter.market_id, oracle_model=oracle_model)
    broker = PaperBroker(Portfolio(cash=float(cfg["bankroll"])))

    loop = cfg["loop"]
    out = run_loop(adapter, strategy, broker, risk,
                   steps=int(loop["steps"]),
                   reconcile_every=int(loop["reconcile_every"]),
                   live=(cfg["mode"] == "live"),
                   interval=float(loop["interval_s"]),
                   verbose=verbose)

    report = {
        "config": {k: v for k, v in cfg.items() if k != "report_path"},
        "market_id": adapter.market_id,
        "halted": out["halted"],
        "kill_switch": out["kill_switch"],
        "steps_run": out["steps_run"],
        "skipped_reconciliations": out["skipped_reconciliations"],
        "resolution": out["resolution"],
        "start_equity": float(cfg["bankroll"]),
        "final_equity": out["final_equity"],
        "return_pct": (out["final_equity"] / float(cfg["bankroll"]) - 1.0) * 100.0,
        "fills": broker.n_fills,
        "fees_paid": broker.fees_paid,
        "breaches": [dataclasses.asdict(d) for d in out["breach"]],
    }
    if cfg.get("report_path"):
        with open(cfg["report_path"], "w") as f:
            json.dump(report, f, indent=2, default=str)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Config-driven strategy runner")
    ap.add_argument("--config", required=True, help="path to session config JSON")
    ap.add_argument("--print-config", action="store_true",
                    help="print the resolved config and exit")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return EXIT_CONFIG
    if args.print_config:
        print(json.dumps(cfg, indent=2))
        return EXIT_OK

    report = run_session(cfg, verbose=not args.quiet)

    print("\n=== session report ===")
    for k in ("market_id", "steps_run", "halted", "kill_switch", "resolution",
              "final_equity", "return_pct", "fills", "fees_paid"):
        v = report[k]
        print(f"  {k:22s}: {v:,.2f}" if isinstance(v, float) else f"  {k:22s}: {v}")
    if cfg.get("report_path"):
        print(f"  report written        : {cfg['report_path']}")
    return EXIT_HALTED if report["halted"] else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
