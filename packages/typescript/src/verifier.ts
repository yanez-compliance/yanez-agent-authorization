import { isDeepStrictEqual } from "node:util";

import { decodeProtectedHeader, importJWK, jwtVerify } from "jose";

import { FetchLike, raiseFor, requireTrustedOrigin } from "./client.js";
import {
  AlreadyConsumedError,
  ConsentPolicyError,
  ReceiptVerificationError,
  TransportError,
} from "./errors.js";
import { IntrospectionResult, Terms, VerifiedReceipt } from "./models.js";

const KEY_CACHE_TTL_MS = 600_000;
// An unknown kid may refresh the key set, but not more often than this: a flood
// of garbage kids must not become a flood of JWKS fetches.
const KEY_REFRESH_COOLDOWN_MS = 30_000;
// A decided_at slightly ahead of our clock is skew; further ahead is not a receipt.
const CLOCK_SKEW_SECONDS = 60;

const REQUIRED_CLAIMS = [
  "sub", "jti", "iat",
  "yanez_agent_key_id", "yanez_decision", "yanez_decided_at",
  "yanez_match_overlap", "yanez_terms",
] as const;
const STRING_CLAIMS = ["sub", "jti", "yanez_agent_key_id"] as const;

export interface ReceiptVerifierOptions {
  timeoutSeconds?: number;
  /** Clock in epoch seconds; injectable for tests. */
  now?: () => number;
  fetch?: FetchLike;
}

export interface VerifyOptions {
  /** Clock override in epoch seconds. */
  now?: number;
  /** Bind the receipt to the user and agent key this relying party expects. */
  expectedSub?: string;
  expectedAgentKeyId?: string;
}

function errName(e: unknown): string {
  return e instanceof Error ? e.name : String(e);
}

/**
 * Relying-party verification. Needs no agent key — a receipt is portable proof.
 *
 * `expectedIssuer` is mandatory: the unverified `iss` claim is never trusted to
 * name its own authority.
 */
export class ReceiptVerifier {
  private readonly baseUrl: string;
  private readonly issuer: string;
  private readonly timeoutSeconds: number;
  private readonly now: () => number;
  private readonly fetchFn: FetchLike;
  private keys = new Map<string, CryptoKey>();
  private keysFetchedAt = Number.NEGATIVE_INFINITY;

  constructor(baseUrl: string, expectedIssuer: string, options: ReceiptVerifierOptions = {}) {
    if (!expectedIssuer) throw new Error("expectedIssuer is mandatory");
    this.baseUrl = requireTrustedOrigin(baseUrl);
    this.issuer = expectedIssuer;
    this.timeoutSeconds = options.timeoutSeconds ?? 10;
    this.now = options.now ?? (() => Date.now() / 1000);
    this.fetchFn = options.fetch ?? globalThis.fetch;
  }

  // --- key set ---

  private async fetchKeys(): Promise<void> {
    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}/api/authz/public-keys`, {
        redirect: "manual",
        signal: AbortSignal.timeout(this.timeoutSeconds * 1000),
      });
    } catch (e) {
      throw new TransportError(errName(e));
    }
    // A 404 here means the feature is absent, exactly as on create.
    await raiseFor(response, { create: true });
    let data: any;
    try {
      data = await response.json();
    } catch {
      throw new TransportError("malformed key set");
    }
    if (data === null || typeof data !== "object" || !Array.isArray(data.keys)) {
      throw new TransportError("malformed key set");
    }
    const keys = new Map<string, CryptoKey>();
    for (const jwk of data.keys) {
      if (jwk?.kty === "OKP" && jwk.crv === "Ed25519" && typeof jwk.kid === "string") {
        try {
          // importJWK returns a CryptoKey for asymmetric JWKs; Uint8Array only for oct.
          const key = (await importJWK(
            { kty: jwk.kty, crv: jwk.crv, x: jwk.x }, "EdDSA")) as unknown as CryptoKey;
          keys.set(jwk.kid, key);
        } catch {
          // One bad entry must not take the whole key set down with it.
        }
      }
    }
    this.keys = keys;
    this.keysFetchedAt = performance.now();
  }

  /**
   * Cached for ten minutes; an unknown kid refreshes at most once per cooldown so
   * a freshly rotated key verifies without a restart. Never selected by algorithm.
   */
  private async keyFor(kid: string): Promise<CryptoKey> {
    // keysFetchedAt starts at -Infinity, so "never fetched" falls out of the TTL check.
    if (performance.now() - this.keysFetchedAt > KEY_CACHE_TTL_MS) {
      await this.fetchKeys();
    }
    if (!this.keys.has(kid) && performance.now() - this.keysFetchedAt > KEY_REFRESH_COOLDOWN_MS) {
      await this.fetchKeys();
    }
    const key = this.keys.get(kid);
    if (key === undefined) throw new ReceiptVerificationError(`unknown signing key "${kid}"`);
    return key;
  }

  // --- verification ---

  /**
   * Signature + profile + exact terms + freshness + consent bound.
   *
   * Freshness (`maxAgeSeconds`, against `yanez_decided_at`) and the user's
   * `yanez_consent_not_after` are THIS relying party's gate on acting; neither
   * affects whether the receipt is genuine. There is deliberately no `exp`
   * requirement — a receipt still verifies years later, when the dispute happens.
   */
  async verify(
    artifact: string,
    expectedTerms: Terms,
    maxAgeSeconds: number,
    options: VerifyOptions = {},
  ): Promise<VerifiedReceipt> {
    const current = options.now ?? this.now();

    let header;
    try {
      header = decodeProtectedHeader(artifact);
    } catch (e) {
      throw new ReceiptVerificationError(errName(e));
    }
    // Pinned algorithm; the token's own header is never an allow-list.
    if (header.alg !== "EdDSA" || !header.kid) {
      throw new ReceiptVerificationError("receipt must be EdDSA with a kid");
    }

    const key = await this.keyFor(header.kid);
    let claims: Record<string, unknown>;
    try {
      const { payload } = await jwtVerify(artifact, key, {
        algorithms: ["EdDSA"],
        issuer: this.issuer,
        // Only applied to exp/nbf when present; a receipt without exp is valid.
        currentDate: new Date(current * 1000),
      });
      claims = payload as Record<string, unknown>;
    } catch (e) {
      throw new ReceiptVerificationError(e instanceof Error ? e.message : String(e));
    }

    for (const name of REQUIRED_CLAIMS) {
      // null is as absent as undefined.
      if (claims[name] == null) throw new ReceiptVerificationError(`missing claim ${name}`);
    }
    for (const name of STRING_CLAIMS) {
      if (typeof claims[name] !== "string") {
        throw new ReceiptVerificationError(`claim ${name} must be a string`);
      }
    }
    // Validated, never cast: a signed "not-a-date" would otherwise compare as false and pass.
    for (const name of ["yanez_decided_at", "yanez_consent_not_after"] as const) {
      if (claims[name] != null && !Number.isInteger(claims[name])) {
        throw new ReceiptVerificationError(`claim ${name} must be an integer NumericDate`);
      }
    }
    if (claims.yanez_decision !== "approved") {
      throw new ReceiptVerificationError("receipt is not an approval");
    }
    if (options.expectedSub !== undefined && claims.sub !== options.expectedSub) {
      throw new ReceiptVerificationError("sub does not match expectedSub");
    }
    if (options.expectedAgentKeyId !== undefined
        && claims.yanez_agent_key_id !== options.expectedAgentKeyId) {
      throw new ReceiptVerificationError("yanez_agent_key_id does not match expectedAgentKeyId");
    }
    if (claims.iat !== claims.yanez_decided_at) {
      throw new ReceiptVerificationError("iat and yanez_decided_at disagree");
    }
    const overlap = claims.yanez_match_overlap;
    // Any non-negative integer: the issuer's block count and threshold are its
    // policy at signing time, not part of this public contract.
    if (typeof overlap !== "number" || !Number.isInteger(overlap) || overlap < 0) {
      throw new ReceiptVerificationError("yanez_match_overlap must be a non-negative integer");
    }
    if (!isDeepStrictEqual(claims.yanez_terms, expectedTerms)) {
      // Deep equality, no ignored or wildcard fields: changed terms mean a new
      // authorization, never a reused receipt.
      throw new ReceiptVerificationError("terms do not match the approved terms");
    }

    const decidedAt = claims.yanez_decided_at as number;
    const notAfter = (claims.yanez_consent_not_after ?? undefined) as number | undefined;
    if (decidedAt > current + CLOCK_SKEW_SECONDS) {
      throw new ReceiptVerificationError("yanez_decided_at is in the future");
    }
    if (current - decidedAt > maxAgeSeconds) {
      throw new ConsentPolicyError(
        `approval is ${Math.trunc(current - decidedAt)}s old, policy allows ${maxAgeSeconds}s`);
    }
    if (notAfter !== undefined && current > notAfter) {
      throw new ConsentPolicyError("past the user's consent bound");
    }

    return {
      sub: claims.sub as string,
      jti: claims.jti as string,
      agentKeyId: claims.yanez_agent_key_id as string,
      decidedAt,
      matchOverlap: overlap,
      terms: claims.yanez_terms as Terms,
      consentNotAfter: notAfter,
    };
  }

  /** Online check; `consume: true` permanently spends the receipt's jti. */
  async introspect(
    artifact: string,
    options: { consume?: boolean; signal?: AbortSignal } = {},
  ): Promise<IntrospectionResult> {
    const { consume = false, signal } = options;
    let response: Response;
    try {
      response = await this.fetchFn(`${this.baseUrl}/api/authz/introspect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ artifact, consume }),
        redirect: "manual",
        signal: signal ?? AbortSignal.timeout(this.timeoutSeconds * 1000),
      });
    } catch (e) {
      throw new TransportError(errName(e));
    }
    // A 404 here means the feature is absent, exactly as on create.
    await raiseFor(response, { create: true });
    const data = (await response.json()) as any;
    return {
      valid: data.valid,
      reason: data.reason ?? undefined,
      consumedNow: data.consumed_now ?? undefined,
      sub: data.sub ?? undefined,
      jti: data.jti ?? undefined,
      decidedAt: data.decided_at ?? undefined,
      consentNotAfter: data.consent_not_after ?? undefined,
      terms: data.terms ?? undefined,
    };
  }

  /**
   * Everything the action boundary needs, in order — but never the action itself.
   *
   * For a single-use action pass `consume: true` and call this immediately before
   * executing. If the action then fails, the receipt stays spent: retry means a
   * new authorization, because consumption and a third-party side effect cannot
   * be one atomic transaction.
   */
  async authorizeAction(
    artifact: string,
    expectedTerms: Terms,
    maxAgeSeconds: number,
    options: { consume: boolean; signal?: AbortSignal } & Omit<VerifyOptions, "now">,
  ): Promise<VerifiedReceipt> {
    const { expectedSub, expectedAgentKeyId } = options;
    const receipt = await this.verify(artifact, expectedTerms, maxAgeSeconds,
      { expectedSub, expectedAgentKeyId });
    if (options.consume) {
      const result = await this.introspect(artifact, { consume: true, signal: options.signal });
      if (result.valid && result.reason === "already_consumed") {
        throw new AlreadyConsumedError("receipt was already spent");
      }
      if (result.valid && result.reason === "consent_expired") {
        throw new ConsentPolicyError("past the user's consent bound");
      }
      if (!result.valid) {
        throw new ReceiptVerificationError(result.reason ?? "invalid receipt");
      }
      // Only a consumption the server confirms may authorize a single-use action.
      if (result.consumedNow !== true) {
        throw new ReceiptVerificationError(
          result.reason ? `receipt was not consumed: ${result.reason}` : "receipt was not consumed");
      }
    }
    return receipt;
  }
}
