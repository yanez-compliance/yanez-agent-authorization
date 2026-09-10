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


class UserSignatureError(ReceiptVerificationError):
    """The approver's own signature is missing, malformed, or does not cover this
    decision. The Yanez JWT may be perfectly valid; that is not enough. Never execute.

    A subclass of `ReceiptVerificationError`, so code that catches the general case
    still catches this one.
    """


class ReservationHeldError(YanezAuthzError):
    """**You** already hold this receipt's reservation, from an earlier attempt whose
    response you lost. This is a successful recovery, not a refusal.

    The opposite of `AlreadyConsumedError`, which means somebody else holds it and you
    must never act. Here the receipt is yours to spend, and the danger is the reverse:
    your earlier attempt may already have performed the downstream action.

    **Reconcile, do not restart.** Re-send or query the downstream system with the
    ORIGINAL idempotency key you derived from `jti`. Do not request a new approval —
    that mints a second `jti` for an action that may already have succeeded, and the
    duplicate is invisible to every consumption check. See spec §4.8.

    `.receipt` carries the verified receipt so you can reconcile without re-verifying.
    """

    def __init__(self, message: str, receipt: object | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


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
