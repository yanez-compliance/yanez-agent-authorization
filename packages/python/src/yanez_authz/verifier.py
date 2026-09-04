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
    TransportError,
)
from yanez_authz.models import IntrospectionResult, VerifiedReceipt

_KEY_CACHE_TTL_SECONDS = 600
# An unknown kid may force one early refresh (key rotation), but a stream of garbage
# kids must not become a stream of key-set fetches.
_KEY_REFRESH_COOLDOWN_SECONDS = 30
_CLOCK_SKEW_SECONDS = 60

_REQUIRED_CLAIMS = ("sub", "jti", "iat", "yanez_agent_key_id", "yanez_decision",
                    "yanez_decided_at", "yanez_match_overlap", "yanez_terms")
_STRING_CLAIMS = ("sub", "jti", "yanez_agent_key_id")
# NumericDate claims the SDK does arithmetic on; a signed string here must be a typed
# rejection, never a TypeError or a comparison that silently passes.
_INTEGER_CLAIMS = ("iat", "yanez_decided_at", "yanez_consent_not_after")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _terms_equal(a: Any, b: Any) -> bool:
    """Deep JSON equality with bool distinct from int, the verdict the TypeScript SDK's
    isDeepStrictEqual reaches; plain `==` would let {"n": true} match {"n": 1}."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_terms_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(map(_terms_equal, a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b  # JSON has one number type
    return type(a) is type(b) and a == b


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
               expected_agent_key_id: Optional[str] = None) -> VerifiedReceipt:
        """Signature + profile + exact terms + freshness + consent bound.

        Freshness (`max_age_seconds`, against `yanez_decided_at`) and the user's
        `yanez_consent_not_after` are THIS relying party's gate on acting; neither
        affects whether the receipt is genuine. There is deliberately no `exp`
        requirement — a receipt still verifies years later, when the dispute happens.

        A genuine receipt says that *some* YID approved these terms. When the terms do
        not name the account, pass `expected_sub` (and/or `expected_agent_key_id`) so
        an approval by one user can never authorize an action for another.
        """
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
        if not _terms_equal(claims["yanez_terms"], expected_terms):
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

        return VerifiedReceipt(
            sub=claims["sub"], jti=claims["jti"],
            agent_key_id=claims["yanez_agent_key_id"], decided_at=decided_at,
            match_overlap=overlap, terms=claims["yanez_terms"],
            consent_not_after=not_after,
        )

    def introspect(self, artifact: str, *, consume: bool = False) -> IntrospectionResult:
        """Online check; `consume=True` permanently spends the receipt's jti."""
        try:
            response = self._http.post("/api/authz/introspect",
                                       json={"artifact": artifact, "consume": consume})
        except httpx.HTTPError as e:
            raise TransportError(type(e).__name__) from None
        _raise_for(response, create=True)  # a 404 here means the feature is absent
        data = response.json()
        return IntrospectionResult(**{k: data.get(k) for k in (
            "valid", "reason", "consumed_now", "sub", "jti",
            "decided_at", "consent_not_after", "terms")})

    def authorize_action(self, artifact: str, expected_terms: dict[str, Any],
                         max_age_seconds: int, *, consume: bool,
                         expected_sub: Optional[str] = None,
                         expected_agent_key_id: Optional[str] = None) -> VerifiedReceipt:
        """Everything the action boundary needs, in order — but never the action itself.

        For a single-use action pass consume=True and call this immediately before
        executing. If the action then fails, the receipt stays spent: retry means a
        new authorization, because consumption and a third-party side effect cannot
        be one atomic transaction.
        """
        receipt = self.verify(artifact, expected_terms, max_age_seconds,
                              expected_sub=expected_sub,
                              expected_agent_key_id=expected_agent_key_id)
        if consume:
            result = self.introspect(artifact, consume=True)
            if result.valid and result.reason == "already_consumed":
                raise AlreadyConsumedError("receipt was already spent")
            if result.valid and result.reason == "consent_expired":
                raise ConsentPolicyError("past the user's consent bound")
            if not result.valid:
                raise ReceiptVerificationError(result.reason or "invalid receipt")
            if result.consumed_now is not True:
                # Only a consumption the server confirmed authorizes a single-use action.
                raise ReceiptVerificationError(
                    "receipt was not consumed" + (f": {result.reason}" if result.reason else ""))
        return receipt
