from __future__ import annotations

import base64
import math
import time
from typing import Any, Callable, Optional

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from yanez_authz.async_client import _raise_for, require_trusted_origin
from yanez_authz.errors import (
    AlreadyConsumedError,
    ConsentPolicyError,
    ReceiptVerificationError,
    ReservationHeldError,
    TransportError,
    UserSignatureError,
)
from yanez_authz.models import IntrospectionResult, VerifiedReceipt
from yanez_authz.proof import UserProofError, terms_equal, verify_user_proof

_KEY_CACHE_TTL_SECONDS = 600
# An unknown kid may force one early refresh (key rotation), but a stream of garbage
# kids must not become a stream of key-set fetches.
_KEY_REFRESH_COOLDOWN_SECONDS = 30
_CLOCK_SKEW_SECONDS = 60

_REQUIRED_CLAIMS = ("sub", "jti", "iat", "yanez_agent_key_id", "yanez_decision",
                    "yanez_decided_at", "yanez_match_overlap", "yanez_terms")

# The five §4.6 proof claims are equally required, but `verify_user_proof` enforces
# them so their absence raises `UserSignatureError` rather than the generic missing-claim
# error. A receipt minted before signed approvals fails there, and is never reported as
# a user-signed approval.

#: Ascending assurance. `medium` satisfies a `medium` floor and a `low` one, never `high`.
_TIER_ORDER = ("low", "medium", "high")
_STRING_CLAIMS = ("sub", "jti", "yanez_agent_key_id")
# NumericDate claims the SDK does arithmetic on; a signed string here must be a typed
# rejection, never a TypeError or a comparison that silently passes.
_INTEGER_CLAIMS = ("iat", "yanez_decided_at", "yanez_consent_not_after")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class ReceiptVerifier:
    """Relying-party verification. Needs no agent key — a receipt is portable proof.

    `expected_issuer` is mandatory: the unverified `iss` claim is never trusted to
    name its own authority.
    """

    def __init__(self, base_url: str, expected_issuer: str, *,
                 timeout_seconds: float = 10.0,
                 now: Callable[[], float] = time.time,
                 transport: Optional[httpx.BaseTransport] = None) -> None:
        if not expected_issuer:
            raise ValueError("expected_issuer is mandatory")
        self._base_url = require_trusted_origin(base_url)
        self._issuer = expected_issuer
        self._now = now
        self._http = httpx.Client(base_url=self._base_url, timeout=timeout_seconds,
                                  follow_redirects=False, transport=transport)
        self._keys: dict[str, Ed25519PublicKey] = {}
        self._keys_fetched_at: Optional[float] = None

    # --- key set ---

    def _fetch_keys(self) -> None:
        try:
            response = self._http.get("/api/authz/public-keys")
        except httpx.HTTPError as e:
            raise TransportError(type(e).__name__) from None
        _raise_for(response, create=True)  # a 404 here means the feature is absent
        try:
            entries = response.json()["keys"]
            if not isinstance(entries, list):
                raise TypeError
        except (ValueError, TypeError, KeyError):
            raise TransportError("malformed key set") from None
        keys = {}
        for jwk in entries:
            if not isinstance(jwk, dict) or jwk.get("kty") != "OKP" \
                    or jwk.get("crv") != "Ed25519" or jwk.get("alg") != "EdDSA" \
                    or not jwk.get("kid"):
                continue
            try:
                keys[jwk["kid"]] = Ed25519PublicKey.from_public_bytes(
                    _b64url_decode(jwk["x"]))
            except (KeyError, TypeError, ValueError):
                continue  # one bad entry must not take the whole key set down
        self._keys = keys
        self._keys_fetched_at = time.monotonic()

    def _key_for(self, kid: str) -> Ed25519PublicKey:
        """Cached for ten minutes; an unknown kid forces one early refresh (at most one
        per cooldown) so a freshly rotated key verifies without a restart. Never
        selected by algorithm."""
        age = (math.inf if self._keys_fetched_at is None
               else time.monotonic() - self._keys_fetched_at)
        if age > _KEY_CACHE_TTL_SECONDS:
            self._fetch_keys()
        elif kid not in self._keys and age > _KEY_REFRESH_COOLDOWN_SECONDS:
            self._fetch_keys()
        key = self._keys.get(kid)
        if key is None:
            raise ReceiptVerificationError(f"unknown signing key {kid!r}")
        return key

    # --- verification ---

    def verify(self, artifact: str, expected_terms: dict[str, Any],
               max_age_seconds: int, *, now: Optional[float] = None,
               expected_sub: Optional[str] = None,
               expected_agent_key_id: Optional[str] = None,
               min_assurance_tier: Optional[str] = None) -> VerifiedReceipt:
        """Both signatures + profile + exact terms + freshness + consent bound.

        Freshness (`max_age_seconds`, against `yanez_decided_at`) and the user's
        `yanez_consent_not_after` are THIS relying party's gate on acting; neither
        affects whether the receipt is genuine. There is deliberately no `exp`
        requirement — a receipt still verifies years later, when the dispute happens.

        A genuine receipt says that *some* YID approved these terms. When the terms do
        not name the account, pass `expected_sub` (and/or `expected_agent_key_id`) so
        an approval by one user can never authorize an action for another.

        Two signatures are checked, not one. After the Yanez JWT verifies, the
        approver's own BLS signature is verified over the exact bytes they signed and
        every field in those bytes is checked against this receipt (§4.7 steps 4-5). A
        failure there raises `UserSignatureError`.

        `min_assurance_tier` is your floor for the value at risk — `"low"`, `"medium"`,
        or `"high"`. It is a policy gate, so falling short raises `ConsentPolicyError`,
        not a verification error: the receipt is genuine, it just is not strong enough
        for what you were about to do.
        """
        if min_assurance_tier is not None and min_assurance_tier not in _TIER_ORDER:
            raise ValueError(f"min_assurance_tier must be one of {_TIER_ORDER}")
        current = self._now() if now is None else now

        try:
            header = jwt.get_unverified_header(artifact)
        except jwt.PyJWTError as e:
            raise ReceiptVerificationError(str(e)) from None
        # Pinned algorithm; the token's own header is never an allow-list.
        if header.get("alg") != "EdDSA" or not header.get("kid"):
            raise ReceiptVerificationError("receipt must be EdDSA with a kid")

        key = self._key_for(header["kid"])
        try:
            claims = jwt.decode(
                artifact, key, algorithms=["EdDSA"], issuer=self._issuer,
                leeway=_CLOCK_SKEW_SECONDS,
            )
        except jwt.PyJWTError as e:
            raise ReceiptVerificationError(str(e)) from None

        for name in _REQUIRED_CLAIMS:
            if claims.get(name) is None:
                raise ReceiptVerificationError(f"missing claim {name}")
        for name in _STRING_CLAIMS:
            if not isinstance(claims[name], str) or not claims[name]:
                raise ReceiptVerificationError(f"claim {name} must be a non-empty string")
        for name in _INTEGER_CLAIMS:
            value = claims.get(name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ReceiptVerificationError(f"claim {name} must be an integer NumericDate")
        if claims["yanez_decision"] != "approved":
            raise ReceiptVerificationError("receipt is not an approval")
        if expected_sub is not None and claims["sub"] != expected_sub:
            raise ReceiptVerificationError("sub does not match expected_sub")
        if expected_agent_key_id is not None and claims["yanez_agent_key_id"] != expected_agent_key_id:
            raise ReceiptVerificationError(
                "yanez_agent_key_id does not match expected_agent_key_id")
        if claims["iat"] != claims["yanez_decided_at"]:
            raise ReceiptVerificationError("iat and yanez_decided_at disagree")
        overlap = claims["yanez_match_overlap"]
        # Any non-negative integer: the issuer's block count and threshold are its
        # policy at signing time, not part of this public contract.
        if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0:
            raise ReceiptVerificationError("yanez_match_overlap must be a non-negative integer")
        if not isinstance(claims["yanez_terms"], dict):
            raise ReceiptVerificationError("yanez_terms must be an object")
        if not terms_equal(claims["yanez_terms"], expected_terms):
            # Deep equality, no ignored or wildcard fields: changed terms mean a new
            # authorization, never a reused receipt.
            raise ReceiptVerificationError("terms do not match the approved terms")

        decided_at = claims["yanez_decided_at"]
        not_after = claims.get("yanez_consent_not_after")
        if decided_at > current + _CLOCK_SKEW_SECONDS:
            raise ReceiptVerificationError("yanez_decided_at is in the future")
        if current - decided_at > max_age_seconds:
            raise ConsentPolicyError(
                f"approval is {int(current - decided_at)}s old, policy allows {max_age_seconds}s")
        if not_after is not None and current > not_after:
            raise ConsentPolicyError("past the user's consent bound")

        # The user's own signature, last: everything above is cheap, and this is the
        # only step that does elliptic-curve work.
        try:
            user_proof = verify_user_proof(claims, expected_issuer=self._issuer)
        except UserProofError as e:
            raise UserSignatureError(str(e)) from None

        tier = user_proof.assurance_tier
        if min_assurance_tier is not None:
            if tier not in _TIER_ORDER:
                raise UserSignatureError(f"unknown assurance tier {tier!r}")
            if _TIER_ORDER.index(tier) < _TIER_ORDER.index(min_assurance_tier):
                raise ConsentPolicyError(
                    f"approval is {tier} assurance, policy requires {min_assurance_tier}")

        return VerifiedReceipt(
            sub=claims["sub"], jti=claims["jti"],
            agent_key_id=claims["yanez_agent_key_id"], decided_at=decided_at,
            match_overlap=overlap, terms=claims["yanez_terms"],
            assurance_tier=tier, user_proof=user_proof,
            consent_not_after=not_after,
        )

    def introspect(self, artifact: str, *, consume: bool = False,
                   consumer_token: Optional[str] = None) -> IntrospectionResult:
        """Online check; `consume=True` permanently spends the receipt's jti.

        `consumer_token` is REQUIRED when consuming and rejected otherwise. It is your
        own opaque, durable string identifying this attempt, and you must reuse the
        same one when retrying after a lost response — that is how the server tells
        your earlier attempt from another holder's. The server never generates one: a
        server-minted token would be lost with the response it travelled in, which is
        the exact failure the token exists to survive.

        Inspection is not consumption. A polling or audit caller passes neither.
        """
        if consume:
            if not consumer_token or not consumer_token.strip():
                raise ValueError("consumer_token is required when consume=True")
        elif consumer_token is not None:
            raise ValueError("consumer_token is only meaningful when consume=True")
        body: dict[str, Any] = {"artifact": artifact, "consume": consume}
        if consume:
            body["consumer_token"] = consumer_token
        try:
            response = self._http.post("/api/authz/introspect", json=body)
        except httpx.HTTPError as e:
            raise TransportError(type(e).__name__) from None
        _raise_for(response, create=True)  # a 404 here means the feature is absent
        data = response.json()
        return IntrospectionResult(**{k: data.get(k) for k in (
            "valid", "reason", "consumed_now", "sub", "jti",
            "decided_at", "consent_not_after", "terms",
            "assurance_tier", "user_public_key", "user_signature",
            "signed_message", "user_sig_alg")})

    def authorize_action(self, artifact: str, expected_terms: dict[str, Any],
                         max_age_seconds: int, *, consume: bool,
                         consumer_token: Optional[str] = None,
                         expected_sub: Optional[str] = None,
                         expected_agent_key_id: Optional[str] = None,
                         min_assurance_tier: Optional[str] = None) -> VerifiedReceipt:
        """Everything the action boundary needs, in order — but never the action itself.

        For a single-use action pass `consume=True` with your `consumer_token`, and
        call this immediately before executing. Write the token and an idempotency key
        derived from `jti` durably BEFORE calling: both must survive the crash they
        exist to recover from.

        Three consume outcomes an executor must tell apart:

        - Returns normally — you won the reservation. Execute, carrying the
          idempotency key.
        - `ReservationHeldError` — you already held it from an attempt whose response
          was lost. Reconcile with the ORIGINAL idempotency key; the action may have
          happened. Never request a new approval.
        - `AlreadyConsumedError` — another holder won. Never execute.

        If the action fails after a successful consume, the receipt stays spent: retry
        means a new authorization, because consumption and a third-party side effect
        cannot be one atomic transaction.
        """
        receipt = self.verify(artifact, expected_terms, max_age_seconds,
                              expected_sub=expected_sub,
                              expected_agent_key_id=expected_agent_key_id,
                              min_assurance_tier=min_assurance_tier)
        if consume:
            result = self.introspect(artifact, consume=True, consumer_token=consumer_token)
            if result.valid and result.reason == "already_consumed":
                raise AlreadyConsumedError("receipt was already spent")
            if result.valid and result.reason == "reservation_held":
                raise ReservationHeldError(
                    "this consumer already holds the reservation; reconcile with the "
                    "original idempotency key rather than re-approving", receipt)
            if result.valid and result.reason == "consent_expired":
                raise ConsentPolicyError("past the user's consent bound")
            if not result.valid:
                raise ReceiptVerificationError(result.reason or "invalid receipt")
            if result.consumed_now is not True:
                # Only a consumption the server confirmed authorizes a single-use action.
                raise ReceiptVerificationError(
                    "receipt was not consumed" + (f": {result.reason}" if result.reason else ""))
        return receipt
