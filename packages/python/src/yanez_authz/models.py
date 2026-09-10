from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yanez_authz.proof import UserProof

# Wire statuses, verbatim. Exactly one per response; only `approved` carries an artifact.
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"
TERMINAL = frozenset({APPROVED, REJECTED, EXPIRED})


@dataclass(frozen=True)
class PendingAuthorization:
    request_id: str
    status: str
    decide_by: str
    idempotency_key: str
    replayed: bool  # True when the server answered from an earlier create


@dataclass(frozen=True)
class AuthorizationResult:
    request_id: str
    status: str
    artifact: Optional[str] = None
    # ISO timestamps as the server sent them; parse only if you need arithmetic.
    consent_not_after: Optional[str] = None
    decided_at: Optional[str] = None


@dataclass(frozen=True)
class IntrospectionResult:
    """What the issuer says about a receipt, and whether you may act on it.

    **Never gate on `valid`.** It answers "is this receipt genuine", which stays true
    forever and says nothing about permission. Whether you may act is `consumed_now`
    plus `reason`. See spec §4.8.

    The proof fields mirror the receipt's §4.6 claims. They are the issuer's report of
    the claims, not an independent check — verifying the user's signature locally is
    `verify_user_proof`, and no server round trip can do it for you.
    """
    valid: bool
    reason: Optional[str] = None
    consumed_now: Optional[bool] = None
    sub: Optional[str] = None
    jti: Optional[str] = None
    decided_at: Optional[int] = None
    consent_not_after: Optional[int] = None
    terms: Optional[dict[str, Any]] = None
    assurance_tier: Optional[str] = None
    user_public_key: Optional[str] = None
    user_signature: Optional[str] = None
    signed_message: Optional[str] = None
    user_sig_alg: Optional[str] = None


@dataclass(frozen=True)
class VerifiedReceipt:
    """A receipt that passed BOTH signatures, plus issuer, claim-profile, exact-terms,
    freshness, and consent checks. Holding one means "permission to act now", not just
    validity.

    `assurance_tier` is the tier the approver's scan actually reached, taken from the
    bytes they signed rather than from Yanez's account of it — the two were checked
    against each other. Gate on it against your own floor for the value at risk.
    """
    sub: str
    jti: str
    agent_key_id: str
    decided_at: int
    match_overlap: int
    terms: dict[str, Any]
    assurance_tier: str
    user_proof: UserProof
    consent_not_after: Optional[int] = None

    @property
    def signed_at(self) -> int:
        """When the approver's device signed, by its own clock. See `decided_at` for
        when Yanez recorded the decision."""
        return self.user_proof.signed_at
