"""The approver's own signature: the standalone helpers, and the policy gates built on
them.

`test_verifier.py` drives the same vectors through `ReceiptVerifier`. These tests cover
the half of the surface an executor uses when it already has a JWT library it trusts and
only needs the part a JWT library cannot do.
"""
from __future__ import annotations

import base64
import json

import httpx
import jwt
import pytest

from yanez_authz import (
    ConsentPolicyError,
    ReceiptVerifier,
    ReservationHeldError,
    UserSignatureError,
    key_is_registered,
    terms_equal,
    verify_bls_signature,
    verify_user_proof,
)
from yanez_authz.proof import UserProof, UserProofError, decode_signed_message

BASE = ISSUER = "https://yanez.test"
TOKEN = "executor-attempt-1"


def _claims(receipts, name="valid"):
    return jwt.decode(receipts["cases"][name]["artifact"], options={"verify_signature": False})


def _verifier(jwks, extra_handler=None, **kw):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/authz/public-keys":
            return httpx.Response(200, json=jwks)
        if extra_handler is not None:
            return extra_handler(request)
        return httpx.Response(404, json={"detail": "unknown"})

    return ReceiptVerifier(BASE, ISSUER, transport=httpx.MockTransport(handler), **kw)


# --- the standalone path: no client, no network, no SDK JWT handling ---


def test_verify_user_proof_works_on_claims_from_any_jwt_library(receipts):
    """The whole point of the standalone helper: bring your own JWT decoding."""
    proof = verify_user_proof(_claims(receipts), expected_issuer=receipts["issuer"])

    assert isinstance(proof, UserProof)
    assert proof.assurance_tier == receipts["assurance_tier"]
    assert proof.public_key == receipts["user_public_key"]
    assert proof.signed_at == receipts["signed_at"]
    assert proof.decision == "approve"
    assert proof.terms == receipts["expected_terms"]
    # The bytes that were verified, not a re-encode of the parsed envelope.
    assert json.loads(proof.signed_message) == dict(proof.envelope)


def test_every_reject_vector_raises_and_says_why(receipts):
    """Each fixture case tagged `user_signature` must fail, and none may fail silently
    by returning something falsy."""
    checked = 0
    for name, case in receipts["cases"].items():
        if case.get("error") != "user_signature":
            continue
        checked += 1
        with pytest.raises(UserProofError) as raised:
            verify_user_proof(_claims(receipts, name), expected_issuer=receipts["issuer"])
        assert str(raised.value), name
    assert checked >= 15, "the reject vectors went missing from the fixtures"


def test_the_signature_itself_is_what_rejects_a_swapped_message(receipts):
    """`user_message_swapped` passes every field cross-check. Only the curve arithmetic
    separates it from a genuine receipt — proof the field checks are not doing this
    work by accident."""
    claims = _claims(receipts, "user_message_swapped")
    raw = decode_signed_message(claims["yanez_signed_message"])
    envelope = json.loads(raw)

    # Everything step 5 compares still lines up.
    assert envelope["authorization_request_id"] == claims["jti"]
    assert envelope["yid"] == claims["sub"]
    assert envelope["assurance_tier"] == claims["yanez_assurance_tier"]
    assert terms_equal(envelope["terms"], claims["yanez_terms"])
    # And the signature does not cover these bytes.
    assert not verify_bls_signature(raw, claims["yanez_user_signature"],
                                    claims["yanez_user_public_key"])


def test_bls_verification_accepts_either_hex_spelling(receipts):
    claims = _claims(receipts)
    raw = decode_signed_message(claims["yanez_signed_message"])
    bare_key = claims["yanez_user_public_key"][2:]
    bare_sig = claims["yanez_user_signature"][2:]

    assert verify_bls_signature(raw, claims["yanez_user_signature"], claims["yanez_user_public_key"])
    assert verify_bls_signature(raw, bare_sig, bare_key)
    assert verify_bls_signature(raw, bare_sig.upper(), bare_key.upper())


def test_malformed_crypto_inputs_return_false_rather_than_raising(receipts):
    """An executor's request handler must not see a curve exception."""
    claims = _claims(receipts)
    raw = decode_signed_message(claims["yanez_signed_message"])
    key = claims["yanez_user_public_key"]

    for bad_signature in ("", "0x", "zz" * 96, "ab" * 95, "0x" + "00" * 96):
        assert verify_bls_signature(raw, bad_signature, key) is False
    for bad_key in ("", "0x" + "00" * 48, "ff" * 48, "ab" * 47):
        assert verify_bls_signature(raw, claims["yanez_user_signature"], bad_key) is False


def test_signed_message_must_be_canonical_base64url(receipts):
    claims = _claims(receipts)
    raw = decode_signed_message(claims["yanez_signed_message"])

    assert base64.urlsafe_b64encode(raw).rstrip(b"=").decode() == claims["yanez_signed_message"]
    for bad in ("", "!!!!", claims["yanez_signed_message"] + "=", "a" * 30_000):
        with pytest.raises(UserProofError):
            decode_signed_message(bad)


def test_duplicate_keys_in_the_signed_message_are_refused(receipts):
    """Two verifiers reading one byte string must not compare different values. The
    signature over such a message is genuine; the message is the problem."""
    from yanez_authz.proof import parse_json_strict

    with pytest.raises(ValueError, match="duplicate"):
        parse_json_strict(b'{"decision":"approve","decision":"reject"}')


# --- policy gates an executor applies on top ---


def test_assurance_floor_is_a_policy_denial_not_a_bad_receipt(jwks, receipts):
    verifier = _verifier(jwks)
    low = receipts["cases"]["assurance_tier_low"]
    terms, now = receipts["expected_terms"], receipts["now_fresh"]

    assert verifier.verify(low["artifact"], terms, 900, now=now).assurance_tier == "low"
    assert verifier.verify(low["artifact"], terms, 900, now=now,
                           min_assurance_tier="low").assurance_tier == "low"
    # Genuine, and not strong enough. A different problem from a forged receipt, and
    # the caller must be able to tell them apart.
    with pytest.raises(ConsentPolicyError):
        verifier.verify(low["artifact"], terms, 900, now=now, min_assurance_tier="high")

    high = receipts["cases"]["valid"]["artifact"]
    assert verifier.verify(high, terms, 900, now=now, min_assurance_tier="high").jti
    with pytest.raises(ValueError):
        verifier.verify(high, terms, 900, now=now, min_assurance_tier="paranoid")


def test_registry_check_normalizes_both_spellings(receipts, user_keys):
    """The receipt claim carries `0x` and the registry does not. A raw string compare
    finds nothing, which reads as "this key is not the user's" — the most alarming
    possible way to be wrong."""
    key, tier = receipts["user_public_key"], receipts["assurance_tier"]

    assert key.startswith("0x") and not user_keys["keys"][0]["public_key"].startswith("0x")
    assert key_is_registered(key, tier, user_keys["keys"])
    assert key_is_registered(key[2:], tier, user_keys["keys"])
    assert key_is_registered(key.upper(), tier, user_keys["keys"])

    # Right key, wrong tier: the registry holds it at `high`, not at `medium`.
    assert not key_is_registered(key, "medium", user_keys["keys"])
    # A key recorded with no tier can never verify a decision, so it never matches.
    assert not key_is_registered("cc" * 48, None, user_keys["keys"])
    assert not key_is_registered("dd" * 48, tier, user_keys["keys"])
    assert not key_is_registered(key, tier, [])
    assert not key_is_registered(key, tier, "not a list")


# --- consumption ---


def test_consumer_token_is_required_to_consume_and_refused_otherwise(jwks, receipts):
    verifier = _verifier(jwks)
    artifact = receipts["cases"]["valid"]["artifact"]

    for bad in (None, "", "   "):
        with pytest.raises(ValueError, match="consumer_token"):
            verifier.introspect(artifact, consume=True, consumer_token=bad)
    # Inspection is not consumption; a polling caller has nothing to own.
    with pytest.raises(ValueError, match="only meaningful"):
        verifier.introspect(artifact, consume=False, consumer_token=TOKEN)


def test_the_token_travels_on_the_wire_only_when_consuming(jwks, receipts, http_fixtures):
    bodies = []

    def introspect(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=http_fixtures["introspect_first_consume"])

    verifier = _verifier(jwks, extra_handler=introspect, now=lambda: receipts["now_fresh"])
    artifact = receipts["cases"]["valid"]["artifact"]

    verifier.introspect(artifact, consume=False)
    verifier.introspect(artifact, consume=True, consumer_token=TOKEN)

    assert "consumer_token" not in bodies[0]
    assert bodies[1]["consumer_token"] == TOKEN


def test_reservation_held_is_recovery_and_carries_the_receipt(jwks, receipts, http_fixtures):
    """The lost-response case the token exists for. Distinct from already_consumed:
    that one is settled against you, this one is yours to reconcile."""
    verifier = _verifier(
        jwks,
        extra_handler=lambda r: httpx.Response(
            200, json=http_fixtures["introspect_reservation_held"]),
        now=lambda: receipts["now_fresh"])

    with pytest.raises(ReservationHeldError) as raised:
        verifier.authorize_action(receipts["cases"]["valid"]["artifact"],
                                  receipts["expected_terms"], 900,
                                  consume=True, consumer_token=TOKEN)

    assert raised.value.receipt is not None
    assert raised.value.receipt.jti == http_fixtures["introspect_reservation_held"]["jti"]
    assert "idempotency" in str(raised.value)


def test_a_receipt_without_a_user_proof_is_a_user_signature_failure(jwks, receipts):
    """It records a real approval. It is not a user-signed one, and the error says so
    rather than reporting a generic missing claim."""
    verifier = _verifier(jwks)
    with pytest.raises(UserSignatureError, match="no user proof"):
        verifier.verify(receipts["cases"]["user_proof_absent"]["artifact"],
                        receipts["expected_terms"], 900, now=receipts["now_fresh"])
