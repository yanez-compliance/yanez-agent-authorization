#!/usr/bin/env python3
"""Regenerate the language-neutral conformance fixtures in conformance/fixtures/.

Deterministic: fixed test-only seeds and fixed timestamps, so a rerun produces
byte-identical fixtures and both SDKs can pin `now` in their tests instead of racing the
clock. Everything here is test material — no production key, YID, or artifact.

Two signatures appear in every receipt, and this file mints both:

- Ed25519, the issuer's signature over the receipt.
- BLS12-381, the approver's own signature over the decision message (spec §4.1, §5).

The BLS half is generated here with `py_ecc` and verified in the TypeScript suite with
`@noble/curves`. Two independent implementations agreeing on the same bytes is the only
cross-check available until real device vectors land — a library verifying its own
output proves the plumbing, not the parameters.

Run with any Python that has PyJWT, cryptography, and py_ecc:

    python conformance/generate_fixtures.py
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from py_ecc.bls import G2Basic

OUT = Path(__file__).parent / "fixtures"

ISSUER = "https://yanez.test"
KID = "authz_test_1"
YID = "a" * 32
AGENT_KEY_ID = "yak_conformance1"
REQUEST_ID = "azr_" + "c0" * 16
USER_SIG_ALG = "BLS12-381-G2-basic"
ENVELOPE_ACTION = "agent_authorizations.decision"
TIER = "high"

# 2026-01-01T00:00:00Z — every time in the fixtures derives from this instant.
DECIDED_AT = 1767225600
NOW_FRESH = DECIDED_AT + 60          # verifying one minute after approval
NOW_STALE = DECIDED_AT + 86_400 * 30  # verifying a month later
# Inside max_age (900) so consent_bound_expired reaches the consent-bound check
# instead of tripping the freshness check first.
CONSENT_NOT_AFTER = DECIDED_AT + 300
# The device signed a few seconds before the server recorded the decision. Verifiers
# bound the DIFFERENCE, never either value against today's clock.
SIGNED_AT = DECIDED_AT - 4

# Spec §3.1: schema_version is required, `display` is gone, and the app formats the
# amount from minor_units and the currency's own exponent.
TERMS = {
    "schema_version": 1,
    "action": "purchase",
    "approval_title": "Purchase running shoes",
    "summary": "Buy running shoes for $180.00 at Example Store",
    "merchant": "Example Store",
    "currency": "USD",
    "amount": {"minor_units": 18000, "currency": "USD"},
    "details": [
        {"label": "Merchant", "value": "Example Store", "emphasized": False},
        {"label": "Item", "value": "Running shoes, model X, size 10", "emphasized": False},
        {"label": "Amount", "value": "$180.00", "emphasized": True},
    ],
}

# Test-only seeds, deliberately low-entropy and checked in.
SIGNING_SEED = bytes(range(32))
ROGUE_SEED = bytes(range(1, 33))
USER_SEED = bytes(range(2, 34))
OTHER_USER_SEED = bytes(range(3, 35))


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwk(key: Ed25519PrivateKey, kid: str) -> dict:
    return {"kty": "OKP", "crv": "Ed25519",
            "x": _b64url(key.public_key().public_bytes_raw()), "kid": kid, "alg": "EdDSA"}


def _sign(key: Ed25519PrivateKey, kid: str, claims: dict) -> str:
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})


def _envelope(**overrides) -> dict:
    """The §4.1 decision message. Sorted keys are the producer convention; verification
    uses the exact bytes, so the ordering here is a convention and never a rule."""
    envelope = {
        "action": ENVELOPE_ACTION,
        "assurance_tier": TIER,
        "authorization_request_id": REQUEST_ID,
        "consent_not_after": None,
        "decision": "approve",
        "issuer": ISSUER,
        "signed_at": SIGNED_AT,
        "terms": TERMS,
        "version": 1,
        "yid": YID,
    }
    envelope.update(overrides)
    return envelope


def _encode(envelope: dict) -> bytes:
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()


def _proof(user_sk: int, envelope: dict) -> dict:
    """The five §4.6 claims for one signed envelope."""
    raw = _encode(envelope)
    return {
        "yanez_assurance_tier": envelope["assurance_tier"],
        "yanez_user_public_key": "0x" + G2Basic.SkToPk(user_sk).hex(),
        "yanez_user_signature": "0x" + G2Basic.Sign(user_sk, raw).hex(),
        "yanez_signed_message": _b64url(raw),
        "yanez_user_sig_alg": USER_SIG_ALG,
    }


def _claims(user_sk: int, *, envelope: dict | None = None, proof: dict | None = None,
            **overrides) -> dict:
    """A full receipt claim set, its user proof consistent unless a case overrides it."""
    envelope = _envelope() if envelope is None else envelope
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
        **(proof if proof is not None else _proof(user_sk, envelope)),
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
    user_sk = G2Basic.KeyGen(USER_SEED)
    other_sk = G2Basic.KeyGen(OTHER_USER_SEED)
    user_pk = "0x" + G2Basic.SkToPk(user_sk).hex()

    def receipt(**kw) -> str:
        return _sign(key, KID, _claims(user_sk, **kw))

    valid = receipt()
    bounded = _sign(key, KID, _claims(
        user_sk, envelope=_envelope(consent_not_after=CONSENT_NOT_AFTER),
        yanez_consent_not_after=CONSENT_NOT_AFTER))

    # A signature made by a key that is not the user's. Everything else is consistent,
    # so only the curve arithmetic can tell these apart.
    wrong_signer = {**_proof(other_sk, _envelope()), "yanez_user_public_key": user_pk}

    # Base64url pads only when the byte length is not a multiple of three, so the
    # non-canonical case needs an envelope whose encoding actually carries "=". Stretch
    # the request id until it does, in the claims and the envelope together. The
    # resulting message is entirely legitimate; the only thing wrong with the fixture is
    # how it was spelled.
    padded_id = next(
        REQUEST_ID + "0" * n for n in range(3)
        if len(_encode(_envelope(authorization_request_id=REQUEST_ID + "0" * n))) % 3
    )
    padded_envelope = _envelope(authorization_request_id=padded_id)

    # A pre-signed-approval receipt: a real approval with no proof. It must fail rather
    # than degrade into a receipt nobody signed.
    legacy = {k: None for k in ("yanez_assurance_tier", "yanez_user_public_key",
                                "yanez_user_signature", "yanez_signed_message",
                                "yanez_user_sig_alg")}

    cases = {
        # name -> {artifact, verdict at now_fresh with max_age 900 and expected_terms}
        "valid": {"artifact": valid, "ok": True},
        "consent_bound_active": {"artifact": bounded, "ok": True},
        "consent_bound_expired": {
            "artifact": bounded, "ok": False, "error": "consent_policy",
            "now": CONSENT_NOT_AFTER + 1},
        "stale": {"artifact": valid, "ok": False, "error": "consent_policy",
                  "now": NOW_STALE},
        "tampered": {"artifact": _tamper(valid), "ok": False, "error": "verification"},
        "unknown_kid": {"artifact": _sign(key, "authz_retired", _claims(user_sk)),
                        "ok": False, "error": "verification"},
        "wrong_issuer": {"artifact": receipt(iss="https://evil.example"),
                         "ok": False, "error": "verification"},
        "wrong_key": {"artifact": _sign(rogue, KID, _claims(user_sk)),
                      "ok": False, "error": "verification"},
        # Classic key confusion: HS256 keyed with the public-key bytes. A verifier that
        # let the header pick the algorithm would accept it.
        "wrong_algorithm": {
            "artifact": jwt.encode(_claims(user_sk), key.public_key().public_bytes_raw(),
                                   algorithm="HS256", headers={"kid": KID}),
            "ok": False, "error": "verification"},
        "missing_agent_key_id": {"artifact": receipt(yanez_agent_key_id=None),
                                 "ok": False, "error": "verification"},
        "not_approved": {"artifact": receipt(yanez_decision="rejected"),
                         "ok": False, "error": "verification"},
        "terms_mismatch": {
            "artifact": valid, "ok": False, "error": "verification",
            "expected_terms": {**TERMS, "amount": {"minor_units": 99900, "currency": "USD"}}},

        # --- the approver's own signature (spec §4.7 steps 4-5) ---
        #
        # Every one of these carries a perfectly valid Yanez JWT. A verifier that checks
        # only the receipt accepts all of them.

        "user_proof_absent": {
            "artifact": receipt(proof=legacy), "ok": False, "error": "user_signature",
            "why": "a receipt minted before signed approvals must fail, not degrade"},
        "user_signature_wrong_key": {
            "artifact": receipt(proof=wrong_signer), "ok": False, "error": "user_signature",
            "why": "signed by a key that is not the one the receipt names"},
        "user_signature_corrupt": {
            "artifact": receipt(proof={**_proof(user_sk, _envelope()),
                                       "yanez_user_signature": "0x" + "11" * 96}),
            "ok": False, "error": "user_signature",
            "why": "the signature is not a valid curve point"},
        "user_message_swapped": {
            # The signature is real, but for a different message. Only the curve check
            # catches this; every field cross-check passes.
            "artifact": receipt(proof={**_proof(user_sk, _envelope()),
                                       "yanez_signed_message": _b64url(
                                           _encode(_envelope(signed_at=SIGNED_AT + 1)))}),
            "ok": False, "error": "user_signature",
            "why": "the signature covers different bytes"},
        "user_message_not_canonical": {
            "artifact": receipt(envelope=padded_envelope, jti=padded_id,
                                proof={**_proof(user_sk, padded_envelope),
                                       "yanez_signed_message": base64.urlsafe_b64encode(
                                           _encode(padded_envelope)).decode()}),
            "ok": False, "error": "user_signature",
            "why": "padded base64url is a second spelling of one message"},
        "user_sig_alg_unsupported": {
            "artifact": receipt(proof={**_proof(user_sk, _envelope()),
                                       "yanez_user_sig_alg": "BLS12-381-G2-aug"}),
            "ok": False, "error": "user_signature",
            "why": "a scheme this version cannot check"},
        "user_decision_rejected": {
            "artifact": receipt(envelope=_envelope(decision="reject")),
            "ok": False, "error": "user_signature",
            "why": "a rejection is signed just as validly as an approval"},
        "user_tier_mismatch": {
            "artifact": receipt(
                envelope=_envelope(assurance_tier="low"),
                proof={**_proof(user_sk, _envelope(assurance_tier="low")),
                       "yanez_assurance_tier": "high"}),
            "ok": False, "error": "user_signature",
            "why": "the receipt claims a higher tier than the user signed"},
        "user_terms_mismatch": {
            "artifact": receipt(envelope=_envelope(
                terms={**TERMS, "amount": {"minor_units": 1, "currency": "USD"}})),
            "ok": False, "error": "user_signature",
            "why": "Yanez's account of the terms and the user's disagree"},
        "user_issuer_mismatch": {
            "artifact": receipt(envelope=_envelope(issuer="https://evil.example")),
            "ok": False, "error": "user_signature", "why": "signed for another issuer"},
        "user_action_mismatch": {
            "artifact": receipt(envelope=_envelope(action="agent_authorizations.other")),
            "ok": False, "error": "user_signature",
            "why": "a signature minted in another ceremony"},
        "user_request_id_mismatch": {
            "artifact": receipt(envelope=_envelope(
                authorization_request_id="azr_" + "ff" * 16)),
            "ok": False, "error": "user_signature",
            "why": "approval of a different request"},
        "user_yid_mismatch": {
            "artifact": receipt(envelope=_envelope(yid="b" * 32)),
            "ok": False, "error": "user_signature",
            "why": "approved by a different identity"},
        "user_consent_bound_mismatch": {
            "artifact": _sign(key, KID, _claims(
                user_sk, envelope=_envelope(consent_not_after=CONSENT_NOT_AFTER))),
            "ok": False, "error": "user_signature",
            "why": "the user signed a deadline the receipt does not carry"},
        "user_version_unsupported": {
            "artifact": receipt(envelope=_envelope(version=2)),
            "ok": False, "error": "user_signature",
            "why": "an envelope version this SDK cannot read"},
        "user_signed_at_drift": {
            "artifact": receipt(envelope=_envelope(signed_at=DECIDED_AT - 3600)),
            "ok": False, "error": "user_signature",
            "why": "signed an hour before the server recorded it"},
        "assurance_tier_low": {
            "artifact": receipt(
                envelope=_envelope(assurance_tier="low"),
                proof=_proof(user_sk, _envelope(assurance_tier="low"))),
            "ok": True, "assurance_tier": "low",
            "why": "genuine, and below a high floor — a policy decision, not a bad receipt"},
    }

    fixtures: dict[str, dict] = {
        "jwks": {"keys": [_jwk(key, KID)]},
        "receipts": {
            "issuer": ISSUER,
            "expected_terms": TERMS,
            "decided_at": DECIDED_AT,
            "signed_at": SIGNED_AT,
            "now_fresh": NOW_FRESH,
            "now_stale": NOW_STALE,
            "consent_not_after": CONSENT_NOT_AFTER,
            "assurance_tier": TIER,
            "user_public_key": user_pk,
            "user_sig_alg": USER_SIG_ALG,
            "cases": cases,
        },
        "user_keys": {
            # GET /api/agent/user_keys (spec §4.9). The route spells keys 0x + lowercase
            # hex like the receipt claim; bare hex here on purpose, so a verifier that
            # compares without normalizing fails this fixture instead of in production.
            "yid": YID,
            "keys": [
                {"tier": TIER, "public_key": user_pk[2:]},
                {"tier": "medium", "public_key": G2Basic.SkToPk(other_sk).hex()},
                {"tier": None, "public_key": "cc" * 48},
            ],
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
                "terms": TERMS, "assurance_tier": TIER, "user_public_key": user_pk,
                "user_sig_alg": USER_SIG_ALG,
            },
            "introspect_repeat_consume": {
                # Another holder won. Never act.
                "valid": True, "reason": "already_consumed", "consumed_now": False,
                "sub": YID, "jti": REQUEST_ID, "decided_at": DECIDED_AT,
                "consent_not_after": None, "terms": TERMS, "assurance_tier": TIER,
                "user_public_key": user_pk, "user_sig_alg": USER_SIG_ALG,
            },
            "introspect_reservation_held": {
                # This caller already holds it, from an attempt whose response was lost.
                # Recovery, not refusal: reconcile with the original idempotency key.
                "valid": True, "reason": "reservation_held", "consumed_now": False,
                "sub": YID, "jti": REQUEST_ID, "decided_at": DECIDED_AT,
                "consent_not_after": None, "terms": TERMS, "assurance_tier": TIER,
                "user_public_key": user_pk, "user_sig_alg": USER_SIG_ALG,
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
