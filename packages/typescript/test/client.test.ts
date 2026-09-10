// Agent-client behavior: auth header, idempotency, error typing, redirect refusal,
// and terminal-state polling. The network is a stubbed fetch — no real sockets.
import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect } from "node:util";

import {
  AuthenticationError,
  AuthorizationClient,
  ConflictError,
  FeatureUnavailableError,
  InvalidRequestError,
  NotFoundError,
  RateLimitError,
  TermsTooLargeError,
  TransportError,
  type Terms,
} from "../src/index.js";
import { httpFixtures, jsonResponse } from "./helpers.js";

const BASE = "https://yanez.test";
const KEY = "yak_abc123abc123_s3cr3t-value";
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

type Handler = (url: URL, init: RequestInit) => Response | Promise<Response>;

function client(handler: Handler): AuthorizationClient {
  return new AuthorizationClient(BASE, KEY, {
    fetch: async (input, init) => handler(new URL(String(input)), init ?? {}),
  });
}

test("create sends bearer and generated idempotency key", async () => {
  const seen: Record<string, string | null> = {};
  const pending = await client((url, init) => {
    const headers = new Headers(init.headers);
    seen.auth = headers.get("authorization");
    seen.idem = headers.get("idempotency-key");
    return jsonResponse(201, httpFixtures.create_response);
  }).requestAuthorization(TERMS);

  assert.strictEqual(seen.auth, `Bearer ${KEY}`);
  assert.ok(seen.idem);
  assert.strictEqual(pending.idempotencyKey, seen.idem);
  assert.strictEqual(pending.status, "pending");
  assert.strictEqual(pending.replayed, false);
});

test("transport retry reuses the same idempotency key", async () => {
  const attempts: (string | null)[] = [];
  const flaky = new AuthorizationClient(BASE, KEY, {
    fetch: async (input, init) => {
      attempts.push(new Headers(init?.headers).get("idempotency-key"));
      if (attempts.length === 1) throw new TypeError("fetch failed");
      return jsonResponse(201, httpFixtures.create_response,
        { "Idempotency-Replayed": "true" });
    },
  });

  const pending = await flaky.requestAuthorization(TERMS, { idempotencyKey: "retry-1" });
  assert.deepStrictEqual(attempts, ["retry-1", "retry-1"]);
  assert.strictEqual(pending.replayed, true);
});

test("a schema 422 names the field paths and never echoes the payload", async () => {
  // The request validator's array carries the submitted value under `input`; the
  // message reaches logs and MCP tool results, so only the paths may survive.
  const c = client(() => jsonResponse(422, { detail: [
    { type: "bool_type", loc: ["body", "terms", "details", 2, "emphasized"],
      msg: "Input should be a valid boolean", input: { patient: "Jane Doe" } },
    { type: "less_than_equal", loc: ["body", "decision_window_seconds"],
      msg: "Input should be <= 3600", input: 99999 },
  ] }));
  await assert.rejects(c.requestAuthorization(TERMS), (e: Error) => {
    assert.ok(e instanceof InvalidRequestError);
    assert.strictEqual(e.message,
      "invalid request: terms.details[2].emphasized, decision_window_seconds");
    assert.ok(!e.message.includes("Jane Doe") && !e.message.includes("99999"));
    return true;
  });
});

// Compile-time check: the server allows extra keys at every level, so the type must
// too — an inline literal with extras in `amount` and a `details` row has to type-check.
const _extraKeysEverywhere: Terms = {
  ...TERMS,
  amount: { ...TERMS.amount, tax_minor_units: 0 },
  details: [{ label: "Item", value: "Shoes", emphasized: false, icon: "cart" }],
  item_id: "sku_123",
};
void _extraKeysEverywhere;

const STATUS_CASES: [number, new (m: string) => Error, boolean][] = [
  [400, InvalidRequestError, true],
  [401, AuthenticationError, true],
  [404, FeatureUnavailableError, true], // the whole router is absent on create
  [404, NotFoundError, false],          // unknown or cross-key id on get
  [409, ConflictError, true],
  [413, TermsTooLargeError, true],
  [422, InvalidRequestError, true],
  [429, RateLimitError, true],
];

for (const [status, errClass, create] of STATUS_CASES) {
  test(`http ${status} on ${create ? "create" : "get"} maps to ${errClass.name}`, async () => {
    const c = client(() => jsonResponse(status, { detail: "nope" }));
    await assert.rejects(
      create ? c.requestAuthorization(TERMS) : c.getAuthorization("azr_x"),
      errClass);
  });
}

test("errors never carry the agent key", async () => {
  const c = client(() => jsonResponse(401, { detail: "Unauthorized" }));
  await assert.rejects(c.requestAuthorization(TERMS), (e: Error) => {
    assert.ok(e instanceof AuthenticationError);
    assert.ok(!e.message.includes(KEY) && !String(e).includes(KEY));
    return true;
  });
});

test("redirects are transport errors, not followed", async () => {
  const c = client((url, init) => {
    assert.strictEqual(init.redirect, "manual");
    return new Response(null, { status: 307, headers: { Location: "https://evil.example/" } });
  });
  await assert.rejects(c.getAuthorization("azr_x"), TransportError);
});

test("https is required off loopback", () => {
  assert.throws(() => new AuthorizationClient("http://yanez.example", KEY));
  new AuthorizationClient("http://localhost:8001", KEY); // loopback development is fine
});

for (const terminal of ["poll_approved", "poll_rejected", "poll_expired"]) {
  test(`wait returns ${terminal.replace("poll_", "")} as a value`, async () => {
    const responses = [httpFixtures.poll_pending, httpFixtures[terminal]];
    const c = client(() => jsonResponse(200, responses.shift()));

    const result = await c.waitForAuthorization("azr_x", 30, { longPollSeconds: 0 });
    assert.strictEqual(result.status, httpFixtures[terminal].status);
    assert.strictEqual(result.artifact !== undefined, result.status === "approved");
  });
}

test("wait times out locally without touching the request or spinning", async () => {
  let fetches = 0;
  const c = client(() => {
    fetches += 1;
    return jsonResponse(200, httpFixtures.poll_pending); // answers "pending" instantly
  });
  await assert.rejects(
    c.waitForAuthorization("azr_x", 0.3, { longPollSeconds: 0 }),
    (e: Error) => e.name === "TimeoutError");
  assert.ok(fetches <= 3, `busy loop: ${fetches} polls in 300ms`);
});

test("long poll carries wait in the query", async () => {
  let seen: URL | undefined;
  await client((url) => {
    seen = url;
    return jsonResponse(200, httpFixtures.poll_pending);
  }).getAuthorization("azr_x", 25);
  assert.strictEqual(seen?.search, "?wait=25");
});

test("a malformed request id never reaches the network", async () => {
  let fetches = 0;
  const c = client(() => {
    fetches += 1;
    return jsonResponse(200, httpFixtures.poll_pending);
  });
  await assert.rejects(c.getAuthorization("../../admin/keys?x=1"), InvalidRequestError);
  await assert.rejects(c.waitForAuthorization("../../admin/keys?x=1", 1), InvalidRequestError);
  assert.strictEqual(fetches, 0);
});

test("the agent key is invisible to inspect and JSON.stringify", () => {
  const c = new AuthorizationClient(BASE, KEY);
  assert.ok(!inspect(c, { depth: null, showHidden: true }).includes(KEY));
  assert.ok(!JSON.stringify(c).includes(KEY));
});
