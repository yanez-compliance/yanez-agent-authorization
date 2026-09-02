from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

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
    valid: bool
    reason: Optional[str] = None
    consumed_now: Optional[bool] = None
    sub: Optional[str] = None
    jti: Optional[str] = None
    decided_at: Optional[int] = None
    consent_not_after: Optional[int] = None
    terms: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class VerifiedReceipt:
    """A receipt that passed signature, issuer, claim-profile, exact-terms, freshness,
    and consent checks. Holding one means "permission to act now", not just validity."""
    sub: str
    jti: str
    agent_key_id: str
    decided_at: int
    match_overlap: int
    terms: dict[str, Any]
    consent_not_after: Optional[int] = None
