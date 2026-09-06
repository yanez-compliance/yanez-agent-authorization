---
title: Terms
description: The object the human approves — every required field, and what each one must contain.
---

# Terms

`terms` is the object the human approves and the relying party enforces. The server
validates its shape on create and answers `422` when a field is missing, blank, or the
wrong type. Every field is also a promise to the approver, because the YID app renders
them on the approval screen.

Every field in the following table is required. A string field must hold at least one
non-whitespace character. The whole object is capped at 4 KB of compact JSON, and the
server answers `413` above that.

| Field | Type | Meaning |
|---|---|---|
| `action` | string | What kind of action this is, such as `purchase`. Free-form for now. Keep it short, lowercase, and identical across identical operations, so a relying party can branch on it |
| `approval_title` | string | The headline the YID app shows the approver. Name the action, not your product |
| `summary` | string | The line under the title. State the whole action in one sentence, including the amount |
| `merchant` | string | The seller's name, spelled the way the approver recognizes it |
| `currency` | string | Currency of the action. Use the ISO 4217 alpha-3 code, such as `USD`. The server checks only that the string isn't blank |
| `amount` | object | What gets charged, described in the following section |
| `details` | array | The rows the app renders as a table, described in the following section |

`merchant`, `currency`, and `amount` are required for every action today, including
actions that move no money, because the app renders one approval screen for every
action. Non-money profiles are unsettled and this requirement can relax later.

Extra keys are allowed at every level. Domain fields the relying party matches on, such
as an item id, a resource id, or a scope list, go alongside the required ones; the
server stores them untouched and they are compared with everything else at enforcement
time. `details` is for what the human reads, extra keys are for what the executor
checks.

## amount

| Field | Type | Meaning |
|---|---|---|
| `minor_units` | integer | The amount as a whole number of the currency's minor unit, which is the smallest denomination the currency charges in. Under `USD` the minor unit is the cent, so `18000` is $180.00. Under a zero-decimal currency such as `JPY` the minor unit is the yen, so `18000` is ¥18,000. Must be a non-negative integer no greater than 9223372036854775807, which is 2^63 - 1 and the largest value the YID app can decode. Never a float and never a decimal string |
| `currency` | string | Must equal the top-level `currency` exactly |
| `display` | string | The amount as the approver reads it, formatted for the currency, such as `"$180.00"` |

**Caution:** `display` is what the human sees, and `minor_units` is what gets charged.
The server can't tell you the two disagree. Derive `display` from `minor_units` and
`currency` in one place instead of passing them in separately.

## details

Each entry has three required fields: `label` and `value` are non-blank strings, and
`emphasized` is a boolean carried on every entry, where `true` renders the row with
visual emphasis. The app renders the entries as a two-column table in array order, so
the array order is the reading order. The app doesn't sort, merge, or drop rows.

The array can be empty, but give it rows. The table is where the approver checks the
specifics of what they're agreeing to, and a screen carrying only a title and a summary
leaves them less to check.

## agent_name

`agent_name` is the one optional field. It names the agent doing the asking, and the YID
app shows it on the approval screen:

```json
{"agent_name": "Shopping agent"}
```

Omit it, or send `null`, and the app falls back to the label on the agent key. A blank
string is a `422` rather than a fallback, because the app reads `null` as "use the key's
label" and a blank string as "show nothing", so the server refuses the one that renders
an empty name. Any non-string value is a `422` as well.

## An example

```json
{
  "action": "purchase",
  "approval_title": "Purchase running shoes",
  "summary": "Buy running shoes for $180.00 at Example Store",
  "merchant": "Example Store",
  "currency": "USD",
  "amount": {"minor_units": 18000, "currency": "USD", "display": "$180.00"},
  "details": [
    {"label": "Merchant", "value": "Example Store", "emphasized": false},
    {"label": "Item", "value": "Running shoes, model X, size 10", "emphasized": false},
    {"label": "Amount", "value": "$180.00", "emphasized": true}
  ]
}
```

`terms` travels in the create body next to `decision_window_seconds`, which is how long
the approver has to answer and is not part of the terms:
[HTTP quickstart](http-quickstart.md).

Profiles per action type (purchase, disclosure, permission):
[terms guidance](https://github.com/yanez-compliance/yanez-agent-authorization/blob/main/skills/yanez-authorize/references/terms-guidance.md).

## Terms are compared whole

Every field travels into the receipt as `yanez_terms` and is compared by deep JSON
equality at enforcement time, display strings included. Re-titling an approval screen
or reformatting `display` produces terms that no longer match what the action executor
expects, so build the object once and hand the same object to both the create call and
the executor: [receipts](receipts.md).

If any material field changes after approval — counterparty, resource, amount,
currency, destination, scope, deadline — the old receipt must not be used. New terms
mean a new authorization request.
