"""Yanez agent authorization SDK.

Two halves, deliberately separate:

- `AuthorizationClient` — the agent side: ask the key's owner to approve terms, poll
  for the decision. Needs the yak_ agent key.
- `ReceiptVerifier` — the relying-party side: verify and (for single-use actions)
  consume a signed receipt. Needs no credentials at all.
"""
from yanez_authz.async_client import AuthorizationClient
from yanez_authz.errors import (
    AlreadyConsumedError,
    AuthenticationError,
    ConflictError,
    ConsentPolicyError,
    FeatureUnavailableError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    ReceiptVerificationError,
    TermsTooLargeError,
    TransportError,
    YanezAuthzError,
)
from yanez_authz.models import (
    AuthorizationResult,
    IntrospectionResult,
    PendingAuthorization,
    VerifiedReceipt,
)
from yanez_authz.verifier import ReceiptVerifier

__version__ = "0.1.0"

__all__ = [
    "AuthorizationClient", "ReceiptVerifier",
    "PendingAuthorization", "AuthorizationResult", "IntrospectionResult", "VerifiedReceipt",
    "YanezAuthzError", "AuthenticationError", "InvalidRequestError", "TermsTooLargeError",
    "RateLimitError", "ConflictError", "NotFoundError", "FeatureUnavailableError",
    "TransportError", "ReceiptVerificationError", "ConsentPolicyError", "AlreadyConsumedError",
]
