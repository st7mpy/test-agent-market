# GTM — Distribution, Accelerators, and How People Actually Get In

*Founder-view companion to `PLAN.md`. That doc says what to build and when it's safe;
this one says how each phase acquires makers, depositors, capital, and credibility.
Written against the 2026 competitive reality in `COMPETITION.md` / `DIFFERENTIATION.md`.*

---

## 0. The GTM thesis in four sentences

1. This is a **two-sided cold-start**, and the sides are not symmetric: **supply
   (makers with real edge) is the scarce asset**; depositor demand follows verified
   performance, never the reverse.
2. Our structural disadvantage is **distribution** — Olas/Virtuals have token
   flywheels, Polymarket owns the audience — so we don't buy distribution, we
   **manufacture credibility**: attested, real-money track records nobody else can fake
   (A-lite) and publish the build honestly.
3. The product ladder mirrors the money ladder: **founder's own record → invited
   makers → senior-tranche yield for conservative capital → public marketplace.**
   Marketing at each rung sells only what the phase gates have already proven.
4. Because we are offshore + geofenced (no US persons), **compliance is a marketing
   constraint from day one**: no yield promises, no US solicitation, disclosures on
   every number. The honesty is also the brand.

---

## 1. Phase-aligned GTM ladder

GTM work attaches to the build phases (`PLAN.md`); nothing is marketed before its
gate passes. Effort tags: (S)olo-hours, (M)eaningful, (L)arge.

| Build phase | GTM track running alongside | Goal / exit metric |
|---|---|---|
| **P0 prove edge** | *Build-in-public groundwork* (S): landing live (agmen.vercel.app), waitlist on it, X/Farcaster account, 1 honest essay/week from the docs | 500 waitlist emails; the P0 PnL thread drafted but NOT posted until the gate passes |
| **P1 automate** | *Founder track record as content* (M): publish the attested journal weekly (net of fees, drawdowns shown), "how the risk gate works" teardown posts | 1k followers who are quants/PM traders, not tourists; 10 inbound maker DMs |
| **P2–P3 vault + first outside money** | *Accelerator window #1* (M) + friends-and-family whitelist (≤3 depositors, ≤$25k, from the waitlist) | Accepted into 1 crypto-native accelerator OR 3 committed angels; whitelist filled from inbound only |
| **P4 safety systems** | *The "boring is the product" campaign* (S): chaos-test writeups, slashing demo video, insurance-fund explainer | Every safety claim maps to a public test artifact |
| **P5 untrusted makers** | *Maker acquisition engine v1* (L): incubation waitlist → paper league → seeded vaults (see §2) | 25 makers in the league, 5 incubated, 2 external vaults live under caps |
| **P6 public launch** | *Launch + tranche wedge* (L): senior tranche marketed to conservative capital as "prediction-market yield, subordination-protected"; PR around the attested-track-record primitive | $1M AUM cap reached in steps; CAC per depositor < 1yr of protocol fee on their deposit |
| **P7 scale** | *B2B white-label (H)* (M): license the vault+attestation stack to venues/apps — the non-token distribution answer | 1 signed integration partner |

**Rule:** each phase's marketing may only cite numbers produced by a **passed gate**.
The kill-criteria discipline applies to GTM too — a campaign that misses its exit
metric twice gets killed, not "iterated."

---

## 2. Getting makers in (supply side — the one that matters)

**Who they are:** solo quants and 2-person algo shops; ex-prop/HFT people with a side
model; the profitable tail of the Polymarket leaderboard; QuantConnect/Numerai
diaspora who already accepted "submit signals/strategies for capital" as a model.

**The pitch (their language):** *keep your strategy private, get capital +
co-located execution you don't have to build, and walk away owning a portable,
cryptographically attested track record.* The track record is the hook — it's the
one asset a quant can't manufacture alone and keeps even if we die.

**Channels, in order of expected yield:**
1. **Direct outreach to on-chain performers.** Polymarket wallets are public;
   the profitable-bot cohort is identifiable from fills. 50 hand-written DMs/emails
   beats any ad. (The flow-signal work in `predmkt/flow_signal.py` doubles as the
   sourcing tool — score wallets, court the top decile.)
2. **The paper league.** Run a recurring public **paper-trading competition on our
   own runner infra** (configs + attested reports): free to enter, leaderboard is
   attestation-backed, winners get incubation slots + platform-seeded first-loss.
   This converts our tooling into an acquisition funnel and pre-screens for exactly
   the skill we custody. Cost ≈ server time.
3. **Quant communities:** QuantConnect/Numerai forums, college quant clubs
   (IIT/ISI circuits are underserved and close to home), r/algotrading, prediction
   -market Discords. Give talks on the *mechanics* (fee models, oracle risk) — the
   docs are the content.
4. **Content honeypot:** publish the EVALUATION-grade teardowns ("the 35% stat is
   laundered", "why copy-bots decay alpha") — contrarian, technical, exactly what
   makers read.

**Anti-goals:** no "earn 20% APY" maker ads; no paying influencers; no open-sourcing
strategies as bait (ADR-003 forbids it and it attracts the wrong cohort).

---

## 3. Getting depositors in (demand side)

**Sequencing matters:** depositors are not marketed to at all until P3, and the
public wedge is the **senior tranche** (E): capped-upside, subordination-protected,
funded by venue-yield — the only prediction-market product a conservative allocator
can hold without pretending to be a degen. Junior/alpha exposure is the upsell,
never the front door.

**Segments + message:**
| Segment | Message | Channel |
|---|---|---|
| Crypto-native yield seekers (non-US) | "Market-neutral venue-subsidized yield; every number attested on-chain" | X/Farcaster, DeFi yield aggregator listings (ERC-4626 composability is free distribution) |
| HNW / small funds (offshore) | "Uncorrelated event-driven sleeve with mechanical risk controls + insurance fund" | warm intros, the accelerator network, one-pager from Concept-Brief |
| Prediction-market power users | "Stop donating spread to bots — hold the vault that runs them" | Polymarket-adjacent Discords/newsletters |

**The content engine is the funnel:** weekly attested performance post → track-record
page → waitlist → KYC'd whitelist. Every post carries the disclosure block (risk of
loss, no US persons, not investment advice). We never publish a projected APY;
we publish realized, net, attested numbers with drawdowns in the same font size.

---

## 4. Accelerators & capital (founder's calendar)

**What we are to investors:** infrastructure + asset-management hybrid on a venue
class that just validated ($2B Polymarket raise, Kalshi growth) — with the moat being
attested-private track records, not "we got there first."

**Fit-ranked targets:**
1. **Alliance DAO** — crypto-native, remote, takes non-US founders/entities
   routinely; closest thesis fit (DeFi infra + real yield). Apply with the P1 gate
   passed (own money, automated, attested record live).
2. **a16z crypto CSX** — best network for the regulated/institutional turn and the
   B2B white-label track; apply at P3–P4 with outside money safely custodied and
   audit #1 done.
3. **YC** — generalist but the brand compounds hiring + BD; the pitch there is
   "Stripe-for-prediction-market-asset-management," lead with the attestation
   primitive. Needs the cleanest story on regulatory posture.
4. **Outlier Ventures / venue-adjacent programs** — backup tier; useful token-less
   base-camp programs exist, but beware token-pressure programs (we are explicitly
   no-token; DIFFERENTIATION rejects that flywheel).
5. **Angels that matter more than any program:** prediction-market operators,
   ex-Polymarket/Kalshi employees, quant-fund partners, UMA/oracle people. They
   answer the two questions programs can't: venue API risk and oracle politics.

**The ask evolves with the gates:**
- Post-P1: $250–500k pre-seed SAFE — funds legal (offshore entity + counsel, the
  long-lead item), audit #1, and 12 months of runway. The deck is HANDOFF.md turned
  into 12 slides; the demo is the live attested dashboard.
- Post-P4/P5: seed — funds the TEE build, audits #2–3, first BD hire.
- **Never raise on projected AUM.** Raise on: gates passed, attested PnL, maker
  waitlist depth, and the insurance/attestation primitives as licensable IP (H).

**Entity reality (do before any accelerator signs):** offshore opco (BVI/Cayman
pattern), founder in India = FEMA counsel on the fund flows, IP assigned to the
entity, no US-person solicitation anywhere in the funnel. An accelerator's standard
SAFE will force this cleanup anyway — cheaper to arrive clean.

---

## 5. Marketing system (what actually ships weekly)

- **The attested dashboard is the homepage.** agmen.vercel.app graduates from
  brochure → live, verifiable numbers (results immediate, positions delayed,
  ADR-009). Nobody else's numbers are cryptographically checkable; ours are the ad.
- **One essay/week, from the repo.** The docs are 80% written: oracle-risk pricing,
  venue-yield mechanics, why slashing must be mechanical, TEE trade-with-proof.
  Technical, honest, zero hype — the audience we want filters itself in.
- **Build-in-public with teeth:** publish chaos-test results and *incidents* too.
  The credibility asymmetry vs. competitors' "127% profit!!" marketing is the moat's
  marketing twin.
- **Founder brand:** the person who says "most of you will lose; here's the one
  construction that doesn't require you to be wrong about that."

---

## 6. Funnel metrics + kill criteria

| Funnel | Metric | Healthy | Kill/retool if |
|---|---|---|---|
| Waitlist | emails, % quant-qualified | 500 by P1 exit | <100 after 8 honest posts |
| Maker | DMs→league entrants→incubated | 10→25→5 by P5 | league <10 after 2 seasons |
| Depositor | waitlist→KYC→funded, CAC | CAC < 1yr protocol fee/depositor | CAC > 3yr fee |
| Content | qualified inbound per post | ≥2 | 0 across 10 posts → change channel, not voice |
| Capital | term sheet by P3+6mo | 1 | none → bootstrap P4 on fees, revisit at P5 |

---

## 7. The 90-day founder calendar (starting now, pre-P0-gate)

Weeks 1–2: entity/counsel engaged (parallel to everything); waitlist + analytics on
the landing; first essay ("what the 35% stat hides") from EVALUATION.md.
Weeks 3–6: run the venue-yield strategy on own capital (P0 attempt); journal in
public *after* each week closes; 25 maker DMs from leaderboard sourcing.
Weeks 7–10: P0 gate review — pass → publish the full attested thread + open
incubation waitlist; fail → publish that too (credibility compounds either way),
pivot per PLAN kill-criteria.
Weeks 11–13: Alliance application drafted against whatever gate is real; paper-league
season 1 announced to the waitlist.

*Everything above is sequenced so that no marketing claim ever outruns a passed
gate — the same invariant discipline as the build plan, applied to the story.*
