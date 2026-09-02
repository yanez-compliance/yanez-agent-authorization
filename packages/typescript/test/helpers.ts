import { readFileSync } from "node:fs";

import { SignJWT, exportJWK, generateKeyPair } from "jose";

// Compiled to dist/test/, so four levels up is the repository root.
const FIXTURES = new URL("../../../../conformance/fixtures/", import.meta.url);

function load(name: string): any {
  return JSON.parse(readFileSync(new URL(name, FIXTURES), "utf8"));
}

export const jwks: any = load("jwks.json");
export const receipts: any = load("receipts.json");
export const httpFixtures: any = load("http.json");

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
