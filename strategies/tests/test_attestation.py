#!/usr/bin/env python3
"""Tests for the attested-track-record flow (A-lite, ADR-018).
Run: `cd strategies && python tests/test_attestation.py`.

Verifies the property that makes A-lite work: results are verifiable, positions are
NOT in the attestation (only a hiding commitment), and the commitment binds a later
reveal (delayed disclosure).
"""
import os
import sys
from dataclasses import asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from predmkt import (  # noqa: E402
    AttestationService, commit_positions, verify_attestation, verify_position_reveal,
)

KEY = b"enclave-attestation-key"
RESULTS = {"net_pnl": 12345.0, "sharpe": 1.8, "max_dd": 0.06, "trades": 240}
POSITIONS = [{"market": "PRES-2028", "token": "YES", "size": 5000.0}]
SALT = "random-per-period-salt"


def _att():
    return AttestationService(KEY, code_hash="strategy-v1-abc123").attest(RESULTS, POSITIONS, SALT)


def test_genuine_attestation_verifies():
    att = _att()
    assert verify_attestation(att, KEY)
    assert verify_attestation(att, KEY, expected_code_hash="strategy-v1-abc123")


def test_positions_are_not_in_the_attestation():
    att = _att()
    blob = str(asdict(att))
    assert "5000" not in blob and "PRES-2028" not in blob, "raw positions must never be published"
    assert att.positions_commitment and len(att.positions_commitment) == 64  # sha256 hex


def test_tampered_results_fail():
    att = _att()
    att.results = dict(att.results, net_pnl=999999.0)   # forge a better record
    assert not verify_attestation(att, KEY), "tampering with results must break the signature"


def test_wrong_key_or_code_hash_fails():
    att = _att()
    assert not verify_attestation(att, b"not-the-enclave-key")
    assert not verify_attestation(att, KEY, expected_code_hash="some-other-binary")


def test_commitment_hides_and_binds():
    att = _att()
    # binding: the true (positions, salt) verify; any change does not
    assert verify_position_reveal(att, POSITIONS, SALT)
    assert not verify_position_reveal(att, POSITIONS, "wrong-salt")
    tampered = [{"market": "PRES-2028", "token": "YES", "size": 9999.0}]
    assert not verify_position_reveal(att, tampered, SALT)
    # hiding: same positions, different salt -> different commitment (leaks nothing)
    assert commit_positions(POSITIONS, "salt-a") != commit_positions(POSITIONS, "salt-b")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"\n{len(tests)} attestation tests passed.")
