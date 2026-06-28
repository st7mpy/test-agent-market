"""Attested track records (A-lite, differentiator A / ADR-018) — "trade with proof,
not trust".

Every competitor's positions are forced on-chain, so copy-bots decay the very alpha
the vault sells (ADR-009). A-lite runs the maker strategy inside a **TEE** (Phala /
Oasis): the live positions stay private from the public/copycats, while the enclave
emits a **cryptographically attested** track record — verifiable performance *without*
revealing the trades.

⚠️ STUB: real attestation is a TEE remote-attestation quote (asymmetric, hardware-rooted)
over the enclave + strategy binary. Here stdlib HMAC stands in for the enclave's
attestation key so the *flow* is testable offline. The shape that matters is real:

  the enclave publishes verifiable RESULTS + a hiding COMMITMENT to its positions,
  never the positions themselves; positions can be revealed LATER (delayed disclosure,
  ADR-009) and checked against that commitment.

A-lite vs A-full: in A-lite the platform still sees positions (the RiskGate + key-holding
OMS need them) — only outsiders are blind. A-full puts keys + RiskGate inside the enclave
so the platform is blind too; that reworks custody (ADR-008) + reconciliation (ADR-011)
and is a research track, not this.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _digest(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def commit_positions(positions: List[dict], salt: str) -> str:
    """A hiding + binding commitment to a position set. `salt` hides it (so the
    commitment leaks nothing about positions); revealing (positions, salt) later
    proves what was held at attestation time without letting anyone copy it live."""
    return _digest({"positions": positions, "salt": salt})


@dataclass
class Attestation:
    code_hash: str             # which strategy binary produced this (integrity)
    results: Dict[str, Any]    # PUBLIC verified track record (net pnl, sharpe, ...)
    positions_commitment: str  # hiding commitment to the SECRET live positions
    signature: str             # enclave signature over the above (RA-quote stand-in)


class AttestationService:
    """Stands in for the TEE enclave. Holds the attestation key and signs the results
    + the position *commitment* — never the positions. Real impl: the enclave's
    hardware key, and `signature` is a remote-attestation quote a verifier checks
    against the manufacturer's root + the expected enclave measurement."""

    def __init__(self, enclave_key: bytes, code_hash: str) -> None:
        self._key = enclave_key
        self.code_hash = code_hash

    def attest(self, results: Dict[str, Any], positions: List[dict], salt: str) -> Attestation:
        commitment = commit_positions(positions, salt)
        payload = {"code_hash": self.code_hash, "results": results,
                   "positions_commitment": commitment}
        sig = hmac.new(self._key, _digest(payload).encode("utf-8"), hashlib.sha256).hexdigest()
        return Attestation(self.code_hash, results, commitment, sig)


def verify_attestation(att: Attestation, enclave_key: bytes, *,
                       expected_code_hash: Optional[str] = None) -> bool:
    """Verify the enclave's signature over (code_hash, results, commitment), and
    optionally that it's the expected strategy binary. Proves the results are
    genuine and untampered WITHOUT the verifier ever seeing the positions."""
    payload = {"code_hash": att.code_hash, "results": att.results,
               "positions_commitment": att.positions_commitment}
    expected_sig = hmac.new(enclave_key, _digest(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, att.signature):
        return False
    if expected_code_hash is not None and att.code_hash != expected_code_hash:
        return False
    return True


def verify_position_reveal(att: Attestation, positions: List[dict], salt: str) -> bool:
    """Delayed-disclosure check (ADR-009): once the alpha-protection window has passed,
    the maker reveals (positions, salt); anyone can confirm they match what was
    committed at attestation time — proving no after-the-fact position editing."""
    return hmac.compare_digest(commit_positions(positions, salt), att.positions_commitment)
