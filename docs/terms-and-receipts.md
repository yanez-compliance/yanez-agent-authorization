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

## The receipt (artifact)

A compact EdDSA JWS, signed by Yanez, readable by its holder (signed, not encrypted).

| Claim | Required | Meaning |
|---|---|---|
| `iss` | yes | The issuer string of your Yanez deployment, published by its operator. It is deployment configuration, not necessarily the API origin; configure your verifier with exactly this value |
| `sub` | yes | YID whose owner approved. Bind it: pass `expected_sub`, or resolve it against your own records before acting. Terms that mention an account do not by themselves prove the approver owns it |
| `jti` | yes | Request id; the single-use replay identifier |
| `iat` | yes | NumericDate; equals decision time |
| `yanez_agent_key_id` | yes | Non-secret id of the requesting agent key |
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

The receipt is a Yanez assertion that a fresh biometric scan matching the YID approved
the terms. It is not a cryptographic signature made by the human.
