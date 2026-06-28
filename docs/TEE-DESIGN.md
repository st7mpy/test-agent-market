# A-lite — TEE-private positions + attested track records (the capstone moat)

*Differentiator A (DIFFERENTIATION.md §3A), Phase 5. This is the design; the running
code is the attestation-flow stub in `strategies/predmkt/attestation.py`. Real enclaves
need Phala/Oasis infra + network, so the enclave itself is not stood up here.*

---

## 1. The problem it solves

Every direct competitor (Moneytalks, PolyFund, copy-bots) exposes positions on-chain.
That's *why* copy-bots work — and it decays the very alpha a vault sells. ADR-009 split
**results** (public, immediate) from **live positions** (delayed) to manage this, but a
delay is a weak lever: too short and you leak, too long and you're not credible.

A-lite resolves the tension cryptographically: **prove the track record without revealing
the trades.** "Trade with proof, not trust." Copy-bots cannot copy what they cannot see.

## 2. What A-lite is (and the A-lite vs A-full line)

Run the maker's (untrusted) strategy inside a **Trusted Execution Environment** (Phala /
Oasis). The enclave:
- runs the strategy binary and emits **intents** (as today), and
- publishes a **verified track record** with a **remote-attestation quote** proving *which
  code* produced *which results* on genuine enclave hardware — while the **live positions
  stay private**.

**A-lite (committed):** the platform still sees positions — the RiskGate and the
key-holding OMS *require* them to bound risk and sign orders. Only the **public/copycats**
are blind. This composes with everything already built and is deliverable by a solo founder.

**A-full (research track, not this):** keys + RiskGate move *inside* the enclave, so even
the platform is blind. That reworks custody (ADR-008) and reconciliation (ADR-011) and is
far heavier — explicitly out of scope for Phase 5.

## 3. How it composes with the existing architecture

The TEE **is the Phase-5 strategy sandbox** — it replaces/augments the Firecracker/gVisor
isolation with the *same* trust boundary, plus privacy + attestation:

```
   UNTRUSTED (inside TEE enclave)        TRUSTED PLATFORM (sees positions)      PUBLIC
  ┌───────────────────────────┐
  │ maker strategy binary      │── intents ─▶ RiskGate ─▶ Execution/OMS ─▶ venue
  │  (positions private)       │                 ▲            (KMS keys)
  │ enclave attests:           │                 │ positions visible to platform only
  │  • code measurement        │
  │  • verified RESULTS  ──────┼── attestation ──┴────────────────────────▶ track-record page
  │  • commitment(positions)   │                                            (results now,
  └───────────────────────────┘                                             positions revealed later)
```

The intent boundary (ADR-002) is unchanged: untrusted code still only emits intents that
the RiskGate validates. A-lite adds two things on top — **the strategy code (and its
positions) is now hidden from outsiders**, and **its output is attested**.

## 4. The attestation flow (what the stub demonstrates)

Per reporting period the enclave produces an `Attestation`:
- `code_hash` — which strategy binary ran (integrity / anti-bait-and-switch);
- `results` — the **public** verified record (net PnL, Sharpe, drawdown, trade count);
- `positions_commitment` — a **hiding + binding** commitment to the secret positions;
- `signature` — the enclave's attestation over the above (a remote-attestation quote).

Anyone can `verify_attestation(...)`: the results are genuine and untampered, produced by
the expected binary — **without seeing a single position**. Later, after the alpha-protection
window (ADR-009), the maker reveals `(positions, salt)` and `verify_position_reveal(...)`
confirms they match what was committed — proving no after-the-fact editing.

The stub uses stdlib HMAC as a stand-in for the enclave key. The real system replaces this
with a hardware remote-attestation quote verified against the manufacturer root + the
expected enclave measurement; the *shape* (verifiable results, hidden positions, binding
commitment, delayed reveal) is exactly what's modeled and tested.

## 5. What the enclave does and does NOT guarantee

- **Does:** code integrity (the attested binary is what ran), output integrity (results
  aren't forged), confidentiality of positions from outsiders.
- **Does not (in A-lite):** hide positions from the platform (by design — RiskGate needs
  them); hold funds (keys stay in the platform KMS/HSM, ADR-001); remove the need for the
  Phase-5 **security gate** — sandbox-escape + key-isolation pentest and **Audit #2** still
  apply. A TEE is a strong boundary, not a substitute for that review (side-channel and
  supply-chain risks remain and must be threat-modeled).

## 6. Status

- **Implemented (offline, testable):** the attestation flow — `predmkt/attestation.py`
  (`AttestationService`, `verify_attestation`, `commit_positions`, `verify_position_reveal`)
  + 5 tests asserting results verify, positions never appear in the attestation, tampering
  breaks the signature, and the commitment binds the later reveal.
- **Gated (not here):** the actual Phala/Oasis enclave, hardware remote attestation, and the
  Phase-5 pentest + Audit #2. This doc + the stub are the design and the seam they slot into.
