"""Yanez agent authorization SDK.

Two halves, deliberately separate:

- `AuthorizationClient` — the agent side: ask the key's owner to approve terms, poll
  for the decision. Needs the yak_ agent key.
- `ReceiptVerifier` — the relying-party side: verify and (for single-use actions)
  consume a signed receipt. Needs no credentials at all.

A receipt carries two signatures: Yanez's Ed25519 signature over the receipt, and the
approver's own BLS signature over the decision they made. `ReceiptVerifier.verify`
checks both. If you decode receipts with your own JWT library, call `verify_user_proof`
directly — that is the half a JWT tutorial will not tell you about.
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
    ReservationHeldError,
    TermsTooLargeError,
    TransportError,
    UserSignatureError,
    YanezAuthzError,
)
from yanez_authz.models import (
    AuthorizationResult,
    IntrospectionResult,
    PendingAuthorization,
    UserKeys,
    VerifiedReceipt,
)
from yanez_authz.proof import (
    ENVELOPE_ACTION,
    ENVELOPE_VERSION,
    USER_SIG_ALG,
    UserProof,
    UserProofError,
    decode_signed_message,
    key_is_registered,
    terms_equal,
    verify_bls_signature,
    verify_user_proof,
)
from yanez_authz.verifier import ReceiptVerifier

__version__ = "0.1.0b5"

__all__ = [
    "AuthorizationClient", "ReceiptVerifier",
    "PendingAuthorization", "AuthorizationResult", "IntrospectionResult", "VerifiedReceipt",
    "UserKeys",
    "YanezAuthzError", "AuthenticationError", "InvalidRequestError", "TermsTooLargeError",
    "RateLimitError", "ConflictError", "NotFoundError", "FeatureUnavailableError",
    "TransportError", "ReceiptVerificationError", "ConsentPolicyError", "AlreadyConsumedError",
    "UserSignatureError", "ReservationHeldError",
    "UserProof", "UserProofError", "verify_user_proof", "verify_bls_signature",
    "decode_signed_message", "terms_equal", "key_is_registered",
    "USER_SIG_ALG", "ENVELOPE_VERSION", "ENVELOPE_ACTION",
]
