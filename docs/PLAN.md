# Build Plan — Phase by Phase to 100% Functionality

*Configuration: Polymarket-first · on-chain vaults · offshore · centralized platform · no token · founder runs the first strategy · solo/bootstrapped. Checkpoints are **milestone-based** (deliverable/effort gates), not calendar dates. Effort sizing: **S** ≈ days, **M** ≈ a few weeks, **L** ≈ 1–2 months solo.*

> **Definition of "100% functionality":** an open, public, two-sided vault marketplace on Polymarket — anyone can deposit; vetted external makers can list private strategies — running **safely at scale** with every safety system proven in production. The Kalshi / regulated rail is a separate, explicitly-gated **post-100% expansion** (Phase 8), because it requires the CPO/CTA regulatory path that was deprioritized.

---

## Moat re-evaluation (2026) — the simple vault is no longer white space

A competitive re-scan (`docs/DIFFERENTIATION.md`, `docs/COMPETITION.md`) shows the naïve
"vault marketplace" has **already shipped**: Moneytalks (0% + 10% profit-only — our *exact*
fee) and PolyFund (≤3% + ≤30%) both run pooled-capital Polymarket vaults today. Demand is
validated; the wrapper is commoditized. The moat is therefore **not** the vault — it is the
**stacked combination no competitor has**, defended by what incumbents structurally *can't* do
(positions forced on-chain; zero-sum directional alpha; uninsured oracle risk).

**Moat statement.** *The professional prediction-market vault with private, un-copyable verified
positions, market-neutral venue-yield, and oracle-failure protection — aligned by maker first-loss
+ slashable bond under mechanical slashing and dynamic capacity caps.*

**The wedge (this changes what Phase 0 proves).** Lead with **venue-yield market-making (B)**, not
directional alpha. Polymarket pays makers **20–25% of taker fees as rebates** plus **liquidity
rewards for resting orders near mid** — a positive-sum, market-neutral, easier-to-sell yield stream
that sidesteps the laundered "35% of agents are profitable" stat entirely. Directional alpha becomes
a secondary track, not the existential bet.

**Differentiators → phases:**

| Diff | What | Phase | Effort | Defensibility |
|---|---|---|---|---|
| **B** venue-yield MM vault *(the wedge)* | harvest rebates + liquidity rewards, market-neutral | **0–1** | low (coded) | medium |
| **F** AI research-agent signal layer | calibrated fair-value probabilities, off the hot path | 1+ | low (pluggable hook) | low–med |
| **D** multi-venue aggregation | Kalshi/Limitless/… via pmxt/agg.market; lifts the capacity ceiling | 3+ | medium | medium |
| **C** oracle controls + depositor insurance | cap dispute-prone markets; insurance fund from fee + slashing | 4 | medium | **high** |
| **A-lite** TEE-private positions + attested record | hide positions from public/copycats; enclave attests results | 5 | high | **highest** |
| **E** tranched / principal-protected vaults | senior (yield-funded, paid first) + junior (first-loss) | 6 | medium | medium |

**Architecture deltas** (full rationale in `docs/DIFFERENTIATION.md`):
- **A-lite is the committed TEE target** — the platform still sees positions (the RiskGate and
  key-holding OMS require it); only the *public/copycats* are blind. This composes with the existing
  intent→RiskGate→OMS path and ADR-009. A-full (keys + RiskGate inside the enclave) reworks custody
  (ADR-008) and reconciliation (ADR-011) — a research track, too heavy for a solo Phase 5.
- **C** extends the existing `RiskGate` (per-market oracle-risk score) and routes the vault's slash
  waterfall to the insurance fund.
- **E** is the *same machinery* as the `_applyLoss` loss-waterfall stub already in `StrategyVault.sol`
  — building it closes that open question (DESIGN §11) rather than adding new surface.

---

## What makes this plan "fool-proof"

Three mechanisms run *across every phase* and are the reason a single mistake can't sink the project or other people's money:

### A. Hard go/no-go gates
No phase begins until the prior phase's **checkpoint** passes — every checkpoint is objective and verifiable (not "feels done"). Each phase also has an explicit **kill/pivot criterion**.

### B. The money-exposure ladder (blast-radius caps)
Total outside capital is hard-capped per phase and **only ratchets up after a clean soak at the current level**. It ratchets **down automatically** on any incident. You never expose more than you've proven you can safely hold.

| Phase | Max outside AUM | Depositors | Strategy authors |
|---|---|---|---|
| 0–2 | $0 (founder capital only) | none | founder only |
| 3 | ≤ $25k | ≤ 3, whitelisted | founder only |
| 4 | ≤ $100k | ≤ 10, whitelisted | founder only |
| 5 | ≤ $250k (small per-vault caps) | invite-only | + a few invited makers |
| 6 | ≤ $1M, raised in steps | public | public (vetted) |
| 7 | scale as audits/soak allow | public | public |

### C. Never-violate invariants (enforced in code, checked at every gate)
1. Untrusted strategy code **never** touches keys or funds.
2. **No outside capital** flows before a passing security audit of the money-path in scope.
3. NAV must **reconcile to the venue or the vault halts** — no deposits/withdrawals/fees on divergence.
4. No vault accepts deposits **beyond its capacity cap**.
5. A vault cannot list (or accept a deposit) unless the maker's **co-invest ratio + bond** are satisfied.
6. **Any money-path code change → re-audit** before the AUM cap is raised.
7. AUM caps **ratchet up only after a clean soak**; they ratchet **down on incident**.

### Cross-cutting workstreams (run alongside the phases)
- **Security:** threat model (P1) → audit #1 vault+fee (P3 gate) → audit #2 sandbox/key-isolation (P5 gate) → audit #3 full-system + bug bounty (P6 gate) → ongoing.
- **Legal:** counsel on Polymarket/US-founder exposure **before P3**; offshore entity + ToS + geofencing policy before outside money; hardened before public (P6).
- **Compliance:** manual KYC/geofence (P3) → automated KYC/geofence vendor (P6).
- **Ops:** observability+alerting (P4) → SLOs + on-call + incident runbooks (P6/7).

---

## Phase map (critical path)

```
P0 Prove the edge ──▶ P1 Automate it ──▶ P2 Wrap it in a vault ──▶ P3 First outside money
   (kill-gate)          (hosted bot)        (NAV/accounting)         (fee+align, AUDIT #1)
                                                                          │
P7 Harden to 100% ◀── P6 Public launch ◀── P5 Untrusted makers ◀────────┘
   (soak, SLOs)         (AUDIT #3, legal)    (sandbox, AUDIT #2)        P4 Safety systems
                                                                          (slashing, caps, kill-switch)
                                   ⋯ P8 (post-100%) Kalshi / regulated rail — separate go/no-go
```

---

## Phase 0 — Prove the edge (the existential kill-gate)
**Objective:** confirm *you personally have a real, positive, real-money edge on Polymarket* before building anything. **Effort: S–M.**

**Why first:** the entire business is a wrapper around alpha. If the alpha isn't real, no amount of engineering matters. This is the cheapest possible place to fail.

**▶ Wedge (B):** the edge to prove *first* is **venue-subsidized market-neutral yield** — maker rebates (20–25% of taker fees) + liquidity rewards on resting orders near mid, harvested by `strategies/predmkt/market_maker.py` — measured **net of a rebate haircut** (assume the program tightens). This is positive-sum and easier to sell than directional alpha, which becomes the secondary track. Track both with `strategies/phase0_journal.py`, which records rebate/reward **income** alongside fee/gas **cost**.

**Deliverables**
- Trade your own capital on Polymarket (manually or with a throwaway script), leading with the **market-making/venue-yield** strategy class; directional alpha as a secondary track.
- Log every fill, fee, gas cost, **and rebate/liquidity-reward income**; compute **net** PnL (and net-of-haircut yield).

**✅ Checkpoint (go/no-go)**
- A documented track record over a meaningful sample (e.g. ≥ 100 trades and ≥ 6–8 weeks spanning ≥ 1 event resolution) showing **positive net-of-all-costs** PnL with a Sharpe you'd stake money on.
- You can articulate *why* the edge exists and *who the losing counterparty is* — and why it won't vanish immediately at small scale.

**🛑 Kill/pivot:** no demonstrable net edge → **stop**, or pivot to the pure picks-and-shovels infra play (sell tooling, never promise alpha). Do not build a marketplace for alpha you don't have.

---

## Phase 1 — Automate it (the C foundation, single venue, your money)
**Objective:** reproduce your manual edge as a **hosted, automated** strategy through the real execution path. **Effort: L.**

**Deliverables**
- `VenueAdapter` for Polymarket (CLOB API + Polygon/CTF) + normalized market-data feed.
- The hot path: **strategy → intent → Risk Gate → Execution/OMS → venue**, with keys in a managed KMS/HSM (**buy**: Turnkey/Fireblocks).
- Your strategy running hosted (still your capital, no vault, no outside money).
- Basic reconciliation (internal position/PnL vs venue) + manual kill-switch.
- Threat model written.

**▶ Differentiator (F):** the `fair_value_fn` hook in `strategies/predmkt/kelly_edge.py` is where an **LLM research-agent signal layer** plugs in — calibrated fair-value probabilities from news/base-rates, Brier-scored, kept **off the hot path** (it only proposes a probability; the Risk Gate still gates every intent). Low effort, the legitimate use of "AI agents" here.

**✅ Checkpoint**
- Hosted bot **matches or beats** your Phase-0 manual track record over a live period.
- Reconciliation is **exact** (internal state == venue state) across a sustained run including an event resolution.
- Kill-switch flattens and halts on command, verified.

**🛑 Kill/pivot:** automation materially underperforms manual (slippage/latency eats the edge) → diagnose; if the edge only exists at manual speed/size, the productized version won't work — rescope.

---

## Phase 2 — Wrap it in a vault (on-chain accounting, still your money)
**Objective:** put your capital inside the real **ERC-4626 vault** with correct NAV accounting. **Effort: M–L.**

**Deliverables**
- ERC-4626 vault contract on Polygon (**buy/fork**: audited template) holding USDC + CTF positions.
- NAV engine: realized cash + marked positions, **resolution-aware** (conservative marks on pending resolution).
- Deposit/withdraw (you only), share minting at NAV/share.
- **Signed NAV snapshots** anchored on-chain (attestation service).
- Continuous **NAV-vs-venue reconciliation → auto-halt on divergence** (invariant #3).

**✅ Checkpoint**
- NAV/share reconciles to venue reality continuously over a sustained period **including an event resolution and a withdrawal**.
- Inject a deliberate divergence → vault **halts** as designed.
- Internal audit / static analysis of the vault contract clean.

**🛑 Kill/pivot:** NAV can't be kept faithful to venue reality (e.g. resolution/marking ambiguity) → fix before *any* outside money; this is non-negotiable.

---

## Phase 3 — First outside money (fees, alignment, closed whitelist) · **AUDIT #1**
**Objective:** prove the economics end-to-end with a few trusted outsiders. **Effort: L.** **AUM cap ≤ $25k, ≤ 3 whitelisted depositors.**

**Deliverables**
- Profit-only **performance fee + per-share HWM + TVL tiers**; protocol take.
- **Co-invest ratio** enforcement (your first-loss tranche) + **slashable bond** (locked).
- Manual KYC + **geofencing** (exclude US persons) for the whitelist.
- **External security audit #1** of vault + fee + co-invest/bond math.
- Legal: offshore entity formed; ToS/disclaimers; counsel sign-off on structure (invariant #2 gate).

**✅ Checkpoint**
- Fee **crystallizes correctly** across deposits, withdrawals, **and a drawdown** (HWM never double-charges recovery) — proven with test vectors + a live cycle.
- Co-invest ratio holds as depositors enter; deposits that would breach it are rejected.
- A whitelisted depositor deposits and **withdraws cleanly** at correct NAV.
- **Audit #1 findings resolved**; legal sign-off in hand.

**🛑 Kill/pivot:** audit finds an unfixable money-path flaw, or fee/HWM accounting can't be made provably correct → halt outside money until resolved.

---

## Phase 4 — Safety systems (run unattended without losing money)
**Objective:** make the system safe to operate without you watching it. **Effort: L.** **AUM cap ≤ $100k, ≤ 10 whitelisted.**

**Deliverables**
- **Risk engine** hardened: pre-trade limits, slippage-vs-book-depth guard, per-vault drawdown limit, **mandate conformance**, per-venue exposure caps.
- **Mechanical slashing** wired to objective triggers (limit breach, drawdown breach, mandate deviation, ratio shortfall) with the **depositor-first waterfall**.
- **Capacity Oracle** v1: dynamic caps from realized slippage/edge decay (auto-tighten on degraded fills).
- **Global + per-vault kill-switch**; automated incident response (auto-halt + alert).
- Observability: metrics, logs, alerting, dashboards.

**▶ Differentiator (C — high moat):** extend the Risk engine with a **per-market oracle-risk score** (cap or refuse exposure to dispute-prone / thin-oracle markets — the $7M UMA false-settlement class of risk) and stand up a **depositor insurance fund** funded by the protocol fee + slashing proceeds. Position: *"the only prediction-market vault that protects you from oracle failure."* Both build on the existing `RiskGate` (`predmkt/execution.py`) and the vault's slash waterfall.

**✅ Checkpoint (adversarial/chaos tests all pass)**
- Simulated limit breach → **slash fires**, waterfall compensates depositors.
- Simulated NAV divergence → **halt**. Simulated venue outage → **safe** (no bad fills, clean recovery).
- Capacity Oracle **demonstrably tightens** the cap when fills degrade.
- A full unattended soak at the $100k cap with **zero manual intervention** and no invariant violations.

**🛑 Kill/pivot:** any safety mechanism fails its chaos test → fix and re-run before raising caps.

---

## Phase 5 — Untrusted makers (the sandbox) · private beta · **AUDIT #2**
**Objective:** safely run **third-party** strategy code and prove the two-sided flow with real external makers. **Effort: L (security-critical).** **AUM cap ≤ $250k, invite-only; small per-vault caps.**

**Why this is the highest-risk phase:** until now the only strategy was *yours* (trusted). Now untrusted code runs near (but never touching) other people's money.

**▶ Differentiator (A-lite — highest moat):** the sandbox **is a TEE** (Phala/Oasis), not just Firecracker. It isolates untrusted maker code *and* keeps **live positions private from the public/copycats** while the enclave emits a **cryptographically attested** track record — "trade with proof, not trust." The platform still sees positions (the Risk Gate requires them); only outsiders are blind, which is what makes "private strategy + verified record" actually hold. Copy-bots cannot copy what they cannot see (resolves the transparency-vs-alpha-leak tension in ADR-009).

**Deliverables**
- **Sandboxed strategy runtime — a TEE** (Phala/Oasis enclave; Firecracker/gVisor as the inner isolation): no key access, no egress except feed + intent bus (invariant #1); enclave attestation of results.
- **Maker SDK** (Python/TS) + reproducible, content-addressed backtester.
- Incubation flow: external maker runs **own capital** → builds a **verified real-money track record** → unlocks outside-AUM tier (gated by track record + co-invest + bond).
- **External security audit #2** focused on **sandbox escape + key isolation** (the rug surface).
- Cross-vault correlation monitor (now meaningful with >1 vault).

**✅ Checkpoint**
- **Pentest proves** a hostile strategy cannot reach keys, funds, or other vaults (sandbox escape attempts fail).
- An external maker goes incubation → verified track record → takes whitelisted capital **safely**.
- Incubation→AUM gating, capacity caps, and slashing all work for a *third-party* vault.
- **Audit #2 findings resolved.**

**🛑 Kill/pivot:** any sandbox-escape or key-isolation finding that can't be fully closed → **no untrusted code in production**. (Fallback: curated first-party-only strategies until solved.)

---

## Phase 6 — Public marketplace launch (open both sides) · **AUDIT #3 + legal hardening**
**Objective:** anyone can deposit; vetted makers can list, self-serve. **Effort: L.** **AUM cap ≤ $1M, raised in steps.**

**Deliverables**
- Self-serve onboarding: **automated KYC + geofencing** (**buy**: Persona/Sumsub) for depositors; maker vetting pipeline.
- **Public marketplace UI**: browse/filter vaults by verified performance, drawdown, capacity headroom, maker skin-in-game, fee tier.
- **Track-record pages** (verified, immediate) + **delayed/obfuscated live position disclosure** (anti-copy).
- Capacity-managed deposits (queue/reject past cap); depositor monitoring + notifications.

**▶ Differentiator (E):** offer **tranched** vaults — a **senior** tranche (principal-protected, lower variance, funded from the market-neutral venue-yield, paid first) + a **junior** tranche (first-loss, higher upside). This widens the funnel to conservative capital and is the *same machinery* as the maker first-loss / `_applyLoss` waterfall stub in `StrategyVault.sol` — implementing it here closes that open question.
- **External security audit #3 (full-system)** + **public bug bounty** live.
- Legal: public ToS/risk disclosures, geofencing enforcement verified, offshore structure sign-off for public operation.
- Load/scale test to target concurrency.

**✅ Checkpoint**
- A cohort of **real external users** completes deposit→monitor→withdraw self-serve, end to end.
- **Geofencing verified** (US persons blocked) by independent test.
- Load test passes at target; **audit #3 resolved**; bug bounty running with no open criticals.
- Legal sign-off for public launch.

**🛑 Kill/pivot:** unresolved critical audit/bug-bounty finding, or geofencing leaks → do not open / roll back to private beta.

---

## Phase 7 — Harden to 100% (steady-state, scale, ops maturity)
**Objective:** operate safely at scale; reach the formal 100%-functionality bar. **Effort: ongoing.** **AUM cap raised as soak/audits allow.**

**Deliverables**
- Full **SLOs + on-call + tested incident runbooks**; automated reconciliation + alerting at scale.
- **Systemic risk** controls live across many vaults (aggregate correlation/exposure, global circuit breakers).
- Capacity Oracle v2 (robust, gaming-resistant); per-strategy caps managed at scale.
- Tax/PnL reporting exports; depositor + maker support ops.
- Recurring audits + always-on bug bounty.

**✅ Checkpoint — the "100% functionality" acceptance checklist (all green over a sustained soak):**
- **Feature matrix complete:** vault lifecycle, profit-only fee+HWM+tiers, co-invest+bond, mechanical slashing, dynamic capacity caps, sandboxed multi-maker runtime, verified track records + delayed disclosure, public self-serve both sides, automated KYC/geofence.
- **Safety proven in production:** every invariant enforced; every chaos test green in prod-like conditions; **no Sev-1 incidents** over the soak window.
- **Ops mature:** SLOs met, on-call + runbooks exercised, reconciliation clean at scale.
- **Capital ladder fully ratcheted** with no incident-driven rollbacks during the window.

**🛑 Kill/pivot:** repeated Sev-1s or invariant violations at scale → freeze cap, root-cause, re-soak before proceeding.

---

## Phase 8 — (Post-100%) Kalshi / regulated rail — *separate go/no-go*
**Not part of the on-chain 100%.** Requires the regulatory fork you deprioritized. **Entry gate:** an explicit decision to (a) form a US/regulated entity, (b) pursue **CPO/CTA** registration, (c) stand up **regulated custody** + dual-rail (on-chain + off-chain) accounting. Treat as its own mini-plan with the same gate/ladder/audit discipline. Do **not** start it until the on-chain marketplace is at 100% and the regulatory decision is consciously made with counsel.

---

## One-page checkpoint summary

| Phase | Exit checkpoint (must all pass) | Gate type |
|---|---|---|
| 0 | Positive net real-money edge, documented, explained | **Kill-gate** |
| 1 | Hosted bot ≥ manual; exact reconciliation; kill-switch works | Go/no-go |
| 2 | NAV reconciles incl. resolution+withdrawal; halts on divergence | Go/no-go |
| 3 | Fee/HWM correct across drawdown; **audit #1** clean; legal sign-off | **Money gate** |
| 4 | All chaos tests pass; unattended soak at $100k clean | Safety gate |
| 5 | Sandbox escape impossible (**pentest/audit #2**); 3rd-party vault safe | **Security gate** |
| 6 | Self-serve E2E; geofencing verified; **audit #3** + legal sign-off | **Launch gate** |
| 7 | 100% feature matrix + no Sev-1 over soak + ops mature | **100% gate** |
| 8 | (Optional) regulatory decision + entity + custody | Separate go/no-go |
