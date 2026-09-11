---
title: User-signed approvals
description: Receipts now carry the approver's own signature. What changed in the schema, and how to verify both signatures.
---

# User-signed approvals

A receipt used to carry one signature. Yanez signed it, and that signature said *Yanez saw
this approval*. Everything you believed about the approval, you believed because Yanez said
so.

A receipt now carries **two**. The second is made by the approver's own key, on their own
device, over the complete decision they made — the request id, the terms verbatim, the
assurance tier their scan reached, and the deadline they agreed to. Verifying it tells you
something Yanez cannot tell you: that the holder of that key approved *these exact terms*.

This page covers what changed in the schema, and the steps to verify both signatures.

<div class="callout">
  <div class="callout-title">This release is breaking</div>
  <p>The five proof claims are <strong>required</strong>. A receipt minted before this
  change fails verification rather than being reported as an approval nobody signed.
  <code>consume</code> also gains a required <code>consumer_token</code>. The Python SDK moves to
  <code>0.1.0b3</code> and the TypeScript SDK to <code>1.0.0</code>; see <a href="#upgrading">Upgrading</a>.</p>
</div>

## What changed in the schema

### Receipts gain five claims

| Claim | Value |
|---|---|
| `yanez_assurance_tier` | `low`, `medium`, or `high` — the tier the approver's scan reached |
| `yanez_user_public_key` | `0x` + 48-byte compressed G1 point, hex |
| `yanez_user_signature` | `0x` + 96-byte compressed G2 point, hex |
| `yanez_signed_message` | base64url of the exact bytes the approver signed |
| `yanez_user_sig_alg` | `BLS12-381-G2-basic` |

`yanez_terms` stays, and it now has a companion. The terms inside `yanez_signed_message`
duplicate it **by design**: one is Yanez's assertion of what was approved, the other is the
user's. Verification checks that the two agree, and disagreement is fatal.

### Terms gain a version and lose `display`

`terms` is now a versioned profile. The server validates it on create and rejects anything
outside it.

| Change | Before | Now |
|---|---|---|
| `schema_version` | absent | required integer, exactly `1` |
| `amount.display` | required string | **removed** — the app formats from `minor_units` and the currency's own exponent |
| `amount.minor_units` | up to 2^63-1 | integer, `0` to 2^53-1 |
| `currency` | any non-blank string | ISO 4217 code from the server's allowlist |
| Numbers anywhere in terms | any JSON number | integers only, within the same bound |

`display` is gone because two fields describing one amount can disagree, and the one the
human read was the one that could lie. `¥18,000` and `$180.00` are both `18000` minor units;
the app knows which currency has a minor unit and formats accordingly.

The 2^53-1 bound is the largest integer a double round-trips exactly, so a JavaScript
verifier and a Python one cannot disagree about the value they are comparing.

See [Terms](terms.md) for the full field rules.

### The pending list gains two arrays

`/list` returns `{requests, unavailable_requests, registered_tiers}`. Requests whose stored
terms predate the profile move to `unavailable_requests`, carry no terms at all, and cannot
be signed. One historical row can no longer break decoding for the valid rows beside it.

### Consuming a receipt requires a token

`consume` now takes a `consumer_token`: your own opaque, durable string identifying the
attempt. Reuse the same one when retrying after a lost response — that is how the server
tells your earlier attempt from another holder's. The server never generates one, because
a server-minted token would be lost with the response it travelled in.

This adds a third consume outcome. See [Recovering a lost consume](#recovering-a-lost-consume).

## The signed message

`yanez_signed_message` base64url-decodes to a JSON object like this:

```json
{
  "action": "agent_authorizations.decision",
  "assurance_tier": "high",
  "authorization_request_id": "azr_c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0",
  "consent_not_after": null,
  "decision": "approve",
  "issuer": "https://yid.yanez.ai",
  "signed_at": 1767225596,
  "terms": { "...verbatim, exactly as the app received them..." },
  "version": 1,
  "yid": "a1b2c3..."
}
```

| Field | Meaning |
|---|---|
| `version` | Envelope version, `1`. Distinct from `terms.schema_version`; the two move independently |
| `issuer` | The Yanez issuer this decision was made for. Must equal your configured issuer |
| `action` | Fixed discriminator. Stops a signature minted in one ceremony being replayed into another |
| `assurance_tier` | The tier the scan reached |
| `authorization_request_id` | Binds the signature to one request |
| `decision` | `approve` or `reject` — **a rejection is signed too** |
| `consent_not_after` | Integer epoch seconds or `null`. The user's own bound on how long their consent may be acted on |
| `signed_at` | Epoch seconds when the device produced the signature |
| `terms` | The request's terms, byte-for-byte as the app received them |
| `yid` | The signing identity |

**Verify the bytes, never a re-encode.** The signature covers the exact bytes in
`yanez_signed_message`. Parse them to read the fields, but check the signature against the
bytes you decoded. Re-serializing the parsed object produces a different byte string, and
it will not verify. Sorted keys are a producer convention, not a rule.

## Verifying, step by step

Seven steps. The SDKs do 1 through 5 inside `verify`, and 7 when you pass `consume`.
Step 6 is the one nobody can do for you: only your service knows which account this
action belongs to.

1. **Verify the Yanez signature.** Fetch the JWKS, pin `alg` to `EdDSA`, select the key by
   `kid` — never by the token's own algorithm header — and check `iss` against your
   configured issuer.
2. **Apply your freshness policy** to `yanez_decided_at`, and check `yanez_consent_not_after`
   if present.
3. **Check `yanez_assurance_tier`** against your own floor for the value at risk.
4. **Verify the user's signature.** base64url-decode `yanez_signed_message` and verify
   `yanez_user_signature` over those exact bytes with `yanez_user_public_key`, using the
   parameters below.
5. **Check what was signed.** Parse the decoded message and check *every* one of these.
   Skipping any makes step 4 decorative:

   - `decision` is `approve`. A rejection carries a signature that passes step 4 perfectly.
   - `version` is supported, and `issuer` equals both your configured issuer and `iss`.
   - `action` is `agent_authorizations.decision`.
   - `authorization_request_id` equals the receipt's `jti`.
   - `yid` equals the receipt's `sub`.
   - `assurance_tier` equals `yanez_assurance_tier`.
   - `terms` matches `yanez_terms` structurally (see [Comparing terms](#comparing-terms)).
   - `consent_not_after` matches the receipt's bound; an absent claim means `null`.
   - `signed_at` is consistent with `yanez_decided_at` within an ingestion allowance. Bound
     the **difference** between them — never either one against today's clock, or every
     historical verification fails, which is exactly when a receipt matters most.

6. **Bind it to your own context.** Confirm the terms describe the action you are about to
   perform, and that `sub` is the account you mean. Pass `expected_sub` and
   `expected_agent_key_id`. A genuine receipt says *some* identity approved *some* terms;
   two people can approve identical terms.
7. **Consume it** atomically before acting, if the action is single-use.

### Cryptographic parameters

| Parameter | Value |
|---|---|
| Curve | BLS12-381 |
| Variant | Minimal pubkey size: public keys in G1, signatures in G2 |
| Public key | 48 bytes, compressed G1 |
| Signature | 96 bytes, compressed G2 |
| Scheme | **Basic**. No message augmentation, no proof of possession |
| DST | `BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_NUL_` |

The DST and the scheme go together. A verifier built on the augmented or proof-of-possession
variant rejects every genuine signature, and one built on a hand-typed DST may accept under
parameters nobody else uses. The `_NUL_` suffix is what marks the basic scheme.

### Comparing terms

Deep equality, with three rules that ordinary helpers get wrong:

- **A boolean is never a number.** `{"n": true}` must not match `{"n": 1}`.
- **Numbers compare by value**, so `-0` equals `0`. Node's `isDeepStrictEqual` separates
  them and Python's `==` does not — two verifiers reading the same bytes would split. Both
  SDKs use `termsEqual` / `terms_equal` instead; use those rather than a stock helper.
- **Array order is significant.** A reordered `details` array is different terms.

Duplicate object keys are rejected when the signed message is parsed. `JSON.parse` and
`json.loads` both silently keep the last one, so a message naming `decision` twice could be
read two ways by two verifiers, each believing it agreed with the other.

## Verifying with the SDK

Both SDKs check both signatures inside `verify`. Nothing extra to call.

```python
from yanez_authz import ReceiptVerifier, ConsentPolicyError, UserSignatureError

verifier = ReceiptVerifier("https://yid.yanez.ai", expected_issuer="https://yid.yanez.ai")

try:
    receipt = verifier.verify(
        artifact,
        expected_terms=terms,
        max_age_seconds=900,
        expected_sub=account.yid,          # step 6
        min_assurance_tier="high",         # step 3
    )
except UserSignatureError as e:
    ...  # the approver did not sign this. Never execute.
except ConsentPolicyError as e:
    ...  # genuine, but stale, expired, or below your floor.

receipt.assurance_tier      # "high", from the bytes the user signed
receipt.signed_at           # when their device signed
receipt.user_proof.envelope # the full decoded message
```

```typescript
import { ReceiptVerifier, UserSignatureError } from "@yanez/agent-authorization";

const verifier = new ReceiptVerifier("https://yid.yanez.ai", "https://yid.yanez.ai");

const receipt = await verifier.verify(artifact, terms, 900, {
  expectedSub: account.yid,
  minAssuranceTier: "high",
});
receipt.assuranceTier;
receipt.userProof.envelope;
```

`min_assurance_tier` is a **policy** gate, so falling short raises `ConsentPolicyError`, not
a verification error. The receipt is genuine; it is just not strong enough for what you were
about to do. Treating those two as one error class means an operator reading your logs
cannot tell a forgery attempt from a user whose scan was mediocre.

## Verifying without the SDK

If you already have a JWT library you trust, use it for step 1 and call the proof helper for
steps 4 and 5. It takes a plain claims mapping and needs no client, no network, and no
configuration beyond your issuer.

```python
import jwt
from yanez_authz import verify_user_proof, UserProofError

claims = jwt.decode(artifact, key, algorithms=["EdDSA"], issuer=ISSUER)  # step 1, your code
proof = verify_user_proof(claims, expected_issuer=ISSUER)                # steps 4 and 5
```

```typescript
import { jwtVerify } from "jose";
import { verifyUserProof } from "@yanez/agent-authorization";

const { payload } = await jwtVerify(artifact, key, { algorithms: ["EdDSA"], issuer: ISSUER });
const proof = verifyUserProof(payload as Record<string, unknown>, { expectedIssuer: ISSUER });
```

**Verify the JWT first.** Running the proof check on an unverified receipt tells you only
that someone assembled a self-consistent bundle — anyone can mint one.

Lower-level pieces are exported too, for a verifier written in another language or a test
harness:

| Python | TypeScript | Does |
|---|---|---|
| `verify_user_proof` | `verifyUserProof` | Steps 4 and 5 together. The one to reach for |
| `verify_bls_signature` | `verifyBlsSignature` | Step 4 alone: one signature, the §5 parameters. Returns a boolean, never raises |
| `decode_signed_message` | `decodeSignedMessage` | base64url with the canonical-encoding check |
| `terms_equal` | `termsEqual` | The comparison rules above |
| `parse_json_strict` | `parseJsonStrict` | JSON with duplicate keys and non-finite numbers refused |
| `key_is_registered` | `keyIsRegistered` | The registry cross-check below |

## Checking the key against the registry

<div class="callout">
  <div class="callout-title">Specified, not yet deployed</div>
  <p>This endpoint is part of the contract but is not live yet. The helpers below take
  the key array as an argument, so they work today against any source of registered
  keys, and will work unchanged once the route ships.</p>
</div>

An agent can ask which keys the registry holds for its own user, and at which tiers:

```
GET /api/agent/user_keys
Authorization: Bearer <yak_ agent key>
```

The YID comes from the agent key. There is no YID parameter, so this cannot be used to
enumerate anyone else's keys.

```json
{
  "yid": "a1b2c3...",
  "keys": [
    {"tier": "high", "public_key": "a3c1..."},
    {"tier": null,   "public_key": "55dd..."}
  ]
}
```

Two uses, both optional:

```python
from yanez_authz import key_is_registered

if not key_is_registered(receipt.user_proof.public_key, receipt.assurance_tier, keys):
    ...  # the receipt names a key the registry does not hold at that tier
```

**Normalize before comparing.** The receipt claim carries a `0x` prefix and the registry
does not. A raw string compare finds nothing, which reads as *this key is not the user's* —
the most alarming possible way to be wrong. The helpers above normalize both sides; if you
compare by hand, strip the prefix and lowercase first.

The second use is pre-flight: a tier **absent** from the list cannot be signed at, so an
agent whose policy floor is `high` knows the request is futile before it prompts anyone. A
tier **present** proves only that the registry holds a key — the device may be lost, and a
scan on it may reach no tier at all. Absence is conclusive; presence is permission to try.

**This is not independent verification.** The registry and the receipt have the same
operator. It catches a receipt whose embedded key was substituted while the registry was
intact, and it is worth exactly that much.

## Recovering a lost consume

`consumer_token` exists for one scenario: you consumed a receipt, and the response never
arrived. Retrying with the same token now has a distinct outcome.

| Outcome | What happened | What to do |
|---|---|---|
| Success | You won the reservation | Execute, carrying your idempotency key |
| `ReservationHeldError` | **You** already hold it, from an attempt whose response was lost | **Reconcile** with the ORIGINAL idempotency key. The action may already have happened |
| `AlreadyConsumedError` | Someone else holds it | Never execute |

`ReservationHeldError` is a recovery, not a refusal — the opposite of `AlreadyConsumedError`.
Requesting a new approval there mints a second `jti` for an action that may already have
succeeded, and the duplicate is invisible to every consumption check.

Write the consumer token and an idempotency key derived from `jti` **durably before**
consuming. Both must survive the crash they exist to recover from.

## What the user's signature proves

**Proved.** The private key matching `yanez_user_public_key` signed this exact decision
message, for this request, at the tier named inside it. The signature covers the exact
bytes, terms included.

**Not proved by the signature alone.** A biometric match, a trustworthy device clock,
ownership of the device that submitted it, or that the app selected the highest tier the
scan could achieve. Those remain Yanez assertions, authenticated by the issuer signature. A
tier downgrade lowers assurance and is caught by your tier floor, not by the signature.

**Not established.** Revocation freshness. No key carries a revoked state, so a receipt
signed by a device later lost still passes every check here. And nothing binds a public key
to a legal identity; that path is not provided.

## Upgrading

The Python SDK moves to `0.1.0b3` and the TypeScript SDK to `1.0.0`. Two breaking changes:

- **`consume` requires `consumer_token`.** An un-updated caller fails at the call site
  rather than silently producing a token that cannot survive a lost response.
- **Verification now requires the user proof.** Receipts minted before this change fail.
  They record real approvals; they are simply not user-signed ones, and they must not be
  consumable under a contract that says they are.

Also check:

- `Terms` gains a required `schema_version` and drops `amount.display`. In TypeScript the
  compiler will find every literal for you.
- `VerifiedReceipt` gains `assurance_tier`, `signed_at`, and `user_proof`.
- Replace any `isDeepStrictEqual`-based terms comparison with `termsEqual` / `terms_equal`.

The Python SDK adds a `py_ecc` dependency and the TypeScript SDK adds `@noble/curves`, both
pure-language implementations with no build step. Two independent implementations verifying
the same conformance vectors is deliberate: a library checking its own output proves the
plumbing, not the parameters.
