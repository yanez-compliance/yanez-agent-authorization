# @yanez/agent-authorization

TypeScript SDK for Yanez agent authorization: request a human's approval of an
action's terms, then verify the signed receipt before acting.

```sh
npm install @yanez/agent-authorization
```

This package is pre-release and not yet published to npm.

## Agent side

```ts
import { AuthorizationClient } from "@yanez/agent-authorization";

const client = new AuthorizationClient(process.env.YANEZ_BASE_URL!, process.env.YANEZ_AGENT_API_KEY!);
const pending = await client.requestAuthorization({
  action: "purchase",
  summary: "Buy running shoes for $180 at Example Store",
});
const result = await client.waitForAuthorization(pending.requestId, 900);
// When result.status is "approved", result.artifact is the signed receipt.
```

`waitForAuthorization` throws a `DOMException` named `TimeoutError` when the local
deadline passes; rejection and expiry are returned as values.

## Relying-party side

```ts
import { ReceiptVerifier } from "@yanez/agent-authorization";

const verifier = new ReceiptVerifier(baseUrl, expectedIssuer);
const receipt = await verifier.authorizeAction(artifact, expectedTerms, 900, {
  consume: true,
  expectedSub: accountYid, // the YID your records tie to the account
});
// Execute the action only after this resolves.
```

Enforcement model and integration details: [action-enforcement](../../docs/action-enforcement.md).
