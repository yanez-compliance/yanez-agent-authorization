# Writing terms

The server validates the shape of `terms` and answers `422` when a field is missing,
blank, or the wrong type. The human then approves what's inside on a phone screen, and
the relying party compares it by deep JSON equality, every field, no wildcards. Terms
must be specific enough that approval means one thing.

Full field reference:
[terms](https://yanez-compliance.github.io/yanez-agent-authorization/terms/).

## Required shape

Financial action:

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
  action in one line, including the amount when one exists.
- `amount.minor_units` is a non-negative integer in the currency's minor unit: `100`
  under `USD` is $1.00, `100` under `JPY` is ¥100. Never a float, never a decimal
  string, and never above 2^53 - 1.
- `amount.currency` equals the top-level `currency`. Do not send `display`; the app
  formats the authoritative amount itself.
- `details` renders as a two-column table in array order, so the array order is the
  reading order. `label` and `value` are required on every entry. `emphasized` is an
  optional boolean; omit it for standard emphasis. Emphasize the amount row when that
  helps the approver. The array can be empty, but rows are what the approver checks, so
  include them.
- `currency` and `amount` are optional as a pair. Omit both for non-financial actions;
  the app then omits its Amount row. Never invent a zero-dollar placeholder.
- `agent_name` names your agent on the approval screen.
  Omit it or send `null` to fall back to the agent key's label; a blank string is a
  `422`, not a fallback.
- Extra keys are allowed at every level. Domain fields the relying party matches on
  (`item_id`, `resource_id`, `scopes`) go alongside the required ones; `details` is for
  what the human reads.
- Carry only facts the user and the relying party need. No secrets, no unnecessary
  personal data.
- Any other decimal quantity travels as a string (`"1.5"`), never a float.
- Under 4 KB of compact JSON.

Build the object once and hand the same object to both the create call and the action
executor.

## Profiles

Document signing. Money fields and optional presentation hints are omitted:

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

Data disclosure. The counterparty goes in `merchant`; money fields are omitted:

```json
{
  "schema_version": 1,
  "action": "disclose_data",
  "approval_title": "Share your August health report",
  "summary": "Send the August health report to Example Clinic",
  "merchant": "Example Clinic",
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
