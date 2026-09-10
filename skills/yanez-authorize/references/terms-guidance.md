# Writing terms

The server validates the shape of `terms` and answers `422` when a field is missing,
blank, or the wrong type. The human then approves what's inside on a phone screen, and
the relying party compares it by deep JSON equality, every field, no wildcards. Terms
must be specific enough that approval means one thing.

Full field reference:
[terms](https://yanez-compliance.github.io/yanez-agent-authorization/terms/).

## Required shape

Every field is required on every action, including actions that move no money:

```json
{
  "schema_version": 1,
  "action": "purchase",
  "approval_title": "Purchase PEP Research queries",
  "summary": "Buy a bundle of 10 Yanez PEP Research queries",
  "merchant": "Yanez PEP Research",
  "currency": "USD",
  "amount": {"minor_units": 100, "currency": "USD"},
  "details": [
    {"label": "Merchant", "value": "Yanez PEP Research", "emphasized": false},
    {"label": "Bundle", "value": "10 PEP Research queries", "emphasized": false},
    {"label": "Amount", "value": "$1.00", "emphasized": true}
  ]
}
```

Rules:

- Every string holds at least one non-whitespace character.
- `action` is short, lowercase, and specific: `purchase`, `disclose_data`,
  `grant_permission`. Free-form for now, so keep it identical across identical
  operations.
- `approval_title` names the action, not your product. `summary` states the whole
  action in one line, including the amount.
- `schema_version` is `1`, the integer. It is required, and there is no fallback to
  permissive validation when it is missing.
- `amount.minor_units` is a non-negative integer in the currency's minor unit: `100`
  under `USD` is $1.00, `100` under `JPY` is ¥100. Never a float, never a decimal
  string, and never above 2^53 - 1 — the largest integer a double round-trips exactly,
  so a JavaScript verifier and a Python one cannot disagree about the value. The same
  rule and bound apply to every other number anywhere in `terms`.
- `amount.currency` equals the top-level `currency`. There is **no** `amount.display`:
  the app formats the amount from `minor_units` and the currency's own exponent. Two
  fields describing one amount can disagree, and the one the human reads was the one
  that could lie.
- `details` renders as a two-column table in array order, so the array order is the
  reading order. `label`, `value`, and `emphasized` are required on every entry.
  Emphasize the amount row. The array can be empty, but rows are what the approver
  checks, so include them.
- `agent_name` is the one optional field. It names your agent on the approval screen.
  Omit it or send `null` to fall back to the agent key's label; a blank string is a
  `422`, not a fallback.
- Extra keys are allowed at every level. Domain fields the relying party matches on
  (`item_id`, `resource_id`, `scopes`) go alongside the required ones; `details` is for
  what the human reads.
- Carry only facts the user and the relying party need. No secrets, no unnecessary
  personal data.
- Any other decimal quantity travels as a string (`"1.5"`), never a float.
- Under 4 KB of compact JSON.

Display strings are part of the compared terms. Build the object once and hand the same
object to both the create call and the action executor.

## Profiles

Data disclosure. The counterparty goes in `merchant`, and a free action still carries
an amount:

```json
{
  "schema_version": 1,
  "action": "disclose_data",
  "approval_title": "Share your August health report",
  "summary": "Send the August health report to Example Clinic",
  "merchant": "Example Clinic",
  "currency": "USD",
  "amount": {"minor_units": 0, "currency": "USD"},
  "details": [
    {"label": "Recipient", "value": "Example Clinic", "emphasized": false},
    {"label": "Report", "value": "August 2026 health report", "emphasized": true},
    {"label": "Data", "value": "Activity, heart rate", "emphasized": false},
    {"label": "Purpose", "value": "Annual physical", "emphasized": false}
  ]
}
```

Permission change:

```json
{
  "schema_version": 1,
  "action": "grant_permission",
  "approval_title": "Give Example App your calendar",
  "summary": "Allow Example App to read calendar events for 7 days",
  "merchant": "Example App",
  "currency": "USD",
  "amount": {"minor_units": 0, "currency": "USD"},
  "details": [
    {"label": "App", "value": "Example App", "emphasized": false},
    {"label": "Access", "value": "Read calendar events", "emphasized": true},
    {"label": "Calendar", "value": "Primary calendar", "emphasized": false},
    {"label": "Expires", "value": "In 7 days", "emphasized": false}
  ]
}
```

Exceeding an earlier user limit? Say so in `summary` and add a `details` row naming the
original limit.

The action executor owns schema validation and the mapping from business inputs to the
exact expected terms.
