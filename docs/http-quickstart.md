---
title: HTTP quickstart
description: Create, poll, verify, and consume an authorization over the four HTTP routes.
---

# HTTP quickstart

Full schemas: [the OpenAPI contract](https://github.com/yanez-compliance/yanez-agent-authorization/blob/main/openapi/agent-authorization.openapi.yaml).
Four routes; the two agent
routes take `Authorization: Bearer yak_...`, the two relying-party routes are public.

## 1. Create a request (agent)

```http
POST /api/agent/authorizations
Authorization: Bearer yak_...
Idempotency-Key: b1946ac92492d234
Content-Type: application/json

{"terms": {"action": "purchase", "summary": "Buy running shoes for $180 at Example Store",
           "merchant": "Example Store", "amount": "180.00", "currency": "USD"},
 "decision_window_seconds": 900}
```

`201` → `{"request_id": "azr_...", "status": "pending", "decide_by": "..."}`.

Always send `Idempotency-Key` (1–128 printable ASCII, generated once per logical
create, reused verbatim on every retry). A retry of a lost response then returns the
original request with `Idempotency-Replayed: true` instead of prompting the user twice;
the same key with a different body returns `409`. Requests without the header are
accepted but every retry rings the user again.

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

## 3. Verify (relying party — no credentials)

```http
GET /api/authz/public-keys
```

Flat Ed25519 JWKs. Verify the artifact offline: pin `alg=EdDSA`, select the key by the
header `kid` (refresh on an unknown kid, at most once per 30 s), check your exact
expected `iss`, compare `yanez_terms` with your expected terms by deep equality, and
check that `sub` is the YID your records tie to the account being acted on. Claim
profile and freshness rules: [terms and receipts](terms-and-receipts.md).

## 4. Consume (action executor, single-use actions)

```http
POST /api/authz/introspect
Content-Type: application/json

{"artifact": "eyJ...", "consume": true}
```

`valid` answers only "is this receipt genuine" — a spent or consent-expired receipt
stays `valid: true`. Gate the action on `consumed_now: true`. A repeat consume returns
`reason: "already_consumed"`, `consumed_now: false`; never act on it.
