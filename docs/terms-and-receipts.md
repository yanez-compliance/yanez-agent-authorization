---
title: Terms and receipts
description: What the human approves, and the claim profile of the signed artifact.
---

# Terms and receipts

## Terms

Opaque JSON to the server; a promise to the human who approves it and the relying
party that enforces it. `terms.action` and `terms.summary` are required non-empty
strings; the whole object is capped at 4 KB compact JSON. Decimal quantities travel as
strings ("180.00"). Recommended profiles (purchase, disclosure, permission):
[terms guidance](https://github.com/yanez-compliance/yanez-agent-authorization/blob/main/skills/yanez-authorize/references/terms-guidance.md).

If any material field changes after approval — counterparty, resource, amount,
currency, destination, scope, deadline — the old receipt must not be used. New terms
mean a new authorization request.

Yanez stores the parsed JSON value of the terms, not the bytes, so whitespace and key
order are not preserved. That is why verification compares terms by deep JSON
equality, never by byte equality. The YID app shows the approver the stored terms and
never resubmits them, so an agent cannot change the terms while approval is pending.

## The receipt (artifact)

A compact EdDSA JWS, signed by Yanez, readable by its holder (signed, not encrypted).

| Claim | Required | Meaning |
|---|---|---|
| `iss` | yes | The issuer string of your Yanez deployment, published by its operator. It is deployment configuration, not necessarily the API origin; configure your verifier with exactly this value |
| `sub` | yes | YID whose owner approved. Bind it: pass `expected_sub`, or resolve it against your own records before acting. Terms that mention an account do not by themselves prove the approver owns it |
| `jti` | yes | Request id; the single-use replay identifier |
| `iat` | yes | NumericDate; equals decision time |
| `yanez_agent_key_id` | yes | Public id of the agent key that asked: `yak_` plus 12 hex characters, which is the prefix of the full credential. It is not the credential: the secret half is never stored in plain form and never appears in a receipt or any response. Safe to log, and pinnable with `expected_agent_key_id` |
| `yanez_decision` | yes | Always `approved` — only approvals produce artifacts |
| `yanez_decided_at` | yes | NumericDate of approval |
| `yanez_match_overlap` | yes | Non-negative integer; issuer evidence about the accepted biometric match. Verifiers must not assume a maximum or threshold |
| `yanez_terms` | yes | Verbatim approved terms |
| `yanez_consent_not_after` | no | Bound on when the receipt may be acted on. The agent declares it as `intent_expires_at` at create time, from the user's instruction; the app does not ask the approver to confirm it separately |

There is deliberately **no `exp`**. The receipt is durable evidence of a past approval
— a dispute or audit arrives years later, and the record must still verify. Three
separate questions, three separate mechanisms:

1. *Genuine?* Signature + issuer + claim profile. Never changes with time.
2. *Recent enough for me to act?* Your policy, applied to `yanez_decided_at`.
3. *Still within the declared consent bound, and unspent?* `yanez_consent_not_after`
   plus introspection with `consume: true`.

## How the receipt is signed

The receipt is a Yanez assertion that a fresh biometric scan matching the YID approved
the terms. It is not a cryptographic signature made by the human. Yanez Pulse, the
authorization service, signs every receipt with its own Ed25519 private key, identified
by `kid` in the protected header. The user has no signing key in this scheme.

The decision arrives from the YID app on a platform-attested device (App Attest on
iOS, Play Integrity on Android), signed per request by that device's key and carrying a
request-time biometric sample. Pulse matches the sample against the YID's enrolled
template, which produces `yanez_match_overlap`, then moves the request out of `pending`
with a single conditional update, so two devices racing to decide cannot both win.
Only when the result is `approved` does Pulse build the claims from the stored request,
sign them, and write the receipt, all inside that same transaction. An approval is
never stored without its proof, and a rejected or expired request has no artifact.

The signature proves that Pulse recorded an approval of exactly these terms, by the
YID in `sub`, at `yanez_decided_at`, in response to the agent key in
`yanez_agent_key_id`, after a biometric match that met the server's policy at the time.
It proves nothing about whether the action is still appropriate now. Freshness, the
consent bound, exact-terms matching, and single use are the relying party's job:
[action enforcement](action-enforcement.md).

## Key publication and rotation

`GET /api/authz/public-keys` returns a flat JWK set and needs no credentials, so any
verifier can check a receipt without holding a Yanez key. Each key has this shape:

```json
{"kty": "OKP", "crv": "Ed25519", "x": "<base64url raw public key>", "kid": "...", "alg": "EdDSA"}
```

The key-distribution origin is a trust anchor in its own right. Fetch the set from a
base URL you configure, over HTTPS (plain HTTP only for loopback development), without
following redirects, and skip any entry whose `kty`, `crv`, `alg`, `kid`, or `x` is
missing or wrong. Checking that a receipt's `iss` matches your expected string does
not make keys from an untrusted origin trustworthy. The SDK verifiers do all of this.

The set holds the current signing key and every key that has signed a receipt.
Because receipts never expire, a retired key stays published: operators rotate the
signing key freely, and old receipts keep verifying under their original `kid`. Cache
the set, and on an unknown `kid` refresh it once before rejecting, because a rotation
is the normal reason a genuine receipt carries a `kid` you haven't seen. The issuer
string is fixed for the life of a deployment, so configure it once.

The one exception is key compromise. If a signing key is ever exposed, the operator
removes its `kid` and asks every verifier to denylist it, because a cached or offline
key set does not learn about the removal by itself. The SDKs cache the key set for up
to ten minutes.
