// Agent side and relying-party side in one file.
//
//   YANEZ_BASE_URL=... YANEZ_ISSUER=... YANEZ_EXPECTED_YID=... YANEZ_AGENT_API_KEY=yak_... \
//     npx tsx quickstart.mts
//
// YANEZ_ISSUER is the issuer string your Yanez operator publishes for the deployment.
// YANEZ_EXPECTED_YID is the approver's YID (shown in the YID app); a real relying party
// takes it from its own account records.
// Pre-release: the package is not on npm yet; build packages/typescript and `npm link` it.
import { randomUUID } from "node:crypto";

import {
  AlreadyConsumedError,
  AuthorizationClient,
  ReceiptVerifier,
  ReservationHeldError,
  UserSignatureError,
} from "@yanez/agent-authorization";

const TERMS = {
  schema_version: 1,
  action: "purchase",
  approval_title: "Purchase running shoes",
  summary: "Buy running shoes for $180.00 at Example Store",
  merchant: "Example Store",
  currency: "USD",
  amount: { minor_units: 18000, currency: "USD" },
  details: [
    { label: "Merchant", value: "Example Store", emphasized: false },
    { label: "Item", value: "Running shoes, model X, size 10", emphasized: false },
    { label: "Amount", value: "$180.00", emphasized: true },
  ],
};

const baseUrl = process.env.YANEZ_BASE_URL!;

// Agent: ask, then wait for the human.
const client = new AuthorizationClient(baseUrl, process.env.YANEZ_AGENT_API_KEY!);
const pending = await client.requestAuthorization(TERMS);
console.log(`created ${pending.requestId}; approve it in the YID app`);
const result = await client.waitForAuthorization(pending.requestId, 900);
console.log(`decision: ${result.status}`);

if (result.status === "approved") {
  // Action executor. A real one is a separate service: it rebuilds the expected terms
  // from its own order record and never trusts the agent's copy.
  //
  // Both of these are written down BEFORE consuming, because both exist to survive a
  // crash between consuming and acting. A token minted after a lost response
  // identifies nothing.
  const consumerToken = randomUUID();      // persist this beside the order
  const idempotencyKey = `order-${consumerToken}`;

  const verifier = new ReceiptVerifier(baseUrl, process.env.YANEZ_ISSUER!);
  try {
    const receipt = await verifier.authorizeAction(result.artifact!, TERMS, 900, {
      consume: true,
      consumerToken,
      expectedSub: process.env.YANEZ_EXPECTED_YID!,
      minAssuranceTier: "medium",          // your floor for the value at risk
    });
    // Only reachable when the server confirmed the consumption.
    console.log(`authorized: yid=${receipt.sub} jti=${receipt.jti} `
      + `tier=${receipt.assuranceTier} signedAt=${receipt.signedAt}`);
    console.log(`executing now, idempotencyKey=${idempotencyKey}`);
  } catch (e) {
    if (e instanceof UserSignatureError) {
      // The Yanez signature may be fine. The approver did not sign this decision.
      console.log(`refused, no valid approver signature: ${e.message}`);
    } else if (e instanceof AlreadyConsumedError) {
      console.log("another consumer already spent this receipt; not acting");
    } else if (e instanceof ReservationHeldError) {
      // Recovery, not failure: an earlier attempt of ours won and lost its response.
      console.log(`already held; reconcile downstream with ${idempotencyKey}`);
    } else {
      throw e;
    }
  }
}
