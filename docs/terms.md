---
title: Terms
description: The object the human approves — required action fields and optional financial terms.
---

# Terms

`terms` is the object the human approves and the relying party enforces. The server
validates its shape on create and answers `422` when a field is missing, blank, or the
wrong type. Every field is also a promise to the approver, because the YID app renders
them on the approval screen — and now because the approver's own key signs it. See
[user-signed approvals](user-signed-approvals.md).

Required string fields must hold at least one non-whitespace character. The whole object
is capped at 4 KB of compact JSON, and the server answers `413` above that.

| Field | Required | Type | Meaning |
|---|---|---|---|
| `schema_version` | yes | integer | Exactly `1`. An absent, non-integer, or different value is a `422` |
| `action` | yes | string | What kind of action this is, such as `purchase`. Keep it short, lowercase, and identical across identical operations so a relying party can branch on it |
| `approval_title` | yes | string | The headline the YID app shows the approver. Name the action, not your product |
| `summary` | yes | string | One sentence stating the whole action, including the amount when one exists |
| `merchant` | yes | string | The seller, counterparty, or service name the approver recognizes |
| `details` | yes | array | The rows the app renders as a table, described below |
| `currency` | no | string | ISO 4217 alpha-3 code from the server's configured allowlist. Required whenever `amount` is present |
| `amount` | no | object | What gets charged. Omit for non-financial actions |

For an action such as signing a document, granting access, or publishing content, omit
both `amount` and `currency`. YanezYID then omits the Amount row entirely. Do not send a
zero-dollar placeholder.

Extra keys are allowed at every level. Domain fields the relying party matches on, such
as an item id, a resource id, or a scope list, go alongside the required ones; the
server stores them untouched, the approver's signature covers them, and they are
compared with everything else at enforcement time. Any number among them is subject to
the same integer rule and the same bound as `minor_units`. `details` is for what the human reads, extra keys are for what the executor
checks.

## amount

`amount` is optional. When it is present, top-level `currency` is required and must
match `amount.currency`.

| Field | Type | Meaning |
|---|---|---|
| `minor_units` | integer | The amount as a whole number of the currency's minor unit, which is the smallest denomination the currency charges in. Under `USD` the minor unit is the cent, so `18000` is $180.00. Under a zero-decimal currency such as `JPY` the minor unit is the yen, so `18000` is ¥18,000. Must be a non-negative integer no greater than 9007199254740991, which is 2^53 - 1. Never a float and never a decimal string |
| `currency` | string | Must equal the top-level `currency` exactly |

**`display` was removed.** The app formats the amount itself, from `minor_units` and the
currency's own exponent. Two fields describing one amount can disagree, and the one the
human read was the one that could lie — the server had no way to tell you. Send the
number; let the app render it.

The 2^53 - 1 bound is the largest integer a double round-trips exactly, so a JavaScript
verifier and a Python one cannot disagree about the value they are comparing. The same
bound applies to **every** number anywhere in `terms`, and every one of them must be an
integer.

## details

Each entry requires `label` and `value` as non-blank strings. `emphasized` is optional;
set it to `true` to render a row with visual emphasis, or omit it for standard emphasis.
When supplied, it must be a boolean. The app renders the entries as a two-column table
in array order, so the array order is the reading order. The app doesn't sort, merge,
or drop rows.

The array can be empty, but give it rows. The table is where the approver checks the
specifics of what they're agreeing to, and a screen carrying only a title and a summary
leaves them less to check.

## agent_name

`agent_name` names the agent doing the asking, and the YID app shows it on the approval
screen:

```json
{"agent_name": "Shopping agent"}
```

Omit it, or send `null`, and the app falls back to the label on the agent key. A blank
string is a `422` rather than a fallback, because the app reads `null` as "use the key's
label" and a blank string as "show nothing", so the server refuses the one that renders
an empty name. Any non-string value is a `422` as well.

## Financial example

```json
{
  "schema_version": 1,
  "action": "purchase",
  "approval_title": "Purchase running shoes",
  "summary": "Buy running shoes for $180.00 at Example Store",
  "merchant": "Example Store",
  "currency": "USD",
  "amount": {"minor_units": 18000, "currency": "USD"},
  "details": [
    {"label": "Merchant", "value": "Example Store", "emphasized": false},
    {"label": "Item", "value": "Running shoes, model X, size 10", "emphasized": false},
    {"label": "Amount", "value": "$180.00", "emphasized": true}
  ]
}
```

## Non-financial example

Omit `amount`, `currency`, and unnecessary presentation hints for an action with no
monetary component:

```json
{
  "schema_version": 1,
  "action": "document.signature.authorize",
  "approval_title": "Sign mutual NDA",
  "summary": "Authorize your signature on the mutual NDA with Yanez Pulse.",
  "merchant": "Documenso",
  "details": [
    {"label": "Document", "value": "Mutual Non-Disclosure Agreement"},
    {"label": "Counterparty", "value": "Yanez Pulse"},
    {"label": "Signing as", "value": "Yanez AI"},
    {"label": "Agreement ID", "value": "NDA-2026-0914"},
    {"label": "Governing law", "value": "California"}
  ]
}
```

`terms` travels in the create body next to `decision_window_seconds`, which is how long
the approver has to answer and is not part of the terms:
[HTTP quickstart](http-quickstart.md).

Profiles per action type (purchase, disclosure, permission):
[terms guidance](https://github.com/yanez-compliance/yanez-agent-authorization/blob/main/skills/yanez-authorize/references/terms-guidance.md).

## Terms are compared whole

Every field travels into the receipt as `yanez_terms`, and the same object travels
inside the bytes the approver signed. Both are compared structurally at enforcement
time. Re-titling an approval screen produces terms that no longer match what the action
executor expects, so build the object once and hand the same object to both the create
call and the executor: [receipts](receipts.md).

"Structurally" has precise rules — a boolean is never a number, `-0` equals `0`, and
array order matters. Use the SDK's `terms_equal` / `termsEqual` rather than a stock deep
-equality helper, which will disagree with the other language on at least one of those:
[comparing terms](user-signed-approvals.md#comparing-terms).

If any material field changes after approval — counterparty, resource, amount,
currency, destination, scope, deadline — the old receipt must not be used. New terms
mean a new authorization request.
