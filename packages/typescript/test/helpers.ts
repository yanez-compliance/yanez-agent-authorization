import { readFileSync } from "node:fs";

import { bls12_381 as bls } from "@noble/curves/bls12-381.js";
import { SignJWT, exportJWK, generateKeyPair } from "jose";

// Compiled to dist/test/, so four levels up is the repository root.
const FIXTURES = new URL("../../../../conformance/fixtures/", import.meta.url);

function load(name: string): any {
  return JSON.parse(readFileSync(new URL(name, FIXTURES), "utf8"));
}

export const jwks: any = load("jwks.json");
export const receipts: any = load("receipts.json");
export const httpFixtures: any = load("http.json");
export const userKeys: any = load("user_keys.json");

export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

/** A throwaway Ed25519 issuer, for receipts the signed fixtures cannot express. */
export async function localIssuer(kid = "authz_local") {
  const { publicKey, privateKey } = await generateKeyPair("EdDSA", { crv: "Ed25519" });
  const jwk = { ...(await exportJWK(publicKey)), kid, alg: "EdDSA" };
  const sign = (claims: Record<string, unknown>) =>
    new SignJWT(claims).setProtectedHeader({ alg: "EdDSA", kid }).sign(privateKey);
  return { jwks: { keys: [jwk] }, sign };
}


// A throwaway BLS approver, for receipts the signed fixtures cannot express. Fixed
// scalar so a rerun signs identical bytes.
const USER_SK = new Uint8Array(32).fill(7);

/**
 * Canonical JSON, matching the sorted compact form the apps produce.
 *
 * ASCII only: Python's `json.dumps` escapes non-ASCII and `JSON.stringify` does not, so
 * the two would diverge on a non-ASCII string. That does not matter here — these bytes
 * are signed and verified inside this file — but it is why the cross-language check
 * lives in the shared fixtures rather than in a re-encode.
 */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj).sort().map((k) => `${JSON.stringify(k)}:${canonical(obj[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** The §4.1 envelope implied by a claim set, so an overridden claim stays consistent. */
export function envelopeFor(claims: Record<string, any>): Record<string, unknown> {
  return {
    action: "agent_authorizations.decision",
    assurance_tier: claims.yanez_assurance_tier ?? "high",
    authorization_request_id: claims.jti,
    consent_not_after: claims.yanez_consent_not_after ?? null,
    decision: "approve",
    issuer: claims.iss,
    signed_at: claims.yanez_decided_at,
    terms: claims.yanez_terms,
    version: 1,
    yid: claims.sub,
  };
}

/** The five §4.6 proof claims for one envelope, signed with the throwaway approver key. */
export function proofFor(envelope: Record<string, unknown>): Record<string, string> {
  const raw = new TextEncoder().encode(canonical(envelope));
  const signature = bls.longSignatures.sign(bls.longSignatures.hash(raw), USER_SK);
  return {
    yanez_assurance_tier: envelope.assurance_tier as string,
    yanez_user_public_key: `0x${Buffer.from(bls.longSignatures.getPublicKey(USER_SK).toBytes()).toString("hex")}`,
    yanez_user_signature: `0x${Buffer.from(signature.toBytes()).toString("hex")}`,
    yanez_signed_message: Buffer.from(raw).toString("base64url"),
    yanez_user_sig_alg: "BLS12-381-G2-basic",
  };
}
