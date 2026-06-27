# Prediction-Market Quant Vault Marketplace

A two-sided marketplace where **makers** (quants) publish private trading strategies as **vaults**, and **depositors** allocate capital to them, trading on prediction-market venues (Polymarket, Kalshi).

This repository currently holds the **design and evaluation artifacts** plus early
Phase 0–2 scaffolding for the concept.

> **New here? Start with [`HANDOFF.md`](HANDOFF.md)** — the single read-me-first doc:
> status, locked decisions, full repo map, where we are against the plan, how to run
> everything, what's verified vs not, and next steps.

## The model in one paragraph

Makers run strategies on platform-hosted, sandboxed infrastructure (never locally, never holding keys). Capital sits in protocol vaults. Makers earn a **profit-only performance fee** (high-water mark, tiered by TVL), post **first-loss co-investment + a slashable bond** for alignment, and are subject to **mechanical slashing** and **dynamic, realized-data capacity caps**. Performance is **publicly verified** from real-money trading; live positions are disclosed on a lag to protect alpha. Custody is split: **on-chain ERC-4626 vaults** for Polymarket, a **regulated custodial vehicle** for Kalshi.

This is deliberately **not** the original "open-source bots, one-click local deploy, decentralized" pitch — that construction fails on alpha decay, the market-for-lemons, value capture, and security. See the evaluation for why, and the architecture for what replaced it.

## Documents

| Doc | What it covers |
|---|---|
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Feasibility critique, comp analysis (Numerai, QuantConnect Alpha Streams, Darwinex), heavy critique of the "35% of agents profitable" stat, TAM, challenges, and the pivots that make it feasible. |
| [`docs/DESIGN.md`](docs/DESIGN.md) | System design: components, vault & fee mechanics, custody split, risk engine, track-record, phased build. Includes a feasibility summary. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The **why**: architectural principles, decision records (ADRs) with rejected alternatives and trade-offs, trust boundaries, failure modes, buildable module layout, and key interface contracts. |
| [`docs/PLAN.md`](docs/PLAN.md) | Phase-by-phase build plan to 100% functionality, with checkpoints, kill criteria, a money-exposure ladder, and never-violate invariants. |

## Code (early build)

| Path | What it is |
|---|---|
| [`strategies/`](strategies/) | **Phase 0–1.** Clean-room sample strategies (arbitrage, market making, Kelly-edge) on an intent-based SDK, a Polymarket data layer + venue adapter, a price-replay backtester, paper trading, and a live loop with position reconciliation (kill-switch on divergence). Dependency-free Python; 11 smoke tests. |
| [`contracts/`](contracts/) | **Phase 2.** ERC-4626 `StrategyVault` skeleton (profit-only HWM fee, TVL tiers, first-loss + slashable bond, capacity cap, RiskGate-only slashing) + Foundry tests. Uncompiled skeleton — see its README. |

## Status

Design phase. The headline feasibility verdict is **conditionally feasible**, bounded by three conditions: (1) the maker co-investment ratio + bond must be sized to neutralize the performance fee's "free option" convexity; (2) total addressable market is capped by venue open interest (~$0.2–0.3B/venue); (3) a regulated wrapper (CPO/CTA + custodial Kalshi rail) is mandatory and front-loaded.
