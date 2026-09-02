// Agent side and relying-party side in one file.
//
//   YANEZ_BASE_URL=... YANEZ_ISSUER=... YANEZ_EXPECTED_YID=... YANEZ_AGENT_API_KEY=yak_... \
//     npx tsx quickstart.mts
//
// YANEZ_ISSUER is the issuer string your Yanez operator publishes for the deployment.
// YANEZ_EXPECTED_YID is the approver's YID (shown in the YID app); a real relying party
// takes it from its own account records.
// Pre-release: the package is not on npm yet; build packages/typescript and `npm link` it.
import { AuthorizationClient, ReceiptVerifier } from "@yanez/agent-authorization";

const TERMS = {
  action: "purchase",
  summary: "Buy running shoes for $180 at Example Store",
  merchant: "Example Store",
  amount: "180.00",
  currency: "USD",
};

const baseUrl = process.env.YANEZ_BASE_URL!;

// Agent: ask, then wait for the human.
const client = new AuthorizationClient(baseUrl, process.env.YANEZ_AGENT_API_KEY!);
const pending = await client.requestAuthorization(TERMS);
console.log(`created ${pending.requestId}; approve it in the YID app`);
const result = await client.waitForAuthorization(pending.requestId, 900);
console.log(`decision: ${result.status}`);

if (result.status === "approved") {
  // Action executor: verify + consume, bound to the YID your records tie to this
  // account, then (and only then) act.
  const verifier = new ReceiptVerifier(baseUrl, process.env.YANEZ_ISSUER!);
  const receipt = await verifier.authorizeAction(result.artifact!, TERMS, 900, {
    consume: true,
    expectedSub: process.env.YANEZ_EXPECTED_YID!,
  });
  console.log(`authorized: yid=${receipt.sub} jti=${receipt.jti} — executing now`);
}
