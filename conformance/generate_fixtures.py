#!/usr/bin/env python3
"""Regenerate the language-neutral conformance fixtures in conformance/fixtures/.

Deterministic: fixed test-only Ed25519 seeds and fixed timestamps, so a rerun produces
byte-identical fixtures and both SDKs can pin `now` in their tests instead of racing the
clock. Everything here is test material — no production key, YID, or artifact.

Run with any Python that has PyJWT and cryptography:

    python conformance/generate_fixtures.py
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

OUT = Path(__file__).parent / "fixtures"

ISSUER = "https://yanez.test"
KID = "authz_test_1"
ROGUE_KID = "authz_rogue"
YID = "a" * 32
AGENT_KEY_ID = "yak_conformance1"
REQUEST_ID = "azr_" + "c0" * 16

# 2026-01-01T00:00:00Z — every time in the fixtures derives from this instant.
DECIDED_AT = 1767225600
NOW_FRESH = DECIDED_AT + 60          # verifying one minute after approval
NOW_STALE = DECIDED_AT + 86_400 * 30  # verifying a month later
# Inside max_age (900) so consent_bound_expired reaches the consent-bound check
# instead of tripping the freshness check first.
CONSENT_NOT_AFTER = DECIDED_AT + 300

TERMS = {
    "action": "purchase",
    "summary": "Buy running shoes for $180 at Example Store",
    "merchant": "Example Store",
    "amount": "180.00",
    "currency": "USD",
}

# Test-only seeds, deliberately low-entropy and checked in.
SIGNING_SEED = bytes(range(32))
ROGUE_SEED = bytes(range(1, 33))


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwk(key: Ed25519PrivateKey, kid: str) -> dict:
    return {"kty": "OKP", "crv": "Ed25519",
            "x": _b64url(key.public_key().public_bytes_raw()), "kid": kid, "alg": "EdDSA"}


def _sign(key: Ed25519PrivateKey, kid: str, claims: dict) -> str:
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})


def _claims(**overrides) -> dict:
    claims = {
        "iss": ISSUER,
        "sub": YID,
        "jti": REQUEST_ID,
        "iat": DECIDED_AT,
        "yanez_agent_key_id": AGENT_KEY_ID,
        "yanez_decision": "approved",
        "yanez_decided_at": DECIDED_AT,
        "yanez_match_overlap": 213,
        "yanez_terms": TERMS,
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _tamper(artifact: str) -> str:
    header, payload, sig = artifact.split(".")
    flipped = "A" if payload[20] != "A" else "B"
    return f"{header}.{payload[:20]}{flipped}{payload[21:]}.{sig}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.from_private_bytes(SIGNING_SEED)
    rogue = Ed25519PrivateKey.from_private_bytes(ROGUE_SEED)

    valid = _sign(key, KID, _claims())
    bounded = _sign(key, KID, _claims(yanez_consent_not_after=CONSENT_NOT_AFTER))

    fixtures: dict[str, dict] = {
        "jwks": {"keys": [_jwk(key, KID)]},
        "receipts": {
            "issuer": ISSUER,
            "expected_terms": TERMS,
            "decided_at": DECIDED_AT,
            "now_fresh": NOW_FRESH,
            "now_stale": NOW_STALE,
            "consent_not_after": CONSENT_NOT_AFTER,
            "cases": {
                # name -> {artifact, verdict-at-now_fresh with max_age 900 and expected_terms}
                "valid": {"artifact": valid, "ok": True},
                "consent_bound_active": {"artifact": bounded, "ok": True},
                "consent_bound_expired": {
                    "artifact": bounded, "ok": False, "error": "consent_policy",
                    "now": CONSENT_NOT_AFTER + 1},
                "stale": {"artifact": valid, "ok": False, "error": "consent_policy",
                          "now": NOW_STALE},
                "tampered": {"artifact": _tamper(valid), "ok": False, "error": "verification"},
                "unknown_kid": {"artifact": _sign(key, "authz_retired", _claims()),
                                "ok": False, "error": "verification"},
                "wrong_issuer": {
                    "artifact": _sign(key, KID, _claims(iss="https://evil.example")),
                    "ok": False, "error": "verification"},
                "wrong_key": {"artifact": _sign(rogue, KID, _claims()),
                              "ok": False, "error": "verification"},
                # Classic key confusion: HS256 keyed with the public-key bytes. A
                # verifier that let the header pick the algorithm would accept it.
                "wrong_algorithm": {
                    "artifact": jwt.encode(_claims(), key.public_key().public_bytes_raw(),
                                           algorithm="HS256", headers={"kid": KID}),
                    "ok": False, "error": "verification"},
                "missing_agent_key_id": {
                    "artifact": _sign(key, KID, _claims(yanez_agent_key_id=None)),
                    "ok": False, "error": "verification"},
                "not_approved": {
                    "artifact": _sign(key, KID, _claims(yanez_decision="rejected")),
                    "ok": False, "error": "verification"},
                "terms_mismatch": {
                    "artifact": valid, "ok": False, "error": "verification",
                    "expected_terms": {**TERMS, "amount": "999.00"}},
            },
        },
        "http": {
            "create_response": {
                "request_id": REQUEST_ID, "status": "pending",
                "decide_by": "2026-01-01T00:15:00Z",
            },
            "poll_pending": {"request_id": REQUEST_ID, "status": "pending",
                             "artifact": None, "consent_not_after": None, "decided_at": None},
            "poll_approved": {"request_id": REQUEST_ID, "status": "approved",
                              "artifact": valid, "consent_not_after": None,
                              "decided_at": "2026-01-01T00:00:00Z"},
            "poll_rejected": {"request_id": REQUEST_ID, "status": "rejected",
                              "artifact": None, "consent_not_after": None,
                              "decided_at": "2026-01-01T00:04:00Z"},
            "poll_expired": {"request_id": REQUEST_ID, "status": "expired",
                             "artifact": None, "consent_not_after": None, "decided_at": None},
            "introspect_first_consume": {
                "valid": True, "reason": None, "consumed_now": True, "sub": YID,
                "jti": REQUEST_ID, "decided_at": DECIDED_AT, "consent_not_after": None,
                "terms": TERMS,
            },
            "introspect_repeat_consume": {
                "valid": True, "reason": "already_consumed", "consumed_now": False,
                "sub": YID, "jti": REQUEST_ID, "decided_at": DECIDED_AT,
                "consent_not_after": None, "terms": TERMS,
            },
            "introspect_bad_signature": {"valid": False, "reason": "bad_signature"},
        },
    }

    for name, content in fixtures.items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n")
        print(f"wrote {path.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
