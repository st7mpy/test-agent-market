#!/usr/bin/env python3
"""Demo the signal layer (F): score an off-hot-path research agent against the market.

    cd strategies
    python signal_demo.py

Builds a synthetic set of *resolved* markets where the market price is noisy and an
"informed agent" is less noisy, then runs the validation harness (ADR-013): Brier
score, Brier skill vs the market-implied null model, calibration curve, and the
trustworthy verdict that gates whether the agent may size capital.

Deterministic (fixed seed). No network, no model call — the agent is simulated so the
mechanics are visible; in production the agent is an LLM behind the same SignalProvider.
"""
from __future__ import annotations

import random

from predmkt import ExternalPriorProvider, MarketImpliedProvider, evaluate_provider
from predmkt.sim import binary_market


def build_resolved_set(n: int = 1500, seed: int = 7):
    rng = random.Random(seed)
    samples = []
    agent_priors = {}
    for i in range(n):
        mid_id = f"mkt-{i}"
        true_p = rng.uniform(0.10, 0.90)
        market_mid = min(0.99, max(0.01, true_p + rng.gauss(0.0, 0.12)))   # market: noisy
        agent_prior = min(0.99, max(0.01, true_p + rng.gauss(0.0, 0.02)))  # agent: much less noisy
        outcome = 1 if rng.random() < true_p else 0
        samples.append((binary_market(mid_id, market_mid), outcome))
        agent_priors[mid_id] = agent_prior
    return samples, agent_priors


def print_report(title: str, rep) -> None:
    print(f"\n  {title}")
    print(f"    observations   : {rep.n}")
    print(f"    Brier score    : {rep.brier:.4f}   (market ref {rep.ref_brier:.4f}; lower better)")
    print(f"    Brier skill    : {rep.skill:+.4f}  (>0 beats the market)")
    print(f"    calibration ECE: {rep.ece:.4f}   (<= {rep.max_ece:.2f} target)")
    print(f"    has skill       : {rep.has_skill}")
    print(f"    well calibrated : {rep.well_calibrated}")
    print(f"    >> TRUSTWORTHY (may size capital): {rep.trustworthy}")
    if rep.bins:
        print("    reliability (predicted -> observed):")
        for b in rep.bins:
            bar = "#" * round(b.obs_freq * 20)
            print(f"      [{b.lo:.1f},{b.hi:.1f})  n={b.count:>3}  "
                  f"pred {b.mean_pred:.2f}  obs {b.obs_freq:.2f}  {bar}")


def main() -> None:
    samples, agent_priors = build_resolved_set()

    print("=" * 64)
    print("  SIGNAL LAYER (F) — validation harness demo")
    print("  Does an off-hot-path research agent add information over the market?")
    print("=" * 64)

    agent = ExternalPriorProvider(agent_priors, confidence=1.0, shrink_to_market=False)
    print_report("Informed agent (the candidate signal)", evaluate_provider(agent, samples))
    print_report("Market-implied (the null reference)", evaluate_provider(MarketImpliedProvider(), samples))

    print("\n  Read: the agent earns the right to size capital only if it beats the")
    print("  market (skill > 0) AND is calibrated (ECE small). The market scores zero")
    print("  skill against itself by definition — it is not its own edge.")
    print("  Caveat: skill is hard to resolve in small samples (the gap is tiny vs")
    print("  Bernoulli noise) — hence Phase 0 demands a long real-money record and")
    print("  backtests never gate AUM (ADR-010).\n")


if __name__ == "__main__":
    main()
