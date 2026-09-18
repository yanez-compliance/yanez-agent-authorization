---
title: HTTP quickstart
description: Create, poll, verify, and consume an authorization over the HTTP routes.
---

# HTTP quickstart

Full schemas: [the OpenAPI contract](https://github.com/yanez-compliance/yanez-agent-authorization/blob/main/openapi/agent-authorization.openapi.yaml).
Five routes; the three agent
routes take `Authorization: Bearer yak_...`, the two relying-party routes are public.

## 1. Create a request (agent)

```http
POST /api/agent/authorizations
Authorization: Bearer yak_...
Idempotency-Key: b1946ac92492d234
Content-Type: application/json

{"terms": {"schema_version": 1,
           "action": "purchase",
           "approval_title": "Purchase running shoes",
           "summary": "Buy running shoes for $180.00 at Example Store",
           "merchant": "Example Store",
           "currency": "USD",
           "amount": {"minor_units": 18000, "currency": "USD"},
           "details": [{"label": "Merchant", "value": "Example Store", "emphasized": false},
                       {"label": "Item", "value": "Running shoes, model X, size 10", "emphasized": false},
                       {"label": "Amount", "value": "$180.00", "emphasized": true}]},
 "decision_window_seconds": 900,
 "intent_expires_at": "<RFC 3339 timestamp in the future>"}
```

The core action fields are required. For non-financial actions, omit `amount` and
`currency`; the YID app then omits the Amount row. Field rules, including the optional
`amount` and `details[].emphasized` fields: [terms](terms.md).

`201` → `{"request_id": "azr_...", "status": "pending", "decide_by": "..."}`.

Two independent windows, both optional. `decision_window_seconds` (60–3600, default
900) is how long the user has to answer before the request expires; a value outside
that range is a `422`. `intent_expires_at` is the bound on *acting* that the user gave
you — "valid for 24 hours" — and must be in the future at creation time. It travels
into the receipt as `yanez_consent_not_after`, which the action executor enforces.
Omit it when the user set no deadline.

Always send `Idempotency-Key` (1–128 printable ASCII, generated once per logical
create, reused verbatim on every retry). A retry of a lost response then returns the
original request with `Idempotency-Replayed: true` instead of prompting the user twice;
the same key with a different body returns `409`. Requests without the header are
accepted but every retry rings the user again. A replay carries the original
request's current status, so a `201` is `pending` only on a fresh create — read
`status` rather than assuming it.

**Caution:** Generate the key from randomness (a UUID), never from the request content.
A key derived by hashing the terms makes two genuine identical purchases collapse into
one — the second call replays the first request and returns its `request_id` without
ever prompting the user. The key identifies the operation, not the body, and the
reservation is permanent, so a content-derived key still replays months later.

## 2. Poll (agent)

```http
GET /api/agent/authorizations/{request_id}?wait=25
Authorization: Bearer yak_...
```

`wait` long-polls 0–25 s. Exactly one status per response: `pending`, `approved`
(non-null `artifact`), `rejected`, `expired`. Unknown and cross-key ids are the same
`404`. Stop on rejection or expiry; do not create replacements in a loop.

### Optional: list the user's signing keys (agent)

```http
GET /api/agent/user_keys
Authorization: Bearer yak_...
```

`200` → `{"yid": "...", "keys": [{"tier": "high", "public_key": "0x..."}]}`. The YID
comes from the agent key; there is no YID parameter. `tier` is `null` for a key with no
recognized tier, and no keys is an empty list.

Use it to check that an approved receipt's `yanez_user_public_key` is registered at its
`yanez_assurance_tier`, or before asking, to learn that a tier your policy requires has
no key. Read it fresh each time rather than caching it. Details:
[checking the key against the registry](user-signed-approvals.md#checking-the-key-against-the-registry).

## 3. Verify (relying party — no credentials)

```http
GET /api/authz/public-keys
```

Flat Ed25519 JWKs. Verify the artifact offline: pin `alg=EdDSA`, select the key by the
header `kid` (refresh on an unknown kid, at most once per 30 s), check your exact
expected `iss`, compare `yanez_terms` with your expected terms structurally, and check
that `sub` is the YID your records tie to the account being acted on. Claim profile and
freshness rules: [receipts](receipts.md).

Then verify the **second** signature. The receipt carries the approver's own BLS
signature over `yanez_signed_message`, and checking it — plus every field inside those
bytes — is what makes the receipt more than a Yanez assertion. A JWT library will not do
this for you: [user-signed approvals](user-signed-approvals.md).

## 4. Consume (action executor, single-use actions)

```http
POST /api/authz/introspect
Content-Type: application/json

{"artifact": "eyJ...", "consume": true, "consumer_token": "<your durable token>"}
```

`consumer_token` is required when consuming. It is your own opaque, durable string
identifying this attempt — write it down before the call, and reuse it verbatim on every
retry.

`valid` answers only "is this receipt genuine" — a spent or consent-expired receipt
stays `valid: true`. Gate the action on `consumed_now: true`. A consume by another
holder returns `reason: "already_consumed"`, `consumed_now: false`; never act on it.

A receipt is bearer proof: never log it or put it in a URL. If the consume response is
lost, retry with the **same** token: `reason: "reservation_held"` means your own earlier
attempt won, so reconcile downstream with your original idempotency key rather than
requesting a new approval. `already_consumed` means someone else holds it.
