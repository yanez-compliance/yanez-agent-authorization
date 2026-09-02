"""Typed errors, one per failure class of the agent-authorization contract.

Messages never contain the agent key, the Authorization header, or a raw artifact —
only HTTP status and the server's sanitized detail string.
"""
from __future__ import annotations

from typing import Optional


class YanezAuthzError(Exception):
    """Base for every error this SDK raises deliberately."""


class AuthenticationError(YanezAuthzError):
    """Missing, malformed, or revoked agent key. Do not retry; reissue the key."""


class InvalidRequestError(YanezAuthzError):
    """Invalid terms, time, or schema. Fix the request."""


class TermsTooLargeError(YanezAuthzError):
    """Terms exceed the server's 4 KB cap. Reduce without losing material facts."""


class RateLimitError(YanezAuthzError):
    """Request or pending limit reached. Wait; never create a replacement loop."""


class ConflictError(YanezAuthzError):
    """Idempotency mismatch or terminal transition. Inspect the original request."""


class NotFoundError(YanezAuthzError):
    """Unknown or cross-key request id. The server discloses nothing more."""


class FeatureUnavailableError(YanezAuthzError):
    """Authorization routes are disabled or not deployed. Operator action needed."""


class TransportError(YanezAuthzError):
    """Timeout, TLS, DNS, connection failure — or an unexpected redirect, which is
    never followed with credentials."""


class ReceiptVerificationError(YanezAuthzError):
    """Bad signature, issuer, claims, or exact terms. Never execute the action."""


class ConsentPolicyError(YanezAuthzError):
    """The receipt is genuine but stale or past the user's bound. Request new approval."""


class AlreadyConsumedError(YanezAuthzError):
    """A genuine single-use receipt was previously spent. Never execute again."""


def error_for_status(status: int, detail: Optional[str], *, create: bool = False) -> YanezAuthzError:
    """Map a non-2xx agent-API response to a typed error.

    A 404 means two different things by route: on create, the whole router is absent
    (feature disabled); on get, the request id is unknown or belongs to another key.
    """
    message = detail or f"HTTP {status}"
    if status == 401:
        return AuthenticationError(message)
    if status == 404:
        return FeatureUnavailableError(message) if create else NotFoundError(message)
    if status == 409:
        return ConflictError(message)
    if status == 413:
        return TermsTooLargeError(message)
    if status == 429:
        return RateLimitError(message)
    if status in (400, 422):
        return InvalidRequestError(message)
    return TransportError(f"unexpected HTTP {status}")
