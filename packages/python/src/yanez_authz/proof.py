"""The user's own signature over the decision, and how to check it.

A receipt carries two signatures. Yanez signs the receipt with Ed25519, which says
"Yanez saw this approval". The approver's own BLS key signs the decision message,
which says "the holder of this key approved these exact terms". The second one is
what makes a receipt more than a Yanez assertion, and it is the one an executor
copying a JWT tutorial will forget.

Everything here works on a plain claims mapping, so you can use it without the rest
of this SDK — decode the receipt with any JWT library you already trust, then hand
the claims to `verify_user_proof`. The only dependency it adds is the BLS library.

Protocol reference: docs/agent-authorization-signed-approval-spec.md §4.1, §4.7, §5.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

# --- §4.1 envelope and §5 parameters ---

#: The only signature scheme this version understands, as `yanez_user_sig_alg` spells it.
USER_SIG_ALG = "BLS12-381-G2-basic"
#: The only decision-envelope version this SDK verifies.
ENVELOPE_VERSION = 1
#: `action` in the signed envelope. A signature over some other action is not a decision.
ENVELOPE_ACTION = "agent_authorizations.decision"

_SIGNATURE_HEX_LEN = 192   # 96-byte compressed G2 point
_PUBLIC_KEY_HEX_LEN = 96   # 48-byte compressed G1 point
_MAX_MESSAGE_CHARS = 21846           # unpadded base64url of 16 KiB
_MAX_MESSAGE_BYTES = 16 * 1024
_MAX_MESSAGE_DEPTH = 32
# `signed_at` (device clock, at the ceremony) against `yanez_decided_at` (server clock,
# at submission). Bounding their DIFFERENCE is a statement about ingestion latency and
# clock skew. Comparing either against today's clock would fail every historical
# verification, which is exactly when a receipt matters most — see §4.7 step 5.
_INGESTION_SKEW_SECONDS = 600


class UserProofError(Exception):
    """The receipt's user signature is missing, malformed, or does not verify.

    Raised by the standalone helpers here. `ReceiptVerifier` re-raises these as
    `UserSignatureError` so a caller can catch the whole verification family at once.
    """


@dataclass(frozen=True)
class UserProof:
    """A verified user signature and the envelope it covers.

    `signed_message` is the exact bytes the signature was checked against. Never
    re-serialize `envelope` to get them back: a re-encode is a different byte string
    and will not verify.
    """

    assurance_tier: str
    public_key: str
    signature: str
    signed_message: bytes
    envelope: Mapping[str, Any]
    signed_at: int
    yid: str
    decision: str
    issuer: str
    version: int
    consent_not_after: Optional[int] = None

    @property
    def terms(self) -> Mapping[str, Any]:
        """The terms the user signed, as distinct from the terms Yanez attested to.

        `verify_user_proof` has already checked the two agree; this is the user's copy.
        """
        return self.envelope["terms"]


# --- §3.3 comparison ---


def terms_equal(a: Any, b: Any) -> bool:
    """Structural equality for terms, per spec §3.3.

    Three rules that ordinary deep-equality helpers get wrong:

    - A boolean is never a number. `{"n": true}` must not match `{"n": 1}`.
    - Numbers compare by value, so `-0` equals `0`. Python's `==` and JavaScript's
      `===` agree here; `isDeepStrictEqual` does not, which is why this SDK no longer
      uses it. Two verifiers reading the same bytes must reach the same verdict.
    - Array order is significant. A reordered `details` array is different terms.

    Duplicate object keys and non-finite numbers are rejected at parse time by
    `parse_json_strict`, before either side becomes a Python object.
    """
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, dict):
        if not isinstance(b, dict) or a.keys() != b.keys():
            return False
        return all(terms_equal(v, b[k]) for k, v in a.items())
    if isinstance(b, dict):
        return False
    if isinstance(a, list):
        if not isinstance(b, list) or len(a) != len(b):
            return False
        return all(terms_equal(x, y) for x, y in zip(a, b))
    if isinstance(b, list):
        return False
    if isinstance(a, (int, float)):
        return isinstance(b, (int, float)) and a == b
    if isinstance(b, (int, float)):
        return False
    return type(a) is type(b) and a == b


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            # json.loads keeps the last one, so two verifiers reading identical bytes
            # could compare different values and both believe they agree.
            raise ValueError(f"duplicate object key: {key}")
        seen[key] = value
    return seen


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite number: {name}")


def _json_depth(value: Any) -> int:
    """Nesting depth, outermost container counting as 1.

    Iterative on purpose: this exists to bound pathological nesting, and a recursive
    walk would hit the limit it is meant to enforce.
    """
    depth = 0
    frontier = [value]
    while frontier:
        depth += 1
        children: list[Any] = []
        for node in frontier:
            if isinstance(node, dict):
                children.extend(node.values())
            elif isinstance(node, list):
                children.extend(node)
        frontier = children
    return depth


def parse_json_strict(raw: bytes, *, max_depth: Optional[int] = _MAX_MESSAGE_DEPTH) -> Any:
    """`json.loads` with the §3.3 parse rules: no duplicate keys, no NaN or Infinity."""
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except RecursionError:
        raise ValueError("json is nested too deeply") from None
    if max_depth is not None and _json_depth(value) > max_depth:
        raise ValueError("json is nested too deeply")
    return value


# --- §5 signature check ---


def verify_bls_signature(message: bytes, signature_hex: str, public_key_hex: str) -> bool:
    """Verify one BLS signature under the parameters in spec §5.

    BLS12-381, minimal pubkey size (keys in G1, signatures in G2), the IRTF **basic**
    scheme: no message augmentation, no proof of possession, DST
    `BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_NUL_`. Getting the scheme or the DST wrong
    produces a verifier that rejects every genuine signature, or worse accepts under
    parameters nobody else uses.

    Returns False for a malformed point, a wrong-length input, or a failed check. It
    raises only if the BLS library is missing. `0x` prefixes are accepted on both hex
    arguments because the receipt claims carry them and the registry does not.
    """
    try:
        from py_ecc.bls import G2Basic
    except ImportError:  # pragma: no cover - packaging error, not a runtime path
        raise UserProofError(
            "BLS verification needs py_ecc; install yanez-agent-authorization[verify]"
        ) from None

    signature = _unhex(signature_hex, _SIGNATURE_HEX_LEN)
    public_key = _unhex(public_key_hex, _PUBLIC_KEY_HEX_LEN)
    if signature is None or public_key is None:
        return False
    try:
        return bool(G2Basic.Verify(public_key, message, signature))
    except Exception:
        # A point that is not on the curve, not in the subgroup, or not decodable at
        # all reaches us as a library exception. That is a failed verification, not a
        # crash to propagate into an executor's request handler.
        return False


def _unhex(value: str, expected_len: int) -> Optional[bytes]:
    if not isinstance(value, str):
        return None
    cleaned = value[2:] if value[:2].lower() == "0x" else value
    if len(cleaned) != expected_len:
        return None
    try:
        return bytes.fromhex(cleaned)
    except ValueError:
        return None


def decode_signed_message(signed_message: str) -> bytes:
    """base64url-decode `yanez_signed_message` into the exact signed bytes.

    Canonical encoding is required: two base64url spellings of one message would both
    decode, and only one of them can equal the bytes the issuer stored.
    """
    if not isinstance(signed_message, str) or not signed_message:
        raise UserProofError("yanez_signed_message must be a non-empty string")
    if len(signed_message) > _MAX_MESSAGE_CHARS:
        raise UserProofError("yanez_signed_message is too large")
    try:
        raw = base64.urlsafe_b64decode(signed_message + "=" * (-len(signed_message) % 4))
    except (ValueError, TypeError):
        raise UserProofError("yanez_signed_message is not valid base64url") from None
    if len(raw) > _MAX_MESSAGE_BYTES:
        raise UserProofError("yanez_signed_message is too large")
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != signed_message:
        raise UserProofError("yanez_signed_message is not canonical base64url")
    return raw


# --- §4.7 steps 4 and 5 ---


def verify_user_proof(claims: Mapping[str, Any], *, expected_issuer: str) -> UserProof:
    """Check the approver's signature and everything it is bound to.

    This is §4.7 step 4 (verify the signature) and step 5 (check what was signed), which
    only make sense together: step 4 alone proves a key signed *some* decision, and step
    5 is what ties that decision to *this* receipt. Skipping any of step 5's checks makes
    step 4 decorative.

    Call it with the claims of a receipt whose Yanez signature you have **already**
    verified. It does not check the JWT — `ReceiptVerifier.verify` does that first and
    then calls this. Verifying the user proof on an unverified JWT tells you only that
    someone assembled a self-consistent bundle.

    Raises `UserProofError` on any failure. Returns the proof on success.
    """
    proof_claims = ("yanez_assurance_tier", "yanez_user_public_key",
                    "yanez_user_signature", "yanez_signed_message", "yanez_user_sig_alg")
    if all(claims.get(name) is None for name in proof_claims):
        # A receipt minted before signed approvals. It records a real approval, but no
        # user signed it, so it does not meet this contract and must not pass under it.
        raise UserProofError("receipt carries no user proof")

    alg = claims.get("yanez_user_sig_alg")
    if alg != USER_SIG_ALG:
        raise UserProofError(f"unsupported yanez_user_sig_alg {alg!r}")

    signature = claims.get("yanez_user_signature")
    public_key = claims.get("yanez_user_public_key")
    tier = claims.get("yanez_assurance_tier")
    for name, value in (("yanez_user_signature", signature),
                        ("yanez_user_public_key", public_key),
                        ("yanez_assurance_tier", tier)):
        if not isinstance(value, str) or not value:
            raise UserProofError(f"claim {name} must be a non-empty string")

    raw = decode_signed_message(claims.get("yanez_signed_message"))

    # Step 4, before parsing: unverified bytes get as little handling as possible.
    if not verify_bls_signature(raw, signature, public_key):
        raise UserProofError("user signature does not verify over yanez_signed_message")

    try:
        envelope = parse_json_strict(raw)
    except ValueError as e:
        raise UserProofError(f"signed message is not valid JSON: {e}") from None
    if not isinstance(envelope, dict):
        raise UserProofError("signed message must be a JSON object")

    # Step 5. Every one of these, in the order the spec lists them.
    if envelope.get("decision") != "approve":
        # A rejection carries a signature that passes step 4 perfectly well.
        raise UserProofError("signed decision is not an approval")
    version = envelope.get("version")
    if version != ENVELOPE_VERSION or isinstance(version, bool):
        raise UserProofError(f"unsupported signed envelope version {version!r}")
    if envelope.get("issuer") != expected_issuer:
        raise UserProofError("signed issuer does not match the expected issuer")
    if claims.get("iss") != expected_issuer:
        raise UserProofError("receipt iss does not match the expected issuer")
    if envelope.get("action") != ENVELOPE_ACTION:
        raise UserProofError("signed action is not a decision")
    if envelope.get("authorization_request_id") != claims.get("jti"):
        raise UserProofError("signed request id does not match the receipt jti")
    if envelope.get("yid") != claims.get("sub"):
        raise UserProofError("signed yid does not match the receipt sub")
    if envelope.get("assurance_tier") != tier:
        raise UserProofError("signed assurance tier does not match the receipt claim")

    signed_terms = envelope.get("terms")
    if not isinstance(signed_terms, dict):
        raise UserProofError("signed terms must be an object")
    if not terms_equal(signed_terms, claims.get("yanez_terms")):
        # Yanez's account of what was approved and the user's own must agree. When they
        # disagree, the user's copy is the one that was signed, and neither is safe.
        raise UserProofError("signed terms do not match yanez_terms")

    bound = envelope.get("consent_not_after")
    if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int)):
        raise UserProofError("signed consent_not_after must be an integer or null")
    if bound != claims.get("yanez_consent_not_after"):
        raise UserProofError("signed consent bound does not match the receipt claim")

    signed_at = envelope.get("signed_at")
    if not isinstance(signed_at, int) or isinstance(signed_at, bool):
        raise UserProofError("signed_at must be an integer")
    decided_at = claims.get("yanez_decided_at")
    if not isinstance(decided_at, int) or isinstance(decided_at, bool):
        raise UserProofError("yanez_decided_at must be an integer")
    if abs(decided_at - signed_at) > _INGESTION_SKEW_SECONDS:
        raise UserProofError("signed_at and yanez_decided_at are too far apart")

    return UserProof(
        assurance_tier=tier,
        public_key=public_key,
        signature=signature,
        signed_message=raw,
        envelope=envelope,
        signed_at=signed_at,
        yid=envelope["yid"],
        decision="approve",
        issuer=expected_issuer,
        version=ENVELOPE_VERSION,
        consent_not_after=bound,
    )


# --- §4.9 registry cross-check ---


def key_is_registered(public_key: str, tier: str, registered_keys: Any) -> bool:
    """Is this the user's key, at the tier it claims?

    `registered_keys` is the `keys` array from `GET /api/agent/user_keys` (spec §4.9).
    Both sides are normalized before comparison. The route and the receipt claim both
    spell keys `0x` + lowercase hex, but a key from any other source may drop the prefix
    or change case, and a raw string compare then silently reports it as unregistered.

    This is a second read path over Yanez's own storage, not independent verification:
    the registry and the receipt have the same operator. It catches a receipt whose
    embedded key was substituted while the registry was intact, and it is worth exactly
    that much. See §4.9.
    """
    wanted = _normalize_key(public_key)
    # A key recorded with no tier can never verify a decision (§4.3 step 9 resolves
    # candidates by exact tier), so a null tier on EITHER side matches nothing. Without
    # this guard, asking about a tierless key finds the tierless registry row and
    # answers True.
    if wanted is None or not tier or not isinstance(registered_keys, list):
        return False
    for entry in registered_keys:
        if not isinstance(entry, Mapping):
            continue
        if entry.get("tier") != tier:
            continue
        if _normalize_key(entry.get("public_key")) == wanted:
            return True
    return False


def _normalize_key(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    cleaned = value[2:] if value[:2].lower() == "0x" else value
    return cleaned.lower() or None
