---
title: Action enforcement
description: The contract for the boundary that turns a verified receipt into an action.
---

# Action enforcement

The enforcement boundary is the sensitive action executor — not the agent, not a
skill, not an MCP status field. A protected action must have **no unguarded path**:
its trusted API takes both the proposed action and the receipt.

```text
execute_purchase(order, yanez_receipt)
```

The executor:

1. Reconstructs the expected terms from `order` — its own inputs, not the agent's
   claims.
2. Verifies the receipt: pinned EdDSA, key by `kid` from `/api/authz/public-keys`
   (at most one early refresh per 30 s on an unknown kid), the exact issuer string the
   Yanez operator publishes, required claims, `yanez_decision == "approved"`,
   `iat == yanez_decided_at` and not in the future, integer `yanez_match_overlap >= 0`,
   and `sub` equals the YID entitled to act on this account (`expected_sub`).
3. Compares `yanez_terms` with the expected terms by deep JSON equality. No ignored
   fields, no wildcards.
4. Applies its freshness policy: refuse when `now - yanez_decided_at > max_age`.
5. Honors the declared consent bound: refuse when `now > yanez_consent_not_after`.
6. For single-use actions, consumes immediately before executing:
   `POST /api/authz/introspect {"artifact": ..., "consume": true}` and proceeds only
   on `consumed_now: true`. `reason: "already_consumed"` (still `valid: true`) means
   the receipt was spent — refuse.

Both SDKs package steps 2–6 as one call:

```python
receipt = ReceiptVerifier(base_url, expected_issuer).authorize_action(
    artifact, expected_terms, max_age_seconds=900, consume=True,
    expected_sub=order.approver_yid)   # the YID your records tie to this account
execute_purchase(order)   # only reachable past authorize_action
```

A genuine receipt proves that *some* YID approved these terms. Naming the account
inside the terms does not change that: any user could approve terms that mention
someone else's account. Always establish who approved, by passing `expected_sub` (the
YID your own records tie to the account) or by resolving `receipt.sub` against those
records before acting. `expected_agent_key_id` additionally pins which agent key asked.

Never accept as authorization: an agent-generated boolean, prose ("the user approved"),
decoded-but-unverified JWT claims, or an MCP tool result. If the external action fails
after consumption, the receipt stays spent — retry requires a new authorization; Yanez
cannot make consumption and a third-party side effect one atomic transaction. Offline
verification alone does not prevent replay: single-use actions consume, or keep an
equivalent relying-party `jti` ledger.
