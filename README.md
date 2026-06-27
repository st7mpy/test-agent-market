# Prediction-Market Quant Vault Marketplace

A two-sided marketplace where **makers** (quants) publish private trading strategies as **vaults**, and **depositors** allocate capital to them, trading on prediction-market venues (Polymarket, Kalshi).

This repository currently holds the **design and evaluation artifacts** for the concept — not yet an implementation.

## The model in one paragraph

Makers run strategies on platform-hosted, sandboxed infrastructure (never locally, never holding keys). Capital sits in protocol vaults. Makers earn a **profit-only performance fee** (high-water mark, tiered by TVL), post **first-loss co-investment + a slashable bond** for alignment, and are subject to **mechanical slashing** and **dynamic, realized-data capacity caps**. Performance is **publicly verified** from real-money trading; live positions are disclosed on a lag to protect alpha. Custody is split: **on-chain ERC-4626 vaults** for Polymarket, a **regulated custodial vehicle** for Kalshi.

This is deliberately **not** the original "open-source bots, one-click local deploy, decentralized" pitch — that construction fails on alpha decay, the market-for-lemons, value capture, and security. See the evaluation for why, and the architecture for what replaced it.

## Documents

| Doc | What it covers |
|---|---|
| [`docs/EVALUATION.md`](docs/EVALUATION.md) | Feasibility critique, comp analysis (Numerai, QuantConnect Alpha Streams, Darwinex), heavy critique of the "35% of agents profitable" stat, TAM, challenges, and the pivots that make it feasible. |
| [`docs/DESIGN.md`](docs/DESIGN.md) | System design: components, vault & fee mechanics, custody split, risk engine, track-record, phased build. Includes a feasibility summary. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The **why**: architectural principles, decision records (ADRs) with rejected alternatives and trade-offs, trust boundaries, failure modes, buildable module layout, and key interface contracts. |

## Status

Design phase. The headline feasibility verdict is **conditionally feasible**, bounded by three conditions: (1) the maker co-investment ratio + bond must be sized to neutralize the performance fee's "free option" convexity; (2) total addressable market is capped by venue open interest (~$0.2–0.3B/venue); (3) a regulated wrapper (CPO/CTA + custodial Kalshi rail) is mandatory and front-loaded.
