# @yanez.ai/agent-authorization

TypeScript SDK for Yanez agent authorization: request a human's approval of an
action's terms, then verify the signed receipt before acting.

```sh
npm install @yanez.ai/agent-authorization@beta
```

This package is pre-release, so releases publish under the `beta` dist-tag.

## Agent side

```ts
import { AuthorizationClient } from "@yanez.ai/agent-authorization";

const client = new AuthorizationClient(process.env.YANEZ_BASE_URL!, process.env.YANEZ_AGENT_API_KEY!);
const pending = await client.requestAuthorization({
  schema_version: 1,
  action: "purchase",
  approval_title: "Purchase running shoes",
  summary: "Buy running shoes for $180.00 at Example Store",
  merchant: "Example Store",
  currency: "USD",
  amount: { minor_units: 18000, currency: "USD" },
  details: [{ label: "Amount", value: "$180.00", emphasized: true }],
});
const result = await client.waitForAuthorization(pending.requestId, 900);
// When result.status is "approved", result.artifact is the signed receipt.
```

`waitForAuthorization` throws a `DOMException` named `TimeoutError` when the local
deadline passes; rejection and expiry are returned as values.

## Relying-party side

```ts
import { ReceiptVerifier } from "@yanez.ai/agent-authorization";

const verifier = new ReceiptVerifier(baseUrl, expectedIssuer);
const receipt = await verifier.authorizeAction(artifact, expectedTerms, 900, {
  consume: true,
  consumerToken: job.token,  // yours, durable, reused verbatim on every retry
  expectedSub: accountYid,   // the YID your records tie to the account
  minAssuranceTier: "high",  // your floor for the value at risk
});
// Execute the action only after this resolves.
receipt.assuranceTier;       // the tier the approver's scan reached, from the signed bytes
receipt.userProof;           // the full verified proof and decoded envelope
```

A receipt carries two signatures — Yanez's, and the approver's own over the decision
they made — and `verify` checks both. Already have a JWT library? Verify the receipt
with it, then call the standalone helper for the half a JWT library cannot do:

```ts
import { verifyUserProof } from "@yanez.ai/agent-authorization";
const proof = verifyUserProof(claims, { expectedIssuer });
```

`consume: true` requires a `consumerToken`. On `ReservationHeldError` your own earlier
attempt already won and lost its response: reconcile downstream with your original
idempotency key rather than requesting a new approval.

Verifying the approver's signature, field by field:
[user-signed-approvals](../../docs/user-signed-approvals.md).
Enforcement model and integration details: [action-enforcement](../../docs/action-enforcement.md).
