"""Verifier behavior against the shared conformance fixtures — the same cases the
TypeScript SDK runs, so both languages reach the same verdict on every receipt."""
from __future__ import annotations

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from yanez_authz import (
    AlreadyConsumedError,
    ConsentPolicyError,
    InvalidRequestError,
    ReceiptVerificationError,
    ReceiptVerifier,
    TransportError,
)

BASE = "https://yanez.test"
ISSUER = "https://yanez.test"

_ERRORS = {"verification": ReceiptVerificationError, "consent_policy": ConsentPolicyError}


def _signed(receipts, **overrides) -> str:
    """The conformance receipt re-signed under the fixture key with claim overrides."""
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))  # generate_fixtures seed
    claims = jwt.decode(receipts["cases"]["valid"]["artifact"],
                        options={"verify_signature": False})
    return jwt.encode({**claims, **overrides}, key, algorithm="EdDSA",
                      headers={"kid": "authz_test_1"})


def _verifier(jwks, extra_handler=None, **kw) -> tuple[ReceiptVerifier, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/authz/public-keys":
            return httpx.Response(200, json=jwks)
        if extra_handler is not None:
            return extra_handler(request)
        return httpx.Response(404, json={"detail": "unknown"})

    v = ReceiptVerifier(BASE, ISSUER, transport=httpx.MockTransport(handler), **kw)
    return v, calls


def test_conformance_cases(jwks, receipts):
    verifier, _ = _verifier(jwks)
    for name, case in receipts["cases"].items():
        now = case.get("now", receipts["now_fresh"])
        expected_terms = case.get("expected_terms", receipts["expected_terms"])
        if case["ok"]:
            receipt = verifier.verify(case["artifact"], expected_terms, 900, now=now)
            assert receipt.jti and receipt.sub, name
            assert receipt.terms == receipts["expected_terms"], name
            assert receipt.match_overlap >= 0, name
        else:
            with pytest.raises(_ERRORS[case["error"]]):
                verifier.verify(case["artifact"], expected_terms, 900, now=now)
            # pytest.raises message loses `name`; re-raise manually if this ever fails.


def test_valid_receipt_exposes_the_full_decoded_profile(jwks, receipts):
    verifier, _ = _verifier(jwks)
    case = receipts["cases"]["valid"]
    receipt = verifier.verify(case["artifact"], receipts["expected_terms"], 900,
                              now=receipts["now_fresh"])
    assert receipt.decided_at == receipts["decided_at"]
    assert receipt.agent_key_id.startswith("yak_")
    assert receipt.consent_not_after is None


def test_unknown_kids_do_not_refetch_within_the_cooldown(jwks, receipts):
    """Anyone can submit garbage kids; that must not turn into a fetch per receipt."""
    verifier, calls = _verifier(jwks)
    case = receipts["cases"]["unknown_kid"]
    for _ in range(5):
        with pytest.raises(ReceiptVerificationError):
            verifier.verify(case["artifact"], receipts["expected_terms"], 900,
                            now=receipts["now_fresh"])
    assert calls.count("/api/authz/public-keys") == 1


def test_rotated_kid_verifies_after_the_cooldown_refresh(jwks, receipts):
    """The rotation path the refresh exists for: after the cooldown, an unknown kid
    fetches again and the second fetch carries the new kid."""
    rotated = {"keys": [{**jwks["keys"][0], "kid": "authz_retired"}]}
    fetches = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetches.append(1)
        return httpx.Response(200, json=jwks if len(fetches) == 1 else rotated)

    verifier = ReceiptVerifier(BASE, ISSUER, transport=httpx.MockTransport(handler))
    verifier.verify(receipts["cases"]["valid"]["artifact"], receipts["expected_terms"],
                    900, now=receipts["now_fresh"])
    verifier._keys_fetched_at -= 31  # the cooldown has elapsed
    case = receipts["cases"]["unknown_kid"]  # signed with kid authz_retired
    receipt = verifier.verify(case["artifact"], receipts["expected_terms"], 900,
                              now=receipts["now_fresh"])
    assert receipt.jti and len(fetches) == 2


def test_key_set_is_cached_between_verifies(jwks, receipts):
    verifier, calls = _verifier(jwks)
    case = receipts["cases"]["valid"]
    for _ in range(3):
        verifier.verify(case["artifact"], receipts["expected_terms"], 900,
                        now=receipts["now_fresh"])
    assert calls.count("/api/authz/public-keys") == 1


def test_introspect_and_authorize_action_map_consumption(jwks, receipts, http_fixtures):
    responses = iter([http_fixtures["introspect_first_consume"],
                      http_fixtures["introspect_repeat_consume"]])

    def introspect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    verifier, _ = _verifier(jwks, extra_handler=introspect,
                            now=lambda: receipts["now_fresh"])
    artifact = receipts["cases"]["valid"]["artifact"]

    receipt = verifier.authorize_action(artifact, receipts["expected_terms"], 900,
                                        consume=True)
    assert receipt.jti == http_fixtures["introspect_first_consume"]["jti"]

    # The repeat is a genuine receipt that must never authorize the action again.
    with pytest.raises(AlreadyConsumedError):
        verifier.authorize_action(artifact, receipts["expected_terms"], 900, consume=True)


def test_expected_issuer_is_mandatory_and_https_is_enforced():
    with pytest.raises(ValueError):
        ReceiptVerifier(BASE, "")
    with pytest.raises(ValueError):
        ReceiptVerifier("http://yanez.example", ISSUER)
    ReceiptVerifier("http://127.0.0.1:8001", ISSUER)  # loopback development is fine


def test_expected_sub_and_agent_key_bind_the_receipt(jwks, receipts):
    verifier, _ = _verifier(jwks)
    artifact = receipts["cases"]["valid"]["artifact"]
    terms, now = receipts["expected_terms"], receipts["now_fresh"]
    genuine = verifier.verify(artifact, terms, 900, now=now)
    bound = verifier.verify(artifact, terms, 900, now=now, expected_sub=genuine.sub,
                            expected_agent_key_id=genuine.agent_key_id)
    assert bound.jti == genuine.jti
    with pytest.raises(ReceiptVerificationError):
        verifier.verify(artifact, terms, 900, now=now, expected_sub="b" * 32)
    with pytest.raises(ReceiptVerificationError):
        verifier.authorize_action(artifact, terms, 900, consume=False,
                                  expected_agent_key_id="yak_someone_else")


def test_decided_at_in_the_future_is_rejected_beyond_clock_skew(jwks, receipts):
    verifier, _ = _verifier(jwks)
    terms, now = receipts["expected_terms"], receipts["now_fresh"]
    with pytest.raises(ReceiptVerificationError):
        verifier.verify(_signed(receipts, iat=now + 3600, yanez_decided_at=now + 3600),
                        terms, 900, now=now)
    assert verifier.verify(_signed(receipts, iat=now + 30, yanez_decided_at=now + 30),
                           terms, 900, now=now).jti


def test_null_or_mistyped_required_claims_are_rejected(jwks, receipts):
    verifier, _ = _verifier(jwks)
    for bad in (_signed(receipts, yanez_agent_key_id=None), _signed(receipts, sub=12345)):
        with pytest.raises(ReceiptVerificationError):
            verifier.verify(bad, receipts["expected_terms"], 900, now=receipts["now_fresh"])


def test_terms_comparison_keeps_bool_and_int_distinct(jwks, receipts):
    """Python's True == 1 must not reach a verdict the TypeScript SDK would not."""
    verifier, _ = _verifier(jwks)
    terms, now = receipts["expected_terms"], receipts["now_fresh"]
    artifact = _signed(receipts, yanez_terms={**terms, "gift": True})
    with pytest.raises(ReceiptVerificationError):
        verifier.verify(artifact, {**terms, "gift": 1}, 900, now=now)
    assert verifier.verify(artifact, {**terms, "gift": True}, 900, now=now).jti


def test_malformed_key_set_is_tolerated_per_entry_and_refused_per_body(jwks, receipts):
    good = jwks["keys"][0]
    artifact, terms, now = (receipts["cases"]["valid"]["artifact"],
                            receipts["expected_terms"], receipts["now_fresh"])
    verifier, _ = _verifier({"keys": [{k: v for k, v in good.items() if k != "x"}, good]})
    assert verifier.verify(artifact, terms, 900, now=now).jti  # bad entry skipped
    verifier, _ = _verifier("not a key set")
    with pytest.raises(TransportError):
        verifier.verify(artifact, terms, 900, now=now)


def test_introspection_outcomes_are_typed(jwks, receipts, http_fixtures):
    artifact, terms = receipts["cases"]["valid"]["artifact"], receipts["expected_terms"]
    outcomes = [
        (httpx.Response(200, json=http_fixtures["introspect_bad_signature"]),
         ReceiptVerificationError),
        (httpx.Response(200, json={"valid": True, "reason": "consent_expired",
                                   "consumed_now": False}), ConsentPolicyError),
        (httpx.Response(422, json={"detail": "artifact too large"}), InvalidRequestError),
    ]
    for response, exc in outcomes:
        verifier, _ = _verifier(jwks, extra_handler=lambda r, response=response: response,
                                now=lambda: receipts["now_fresh"])
        with pytest.raises(exc):
            verifier.authorize_action(artifact, terms, 900, consume=True)


def test_consume_requires_confirmed_consumption(jwks, receipts):
    artifact, terms = receipts["cases"]["valid"]["artifact"], receipts["expected_terms"]
    for body in ({"valid": True, "consumed_now": False}, {"valid": True}):
        verifier, _ = _verifier(jwks, extra_handler=lambda r, body=body: httpx.Response(200, json=body),
                                now=lambda: receipts["now_fresh"])
        with pytest.raises(ReceiptVerificationError):
            verifier.authorize_action(artifact, terms, 900, consume=True)


def test_numeric_date_claims_must_be_integers(jwks, receipts):
    verifier, _ = _verifier(jwks)
    terms, now = receipts["expected_terms"], receipts["now_fresh"]
    for bad in (_signed(receipts, yanez_consent_not_after="not-a-date"),
                _signed(receipts, yanez_decided_at="x")):
        with pytest.raises(ReceiptVerificationError):
            verifier.verify(bad, terms, 900, now=now)
    # A JSON null bound is "no bound", the same verdict the TypeScript SDK reaches.
    receipt = verifier.verify(_signed(receipts, yanez_consent_not_after=None), terms, 900, now=now)
    assert receipt.consent_not_after is None


def test_profile_rejects_empty_ids_float_iat_and_non_object_terms(jwks, receipts):
    verifier, _ = _verifier(jwks)
    terms, now = receipts["expected_terms"], receipts["now_fresh"]
    decided_at = jwt.decode(receipts["cases"]["valid"]["artifact"],
                            options={"verify_signature": False})["yanez_decided_at"]
    for bad in (_signed(receipts, sub=""), _signed(receipts, jti=""),
                _signed(receipts, yanez_agent_key_id=""),
                # 1750000000.0 == 1750000000, so equality with decided_at alone would pass.
                _signed(receipts, iat=float(decided_at))):
        with pytest.raises(ReceiptVerificationError):
            verifier.verify(bad, terms, 900, now=now)
    # Equal to what the caller expects, but not an object: rejected on shape, not on terms.
    with pytest.raises(ReceiptVerificationError, match="must be an object"):
        verifier.verify(_signed(receipts, yanez_terms=["x"]), ["x"], 900, now=now)


def test_jwk_without_eddsa_alg_is_not_a_usable_key(jwks, receipts):
    good = jwks["keys"][0]
    artifact, terms, now = (receipts["cases"]["valid"]["artifact"],
                            receipts["expected_terms"], receipts["now_fresh"])
    for bad in ({k: v for k, v in good.items() if k != "alg"}, {**good, "alg": "RS256"}):
        verifier, _ = _verifier({"keys": [bad]})
        with pytest.raises(ReceiptVerificationError):
            verifier.verify(artifact, terms, 900, now=now)
