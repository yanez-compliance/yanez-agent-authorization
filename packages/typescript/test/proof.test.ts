// The approver's own signature: the standalone helpers, and the policy gates built on
// them.
//
// Every signature checked here was produced by py_ecc in conformance/generate_fixtures.py
// and is verified by @noble/curves. Two independent implementations agreeing on the same
// bytes is the only cross-check available until real device vectors land — a library
// verifying its own output proves the plumbing, not the parameters.
import assert from "node:assert/strict";
import { test } from "node:test";

import { decodeJwt } from "jose";

import {
  ConsentPolicyError,
  ReceiptVerifier,
  ReservationHeldError,
  UserProofError,
  UserSignatureError,
  decodeSignedMessage,
  keyIsRegistered,
  parseJsonStrict,
  termsEqual,
  verifyBlsSignature,
  verifyUserProof,
} from "../src/index.js";
import { httpFixtures, jsonResponse, jwks, receipts, userKeys } from "./helpers.js";

const BASE = "https://yanez.test";
const ISSUER = "https://yanez.test";
const TOKEN = "executor-attempt-1";

function claimsOf(name = "valid"): Record<string, unknown> {
  return decodeJwt(receipts.cases[name].artifact) as Record<string, unknown>;
}

function makeVerifier(extraHandler?: () => Response, options: any = {}) {
  const fetchStub = async (input: string | URL): Promise<Response> => {
    const url = new URL(String(input));
    if (url.pathname === "/api/authz/public-keys") return jsonResponse(200, jwks);
    if (extraHandler) return extraHandler();
    return jsonResponse(404, { detail: "unknown" });
  };
  return new ReceiptVerifier(BASE, ISSUER, { fetch: fetchStub, ...options });
}

// --- the standalone path: no client, no network, no SDK JWT handling ---

test("verifyUserProof works on claims from any JWT library", () => {
  const proof = verifyUserProof(claimsOf(), { expectedIssuer: receipts.issuer });

  assert.strictEqual(proof.assuranceTier, receipts.assurance_tier);
  assert.strictEqual(proof.publicKey, receipts.user_public_key);
  assert.strictEqual(proof.signedAt, receipts.signed_at);
  assert.strictEqual(proof.decision, "approve");
  assert.deepStrictEqual(proof.terms, receipts.expected_terms);
  // The bytes that were verified, not a re-encode of the parsed envelope.
  assert.deepStrictEqual(
    JSON.parse(Buffer.from(proof.signedMessage).toString("utf8")), proof.envelope);
});

test("a py_ecc signature verifies under @noble/curves", () => {
  // The parameter check the spec asks for: same DST, same scheme, two implementations.
  const claims = claimsOf();
  const raw = decodeSignedMessage(claims.yanez_signed_message);
  assert.ok(verifyBlsSignature(raw, claims.yanez_user_signature, claims.yanez_user_public_key));
});

test("every reject vector throws and says why", () => {
  let checked = 0;
  for (const [name, c] of Object.entries(receipts.cases) as [string, any][]) {
    if (c.error !== "user_signature") continue;
    checked += 1;
    assert.throws(
      () => verifyUserProof(claimsOf(name), { expectedIssuer: receipts.issuer }),
      (e: unknown) => e instanceof UserProofError && e.message.length > 0,
      name);
  }
  assert.ok(checked >= 15, "the reject vectors went missing from the fixtures");
});

test("the signature itself is what rejects a swapped message", () => {
  // `user_message_swapped` passes every field cross-check. Only the curve arithmetic
  // separates it from a genuine receipt — proof the field checks are not doing this
  // work by accident.
  const claims = claimsOf("user_message_swapped") as any;
  const raw = decodeSignedMessage(claims.yanez_signed_message);
  const envelope = JSON.parse(Buffer.from(raw).toString("utf8"));

  assert.strictEqual(envelope.authorization_request_id, claims.jti);
  assert.strictEqual(envelope.yid, claims.sub);
  assert.strictEqual(envelope.assurance_tier, claims.yanez_assurance_tier);
  assert.ok(termsEqual(envelope.terms, claims.yanez_terms));
  assert.ok(!verifyBlsSignature(raw, claims.yanez_user_signature, claims.yanez_user_public_key));
});

test("BLS verification accepts either hex spelling", () => {
  const claims = claimsOf() as any;
  const raw = decodeSignedMessage(claims.yanez_signed_message);
  const bareKey = claims.yanez_user_public_key.slice(2);
  const bareSig = claims.yanez_user_signature.slice(2);

  assert.ok(verifyBlsSignature(raw, claims.yanez_user_signature, claims.yanez_user_public_key));
  assert.ok(verifyBlsSignature(raw, bareSig, bareKey));
  assert.ok(verifyBlsSignature(raw, bareSig.toUpperCase(), bareKey.toUpperCase()));
});

test("malformed crypto inputs return false rather than throwing", () => {
  // An executor's request handler must not see a curve exception.
  const claims = claimsOf() as any;
  const raw = decodeSignedMessage(claims.yanez_signed_message);

  for (const bad of ["", "0x", "zz".repeat(96), "ab".repeat(95), `0x${"00".repeat(96)}`, null, 7]) {
    assert.strictEqual(verifyBlsSignature(raw, bad, claims.yanez_user_public_key), false);
  }
  for (const bad of ["", `0x${"00".repeat(48)}`, "ff".repeat(48), "ab".repeat(47), undefined]) {
    assert.strictEqual(verifyBlsSignature(raw, claims.yanez_user_signature, bad), false);
  }
});

test("signed_message must be canonical base64url", () => {
  const claims = claimsOf() as any;
  const raw = decodeSignedMessage(claims.yanez_signed_message);
  assert.strictEqual(Buffer.from(raw).toString("base64url"), claims.yanez_signed_message);

  for (const bad of ["", "!!!!", `${claims.yanez_signed_message}=`, "a".repeat(30_000), 7, null]) {
    assert.throws(() => decodeSignedMessage(bad), UserProofError);
  }
});

test("duplicate keys in the signed message are refused", () => {
  // Two verifiers reading one byte string must not compare different values. The
  // signature over such a message is genuine; the message is the problem.
  assert.throws(() => parseJsonStrict('{"decision":"approve","decision":"reject"}'), /duplicate/);
  // A repeated key in a nested object, and one that only looks like a key.
  assert.throws(() => parseJsonStrict('{"a":{"x":1,"x":2}}'), /duplicate/);
  assert.deepStrictEqual(parseJsonStrict('{"a":["x","x"],"b":"c:d"}'), { a: ["x", "x"], b: "c:d" });
  // The same name at two different levels is not a duplicate.
  assert.deepStrictEqual(parseJsonStrict('{"a":1,"b":{"a":2}}'), { a: 1, b: { a: 2 } });
});

test("terms comparison matches the Python SDK on the cases that split verifiers", () => {
  // -0 equals 0 (isDeepStrictEqual says otherwise, which is why neither SDK uses it).
  assert.ok(termsEqual({ n: -0 }, { n: 0 }));
  // A boolean is never a number.
  assert.ok(!termsEqual({ n: true }, { n: 1 }));
  assert.ok(!termsEqual({ n: 1 }, { n: true }));
  // Array order is significant.
  assert.ok(!termsEqual([1, 2], [2, 1]));
  // Key sets must match exactly, in both directions.
  assert.ok(!termsEqual({ a: 1 }, { a: 1, b: 2 }));
  assert.ok(!termsEqual({ a: 1, b: 2 }, { a: 1 }));
  assert.ok(!termsEqual({ a: 1 }, { b: 1 }));
  assert.ok(termsEqual(receipts.expected_terms, receipts.expected_terms));
});

// --- policy gates an executor applies on top ---

test("the assurance floor is a policy denial, not a bad receipt", async () => {
  const verifier = makeVerifier();
  const low = receipts.cases.assurance_tier_low.artifact;
  const terms = receipts.expected_terms;
  const now = receipts.now_fresh;

  assert.strictEqual((await verifier.verify(low, terms, 900, { now })).assuranceTier, "low");
  assert.ok(await verifier.verify(low, terms, 900, { now, minAssuranceTier: "low" }));
  // Genuine, and not strong enough. A different problem from a forged receipt, and the
  // caller must be able to tell them apart.
  await assert.rejects(
    verifier.verify(low, terms, 900, { now, minAssuranceTier: "high" }), ConsentPolicyError);

  const high = receipts.cases.valid.artifact;
  assert.ok(await verifier.verify(high, terms, 900, { now, minAssuranceTier: "high" }));
});

test("the registry check normalizes both spellings", () => {
  // The receipt claim carries `0x` and the registry does not. A raw string compare
  // finds nothing, which reads as "this key is not the user's" — the most alarming
  // possible way to be wrong.
  const key = receipts.user_public_key;
  const tier = receipts.assurance_tier;

  assert.ok(key.startsWith("0x") && !userKeys.keys[0].public_key.startsWith("0x"));
  assert.ok(keyIsRegistered(key, tier, userKeys.keys));
  assert.ok(keyIsRegistered(key.slice(2), tier, userKeys.keys));
  assert.ok(keyIsRegistered(key.toUpperCase(), tier, userKeys.keys));

  // Right key, wrong tier: the registry holds it at `high`, not at `medium`.
  assert.ok(!keyIsRegistered(key, "medium", userKeys.keys));
  // A key recorded with no tier can never verify a decision, so it never matches.
  assert.ok(!keyIsRegistered("cc".repeat(48), null, userKeys.keys));
  assert.ok(!keyIsRegistered("dd".repeat(48), tier, userKeys.keys));
  assert.ok(!keyIsRegistered(key, tier, []));
  assert.ok(!keyIsRegistered(key, tier, "not a list"));
});

// --- consumption ---

test("consumerToken is required to consume and refused otherwise", async () => {
  const verifier = makeVerifier();
  const artifact = receipts.cases.valid.artifact;

  for (const bad of [undefined, "", "   "]) {
    await assert.rejects(
      verifier.introspect(artifact, { consume: true, consumerToken: bad }), /consumerToken/);
  }
  // Inspection is not consumption; a polling caller has nothing to own.
  await assert.rejects(
    verifier.introspect(artifact, { consume: false, consumerToken: TOKEN }), /only meaningful/);
});

test("the token travels on the wire only when consuming", async () => {
  const bodies: any[] = [];
  const fetchStub = async (input: string | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input));
    if (url.pathname === "/api/authz/public-keys") return jsonResponse(200, jwks);
    bodies.push(JSON.parse(String(init?.body)));
    return jsonResponse(200, httpFixtures.introspect_first_consume);
  };
  const verifier = new ReceiptVerifier(BASE, ISSUER, { fetch: fetchStub });
  const artifact = receipts.cases.valid.artifact;

  await verifier.introspect(artifact, { consume: false });
  await verifier.introspect(artifact, { consume: true, consumerToken: TOKEN });

  assert.ok(!("consumer_token" in bodies[0]));
  assert.strictEqual(bodies[1].consumer_token, TOKEN);
});

test("reservation_held is recovery and carries the receipt", async () => {
  // The lost-response case the token exists for. Distinct from already_consumed: that
  // one is settled against you, this one is yours to reconcile.
  const verifier = makeVerifier(
    () => jsonResponse(200, httpFixtures.introspect_reservation_held),
    { now: () => receipts.now_fresh });

  await assert.rejects(
    verifier.authorizeAction(receipts.cases.valid.artifact, receipts.expected_terms, 900,
      { consume: true, consumerToken: TOKEN }),
    (e: unknown) => {
      assert.ok(e instanceof ReservationHeldError);
      assert.strictEqual((e.receipt as any).jti, httpFixtures.introspect_reservation_held.jti);
      assert.match(e.message, /idempotency/);
      return true;
    });
});

test("a receipt without a user proof is a user-signature failure", async () => {
  // It records a real approval. It is not a user-signed one, and the error says so
  // rather than reporting a generic missing claim.
  const verifier = makeVerifier();
  await assert.rejects(
    verifier.verify(receipts.cases.user_proof_absent.artifact, receipts.expected_terms, 900,
      { now: receipts.now_fresh }),
    (e: unknown) => e instanceof UserSignatureError && /no user proof/.test(e.message));
});
