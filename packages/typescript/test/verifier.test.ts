// Verifier behavior against the shared conformance fixtures — the same cases the
// Python SDK runs, so both languages reach the same verdict on every receipt.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  AlreadyConsumedError,
  ConsentPolicyError,
  FeatureUnavailableError,
  InvalidRequestError,
  ReceiptVerificationError,
  ReceiptVerifier,
  TransportError,
  type ReceiptVerifierOptions,
} from "../src/index.js";
import { httpFixtures, jsonResponse, jwks, localIssuer, receipts } from "./helpers.js";

const BASE = "https://yanez.test";
const ISSUER = "https://yanez.test";

const ERRORS: Record<string, new (m: string) => Error> = {
  verification: ReceiptVerificationError,
  consent_policy: ConsentPolicyError,
};

type Handler = (url: URL, init?: RequestInit) => Response | Promise<Response>;

function makeVerifier(extraHandler?: Handler, options: ReceiptVerifierOptions = {}) {
  const calls: string[] = [];
  const fetchStub = async (input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input));
    calls.push(url.pathname);
    if (url.pathname === "/api/authz/public-keys") return jsonResponse(200, jwks);
    if (extraHandler) return extraHandler(url, init);
    return jsonResponse(404, { detail: "unknown" });
  };
  const verifier = new ReceiptVerifier(BASE, ISSUER, { fetch: fetchStub, ...options });
  return { verifier, calls };
}

test("conformance cases", async (t) => {
  const { verifier } = makeVerifier();
  for (const [name, c] of Object.entries(receipts.cases) as [string, any][]) {
    await t.test(name, async () => {
      const now = c.now ?? receipts.now_fresh;
      const expectedTerms = c.expected_terms ?? receipts.expected_terms;
      if (c.ok) {
        const receipt = await verifier.verify(c.artifact, expectedTerms, 900, { now });
        assert.ok(receipt.jti && receipt.sub);
        assert.deepStrictEqual(receipt.terms, receipts.expected_terms);
        assert.ok(receipt.matchOverlap >= 0);
      } else {
        await assert.rejects(
          verifier.verify(c.artifact, expectedTerms, 900, { now }), ERRORS[c.error]);
      }
    });
  }
});

test("valid receipt exposes the full decoded profile", async () => {
  const { verifier } = makeVerifier();
  const c = receipts.cases.valid;
  const receipt = await verifier.verify(c.artifact, receipts.expected_terms, 900,
    { now: receipts.now_fresh });
  assert.strictEqual(receipt.decidedAt, receipts.decided_at);
  assert.ok(receipt.agentKeyId.startsWith("yak_"));
  assert.strictEqual(receipt.consentNotAfter, undefined);
});

test("unknown kids never storm the key endpoint", async () => {
  const { verifier, calls } = makeVerifier();
  const now = receipts.now_fresh;
  await verifier.verify(receipts.cases.valid.artifact, receipts.expected_terms, 900, { now });
  for (let i = 0; i < 5; i++) {
    await assert.rejects(
      verifier.verify(receipts.cases.unknown_kid.artifact, receipts.expected_terms, 900, { now }),
      ReceiptVerificationError);
  }
  assert.strictEqual(calls.filter((p) => p === "/api/authz/public-keys").length, 1);
});

test("rotated kid verifies once the refresh cooldown has passed", async () => {
  // The rotation path the refresh exists for: the second fetch carries the new kid.
  const rotated = { keys: [{ ...jwks.keys[0], kid: "authz_retired" }] };
  let fetches = 0;
  const verifier = new ReceiptVerifier(BASE, ISSUER, {
    fetch: async () => {
      fetches += 1;
      return jsonResponse(200, fetches === 1 ? jwks : rotated);
    },
  });
  const now = receipts.now_fresh;
  const c = receipts.cases.unknown_kid; // signed with kid authz_retired
  // Inside the cooldown the just-fetched set is authoritative.
  await assert.rejects(
    verifier.verify(c.artifact, receipts.expected_terms, 900, { now }), ReceiptVerificationError);
  (verifier as any).keysFetchedAt -= 31_000; // age the cache instead of sleeping
  const receipt = await verifier.verify(c.artifact, receipts.expected_terms, 900, { now });
  assert.ok(receipt.jti);
  assert.strictEqual(fetches, 2);
});

test("malformed key-set entries are skipped and bodies rejected", async () => {
  const c = receipts.cases.valid;
  const verify = (v: ReceiptVerifier) =>
    v.verify(c.artifact, receipts.expected_terms, 900, { now: receipts.now_fresh });
  const withBody = (status: number, body: unknown) =>
    new ReceiptVerifier(BASE, ISSUER, { fetch: async () => jsonResponse(status, body) });

  // A key with no "x" cannot import; the good key beside it must still work.
  const broken = { kty: "OKP", crv: "Ed25519", kid: "broken" };
  const receipt = await verify(withBody(200, { keys: [broken, ...jwks.keys] }));
  assert.ok(receipt.jti);
  await assert.rejects(verify(withBody(200, "nope")), TransportError);
  await assert.rejects(verify(withBody(404, { detail: "Not Found" })), FeatureUnavailableError);
});

/** Verify a freshly minted receipt: the valid baseline with `claims` overlaid. */
async function mintedVerify() {
  const issuer = await localIssuer();
  const verifier = new ReceiptVerifier(BASE, ISSUER, {
    fetch: async () => jsonResponse(200, issuer.jwks),
  });
  const good = {
    iss: ISSUER, sub: "a".repeat(32), jti: "azr_1", iat: receipts.decided_at,
    yanez_agent_key_id: "yak_local1", yanez_decision: "approved",
    yanez_decided_at: receipts.decided_at, yanez_match_overlap: 1,
    yanez_terms: receipts.expected_terms,
  };
  return (claims: Record<string, unknown>) => issuer.sign({ ...good, ...claims })
    .then((a) => verifier.verify(a, receipts.expected_terms, 900, { now: receipts.now_fresh }));
}

test("null or non-string identity claims are rejected", async () => {
  const verify = await mintedVerify();
  assert.ok((await verify({})).jti); // the minted baseline itself is fine
  await assert.rejects(verify({ yanez_agent_key_id: null }),
    { name: "ReceiptVerificationError", message: "missing claim yanez_agent_key_id" });
  await assert.rejects(verify({ sub: 12345 }),
    { name: "ReceiptVerificationError", message: "claim sub must be a string" });
});

test("non-integer NumericDate claims are rejected, not cast", async () => {
  const verify = await mintedVerify();
  await assert.rejects(verify({ yanez_consent_not_after: "not-a-date" }),
    { name: "ReceiptVerificationError",
      message: "claim yanez_consent_not_after must be an integer NumericDate" });
  await assert.rejects(verify({ yanez_decided_at: "x" }),
    { name: "ReceiptVerificationError",
      message: "claim yanez_decided_at must be an integer NumericDate" });
  assert.strictEqual((await verify({ yanez_consent_not_after: null })).consentNotAfter, undefined);
});

test("authorizeAction requires a confirmed consumption", async () => {
  const responses = [
    { valid: true, consumed_now: false },
    { valid: true },
    { valid: true, consumed_now: true },
  ];
  const { verifier } = makeVerifier(() => jsonResponse(200, responses.shift()),
    { now: () => receipts.now_fresh });
  const act = () => verifier.authorizeAction(
    receipts.cases.valid.artifact, receipts.expected_terms, 900, { consume: true });

  await assert.rejects(act(), { name: "ReceiptVerificationError", message: "receipt was not consumed" });
  await assert.rejects(act(), ReceiptVerificationError);
  assert.ok((await act()).jti);
});

test("expectedSub and expectedAgentKeyId bind the receipt", async () => {
  const { verifier } = makeVerifier(undefined, { now: () => receipts.now_fresh });
  const c = receipts.cases.valid;
  const ok = await verifier.verify(c.artifact, receipts.expected_terms, 900,
    { expectedSub: "a".repeat(32), expectedAgentKeyId: "yak_conformance1" });
  assert.ok(ok.jti);
  await assert.rejects(
    verifier.verify(c.artifact, receipts.expected_terms, 900, { expectedSub: "someone-else" }),
    { name: "ReceiptVerificationError", message: "sub does not match expectedSub" });
  await assert.rejects(
    verifier.verify(c.artifact, receipts.expected_terms, 900, { expectedAgentKeyId: "yak_other" }),
    { name: "ReceiptVerificationError",
      message: "yanez_agent_key_id does not match expectedAgentKeyId" });
  // authorizeAction forwards the binding.
  await assert.rejects(
    verifier.authorizeAction(c.artifact, receipts.expected_terms, 900,
      { consume: false, expectedSub: "someone-else" }),
    ReceiptVerificationError);
});

test("a decided_at in the future is not a receipt, within clock skew it is", async () => {
  const { verifier } = makeVerifier();
  const c = receipts.cases.valid;
  await assert.rejects(
    verifier.verify(c.artifact, receipts.expected_terms, 900, { now: receipts.decided_at - 3600 }),
    { name: "ReceiptVerificationError", message: "yanez_decided_at is in the future" });
  const receipt = await verifier.verify(c.artifact, receipts.expected_terms, 900,
    { now: receipts.decided_at - 30 });
  assert.ok(receipt.jti);
});

test("introspect maps HTTP errors like the agent client", async () => {
  const { verifier } = makeVerifier(() => jsonResponse(422, { detail: "bad artifact" }));
  await assert.rejects(verifier.introspect(receipts.cases.valid.artifact), InvalidRequestError);
});

test("key set is cached between verifies", async () => {
  const { verifier, calls } = makeVerifier();
  const c = receipts.cases.valid;
  for (let i = 0; i < 3; i++) {
    await verifier.verify(c.artifact, receipts.expected_terms, 900, { now: receipts.now_fresh });
  }
  assert.strictEqual(calls.filter((p) => p === "/api/authz/public-keys").length, 1);
});

test("introspect and authorizeAction map consumption", async () => {
  const responses = [
    httpFixtures.introspect_first_consume,
    httpFixtures.introspect_repeat_consume,
  ];
  const { verifier } = makeVerifier(() => jsonResponse(200, responses.shift()),
    { now: () => receipts.now_fresh });
  const artifact = receipts.cases.valid.artifact;

  const receipt = await verifier.authorizeAction(artifact, receipts.expected_terms, 900,
    { consume: true });
  assert.strictEqual(receipt.jti, httpFixtures.introspect_first_consume.jti);

  // The repeat is a genuine receipt that must never authorize the action again.
  await assert.rejects(
    verifier.authorizeAction(artifact, receipts.expected_terms, 900, { consume: true }),
    AlreadyConsumedError);
});

test("expectedIssuer is mandatory and https is enforced", () => {
  assert.throws(() => new ReceiptVerifier(BASE, ""));
  assert.throws(() => new ReceiptVerifier("http://yanez.example", ISSUER));
  new ReceiptVerifier("http://127.0.0.1:8001", ISSUER); // loopback development is fine
});
