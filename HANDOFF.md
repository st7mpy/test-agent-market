# Project Handoff

**Project:** Prediction-Market Quant Vault Marketplace
**Branch:** `claude/quant-marketplace-evaluation-5pd4rp`
**Status:** Design complete · pre-Phase-0 scaffolding built & tested offline · **no phase gate passed yet**
**Last updated:** 2026-06-27

This is the single read-me-first document. It says what the project is, every decision
that's been locked, what code exists and what's verified, where we are against the build
plan, how to run everything, and what to do next. Deeper detail lives in `docs/`.

---

## 0. Read this first — three things that will bite you

1. **Pushed.** The branch `claude/quant-marketplace-evaluation-5pd4rp` is on GitHub at
   `st7mpy/test-agent-market` (the original 403 push-block is resolved). Continue work
   on that branch; open a PR when a phase gate is ready for review.

2. **This session's network blocks `polymarket.com`** (egress policy → 403, confirmed). So
   every `--live` path and real-data backtest is **written but untested here**; everything
   ran against a bundled offline fixture. Re-run the live paths in a networked environment.

3. **The Solidity now compiles and tests pass, but is NOT externally audited.**
   `contracts/` builds under Foundry 1.7.1 / solc 0.8.24 / OpenZeppelin v5 and passes
   **24 tests** (incl. the HWM no-double-charge-across-drawdown vector and the insurance-fund
   loss waterfalls); Slither is triaged in `contracts/AUDIT-PREP.md` (3 accepted findings).
   The loss-waterfall is now implemented (ADR-015); **external Audit #1 (Phase 3) remains
   the gate before any real capital.**

And one conceptual caveat: the original "35% of agents are profitable" validation is
**directionally true but laundered** — conditioned on the actual target user it collapses to
~10–30% (often worse). See `docs/EVALUATION.md §3`. Don't rebuild the naive pitch on it.

---

## 1. What the project is

A two-sided marketplace where **makers** (quants) publish *private* trading strategies as
**vaults**, and **depositors** allocate capital to them, trading on prediction markets
(Polymarket first). Makers run on platform-hosted sandboxed infra (never local, never holding
keys), earn a **profit-only** performance fee, post **first-loss capital + a slashable bond**,
and live under **mechanical slashing** and **dynamic capacity caps**. Performance is publicly
verified from real-money trading; live positions are disclosed on a lag.

This is configuration **B-on-C** (infrastructure layer + capital allocator) — deliberately
**not** the original "open-source bots, one-click local deploy, decentralized" pitch, which
fails on alpha decay, the market-for-lemons, value capture, and security. The full reasoning,
competitive analysis, TAM, and the pivot are in the docs below.

| Doc | Read it for |
|---|---|
| `docs/EVALUATION.md` | Feasibility critique, comp analysis, the "35%" teardown, TAM, why the pivot |
| `docs/DESIGN.md` | System design: components, vault/fee mechanics, custody split, phased build |
| `docs/ARCHITECTURE.md` | The **why**: 18 ADRs (incl. the differentiators), trust boundaries, failure modes |
| `docs/PLAN.md` | Phase-by-phase plan to 100% + the 2026 moat re-eval / differentiator map |
| `docs/DIFFERENTIATION.md` · `docs/COMPETITION.md` | 2026 competitive scan + the moat (B/F/D/C/A-lite/E) |
| `docs/TEE-DESIGN.md` | A-lite design: TEE-private positions + attested track records (ADR-018) |
| `docs/Concept-Brief.pdf` | 7-page styled brief (idea, users, TAM, architecture, user flows) |

---

## 2. Decisions locked (the config everything is built around)

| Decision | Choice | Why / source |
|---|---|---|
| Product shape | **B-on-C** (infra + private-strategy allocator) | EVALUATION — solves lemons + value capture |
| First venue | **Polymarket**, on-chain | founder pick — fastest to live, defers regulatory lift |
| Jurisdiction | **Offshore**, non-US users | founder pick — Polymarket geofences US |
| Token | **None** — centralized platform + on-chain vaults | founder pick — leanest path |
| First alpha source | **Founder runs own strategy** | founder pick — cleanest Phase-0 control |
| Resourcing | **Solo / bootstrapped**, milestone-based | founder pick — sequential, build-vs-buy |
| Performance fee | **Profit-only + per-share HWM + TVL tiers** | founder confirmed — avoids churn/AUM-gather |
| Alignment | **Maker first-loss co-invest + slashable bond**, ratio enforced | founder confirmed — kills the fee's free-option convexity |
| Track record | **Public verified real-money**; live positions delayed | founder confirmed — anti-fraud without alpha leak |
| Slashing | **Mechanical, pre-committed triggers** | founder confirmed — enforceable, no disputes |
| Capacity | **Dynamic, realized-data caps** | founder confirmed — anti-overcapitalization |

**The #1 unresolved design risk:** the co-invest *ratio* + bond must be sized to outweigh the
performance fee's option value, or alignment is cosmetic. Model this before real capital
(`docs/PLAN.md §11`, `docs/DESIGN.md §11`).

---

## 3. Repo map (full outline)

```
README.md                     project index
HANDOFF.md                    ← you are here
.gitignore

docs/
  EVALUATION.md               feasibility, comps, "35%" critique, TAM, challenges
  DESIGN.md                   system design + feasibility summary
  ARCHITECTURE.md             ADRs (the "why"), trust boundaries, interface contracts
  PLAN.md                     phase-by-phase build plan + checkpoints + invariants
  Concept-Brief.pdf           7-page styled brief  (source: concept-brief.src.html)

strategies/                   Phase 0–1 code — dependency-free Python, 11 smoke tests
  predmkt/
    types.py                  domain types + the Intent vocabulary (the strategy boundary)
    base.py                   Strategy base class + per-tick Context
    fees.py                   Polymarket (min(p,1-p)+cap) and Kalshi fee models
    arbitrage.py              strategy 1: intra-market / NegRisk / cross-venue
    market_maker.py           strategy 2: Avellaneda-Stoikov adapted to [0,1] markets
    kelly_edge.py             strategy 3: fractional Kelly + guarded mean-reversion
    sim.py                    offline order-book builders + synthetic series
    data.py                   live Polymarket API (Gamma + CLOB book/history) + fixture loader
    venue.py                  VenueAdapter: Polymarket + Kalshi (live) + ReplayAdapter + CrossVenueFeed (D, ADR-016)
    execution.py              RiskGate + PaperBroker + PaperOMS (trusted execution seams)
    reconcile.py              position reconciliation (halt-on-divergence, ADR-011)
    signals.py                signal layer (F): SignalProvider seam + Brier/calibration harness (ADR-012/013)
    oracle_risk.py            oracle/resolution-risk scoring for the RiskGate (C, ADR-014)
    attestation.py            attested track records / TEE flow stub (A-lite, ADR-018)
  data/sample_history.json    offline price fixture (Polymarket schema, resolves YES)
  demo.py                     prints intents each strategy emits
  backtest.py                 price-replay backtester (--live / --file / fixture; --pages, --outcome)
  papertrade.py               paper-trade behind the venue adapter + risk gate + OMS
  live.py                     live/poll loop + reconciliation + kill-switch
  signal_demo.py              scores a research agent vs the market (Brier skill + calibration)
  multivenue_demo.py          cross-venue arb across two (offline) venues, venue-aware fees
  phase0_journal.py           Phase-0 trade journal incl. venue-yield (rebate/reward) accounting
  check_polymarket.py         live-API reachability probe (headers fix; see DEPLOY_DATA.md)
  capture_history.py          poll a live market's mid into a backtestable series (--file)
  DEPLOY_DATA.md              run live data from a supported region if geo-blocked
  tests/test_smoke.py         11 smoke · signals 7 · phase0_journal 5 · oracle_risk 8 · multivenue 7 · attestation 5
  README.md, LICENSE (MIT)

contracts/                    Phase 2/6 — vaults (compile, 31 Foundry tests, not audited)
  src/StrategyVault.sol       profit-only HWM fee, TVL tiers, first-loss+bond, caps, slashing,
                              insurance fund + loss waterfalls (ADR-015)
  src/TranchedVault.sol       Phase-6 senior/junior tranches (E, ADR-017)
  test/StrategyVault.t.sol    happy-path Foundry tests (5)
  test/StrategyVaultProperties.t.sol   adversarial money-path vectors (12)
  test/StrategyVaultInsurance.t.sol    insurance fund + loss waterfalls (7)
  test/TranchedVault.t.sol    senior/junior tranching (7)
  AUDIT-PREP.md               toolchain, coverage matrix, Slither triage (Audit #1 scoping)
  foundry.toml, README.md
```

~2,500 lines of Python + Solidity. 7 commits (see `git log --reverse`).

---

## 4. Where we are vs the plan

**Important framing:** the code built so far is **cross-phase scaffolding**, not passed gates.
`docs/PLAN.md` defines each phase by an objective checkpoint; **none have been passed** — e.g.
Phase 0's gate is a *documented positive net real-money edge*, which requires trading real
capital on Polymarket (blocked here by network + no live data). What exists is the *tooling*
the founder will use to attempt those gates.

| Phase (PLAN.md) | Gate | Built so far | Status |
|---|---|---|---|
| **0 Prove the edge** | Positive net real-money edge, documented | Sample strategies + backtester + paper-trader + edge screener + trade journal/gate-checker | ⏳ tooling ready; **edge NOT proven** (needs real $ + network) |
| **1 Automate it** | Hosted bot ≥ manual; exact reconciliation; kill-switch | Venue adapter, intent→RiskGate→OMS, reconcile + kill-switch, live loop, **signal layer (F) + Brier/calibration gate** | ⏳ skeleton runs offline; **untested on live data** |
| **2 Vault** | NAV reconciles incl. resolution; halts on divergence | `StrategyVault.sol` **compiles + 24 tests pass + Slither triaged**; loss-waterfall implemented | ⏳ **compiles & tested; not externally audited** |
| **3 First outside money** | AUDIT #1 + fee/HWM correct + legal | fee/HWM correctness **proven by test vectors** (`AUDIT-PREP.md`); **multi-venue (D): Kalshi adapter + CrossVenueFeed + venue-aware fees**; audit + legal still pending | ◻ code-correctness done; audit/legal not started |
| **4 Safety systems** | Chaos tests pass; unattended soak | partial: RiskGate, slashing, caps, kill-switch, **+ oracle-risk scoring/gating + insurance fund & loss-waterfall (C)**; chaos suite pending | ◻ not hardened |
| **5 Untrusted makers** | Sandbox escape impossible (AUDIT #2) | intent-boundary designed; **A-lite TEE design + attestation-flow stub (A, ADR-018, `docs/TEE-DESIGN.md`)**; real enclave + pentest/AUDIT #2 gated | ◻ design + stub; enclave not built |
| **6 Public launch** | Self-serve + geofence + AUDIT #3 + legal | **tranched vaults (E): `TranchedVault.sol` senior/junior, 7 tests**; UI/KYC/geofence not started | ◻ tranching done; launch infra not started |
| **7 Harden to 100%** | Full feature matrix + no Sev-1 soak | — | ◻ not started |
| **8 Kalshi rail** | (post-100%) regulatory decision | — | ◻ explicitly deferred |

---

## 5. How to run everything

```bash
# --- Python (no dependencies; runs offline) ---
cd strategies
python tests/test_smoke.py                 # 11 smoke tests
python tests/test_signals.py               # 7 signal-layer tests (F)
python tests/test_phase0_journal.py        # 5 venue-yield journal tests (B)
python tests/test_oracle_risk.py           # 8 oracle-risk scoring/gating tests (C)
python tests/test_multivenue.py            # 7 multi-venue + cross-venue arb tests (D)
python tests/test_attestation.py           # 5 attested-track-record / TEE-flow tests (A-lite)
python multivenue_demo.py                  # cross-venue arb across two venues (D)
python demo.py                             # intents each strategy emits
python signal_demo.py                      # signal skill + calibration vs the market (F)
python phase0_journal.py status            # Phase-0 net PnL incl. venue-yield + gate (B)
python backtest.py --strategy mm           # price-replay backtest (fixture)
python backtest.py --strategy kelly
python papertrade.py --strategy mm         # paper-trade via adapter + risk gate + OMS
python live.py --strategy mm               # live loop, reconciliation clean
python live.py --strategy mm --inject-divergence-at 100   # demo: kill-switch halt

# --- Live Polymarket data (works from a normal network; headers clear Cloudflare) ---
python check_polymarket.py                                   # reachability probe
python backtest.py  --strategy mm  --live  --query "election"   # --pages N to search deeper
python papertrade.py --strategy arb --source live --query "election"
python live.py       --strategy mm --source live --query "election"
# free prices-history is sparse for some markets — capture a live series, then replay it:
python capture_history.py --query "bitcoin hit \$1m" --out btc1m.json --interval 30 --steps 240
python backtest.py --strategy mm --file btc1m.json --outcome YES

# --- Contracts (needs Foundry + network) ---
cd contracts
forge install OpenZeppelin/openzeppelin-contracts foundry-rs/forge-std --no-commit
forge build && forge test -vvv
```

Sample offline results (deliberately unremarkable — backtester and paper-trader agree):
`mm -0.27%` (adversely selected on a trending market), `kelly +0.13%`. These prove nothing
until a real-money track record — that's the Phase-0 point.

---

## 6. Verified vs unverified (be honest about this)

| Area | Verified here | NOT verified |
|---|---|---|
| Python strategies, SDK, execution, reconcile | ✅ 11 smoke tests; demo/backtest/paper/live all run offline | — |
| Reconciliation halt-on-divergence | ✅ injected-fault test halts + trips kill-switch | behavior against a real venue feed |
| Live Polymarket adapter (REST CLOB/Gamma) | endpoints + parsing written | ❌ never hit a real endpoint (network blocked) |
| Backtest/paper on real data | code path written | ❌ no real series fetched |
| `StrategyVault.sol` | logic written + tests written | ❌ never compiled, never run, not audited |
| Fee/venue-mechanic numbers | structure modelled | ❌ approximate — confirm against venue docs |

---

## 7. Open questions to resolve (before spending real money)

1. **Co-invest ratio + bond sizing** that provably beats the fee's option value — model first.
2. **Capacity-oracle** estimator: robust + gaming-resistant from realized slippage.
3. **Junior loss-waterfall** in the vault (first-loss absorbing strategy losses before
   depositors) — stubbed in `StrategyVault.sol`; needs settlement integration.
4. **Per-share HWM equalization** on mid-period deposits/withdrawals.
5. **Regulated wrapper** (offshore entity, geofencing, counsel on Polymarket/US-founder
   exposure) — gates any outside money.
6. **Position-disclosure delay** window: long enough to protect alpha, short enough to stay credible.

---

## 8. Immediate next steps (prioritized)

1. **Preserve the work:** grant GitHub write access and push the branch (Section 0.1).
2. **Phase-0 for real:** in a networked env, fetch real Polymarket data (`--live`), then trade
   your own capital and document a positive *net* edge. This is the existential kill-gate — no
   edge, no business (consider the picks-and-shovels infra pivot instead; EVALUATION §10).
3. **Legal:** open the regulatory conversation now (offshore structure + Polymarket/US-founder
   exposure) — it's long-lead and gates everything downstream.
4. **Compile the vault:** `forge build && forge test`; fix what doesn't compile; scope Audit #1.
5. **Phase-1 live test:** run the venue adapter + reconciliation against real Polymarket books;
   confirm reconciliation holds and the kill-switch behaves.
6. **Sandbox (Phase 5 prerequisite):** the intent boundary is designed but the Firecracker/gVisor
   strategy sandbox — the thing that lets untrusted maker code run near funds — is not built.

---

## 9. Key concepts (glossary)

- **Intent boundary (ADR-002):** strategies only emit declarative `Intent`s (orders / splits /
  cancels); they never hold keys. Every intent passes the `RiskGate` before execution. This is
  the security crux and is already wired in `execution.py`.
- **Vault mechanics (ADR-004/005):** profit-only fee above a high-water mark, tiered by TVL;
  maker first-loss + slashable bond aligned by capital, not reputation.
- **Reconcile-or-halt (ADR-011):** internal positions are a derived view; the venue is truth;
  divergence trips the kill-switch. Implemented in `reconcile.py` + `live.py`.
- **Capacity caps (ADR-007):** dynamic, driven by *realized* execution quality — prevents
  overcapitalizing capacity-limited edges.

For anything not covered here, the four `docs/` files are the source of truth; this handoff
points at them rather than duplicating them.
