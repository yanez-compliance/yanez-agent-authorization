# Writing terms

The server treats `terms` as opaque JSON, but the human approves it on a phone screen
and the relying party compares it by deep JSON equality, every field, no wildcards. Terms must be specific enough that
approval means one thing.

Always:

- `action`: short and specific ("purchase", "disclose_data", "grant_permission").
- `summary`: one user-readable line stating the whole action, including the amount.
- Decimal quantities as strings ("180.00"), never floats.
- Only facts the user and relying party need — no secrets, no unnecessary personal data.
- Under 4 KB of compact JSON.

## Recommended profiles

Purchase:

```json
{
  "action": "purchase",
  "summary": "Buy running shoes for $180 at Example Store",
  "item_id": "sku_123",
  "item_description": "Running shoes, model X, size 10",
  "merchant": "Example Store",
  "amount": "180.00",
  "currency": "USD",
  "destination_id": "shipping_address_home"
}
```

Data disclosure:

```json
{
  "action": "disclose_data",
  "summary": "Send the August health report to Example Clinic",
  "recipient": "Example Clinic",
  "data_categories": ["activity", "heart_rate"],
  "resource_id": "report_2026_08",
  "purpose": "Annual physical"
}
```

Permission change:

```json
{
  "action": "grant_permission",
  "summary": "Allow Example App to read calendar events for 7 days",
  "principal": "example-app",
  "scopes": ["calendar.events.read"],
  "resource": "primary-calendar",
  "duration_seconds": 604800
}
```

Exceeding an earlier user limit? Add the reason:
`"original_limit": "150.00"` plus a summary that names the overage.

Profiles are recommendations. The action executor owns schema validation and the
mapping from business inputs to the exact expected terms.
