// Wire statuses, verbatim. Exactly one per response; only `approved` carries an artifact.
export type AuthorizationStatus = "pending" | "approved" | "rejected" | "expired";

export const PENDING = "pending";
export const APPROVED = "approved";
export const REJECTED = "rejected";
export const EXPIRED = "expired";
export const TERMINAL: ReadonlySet<string> = new Set([APPROVED, REJECTED, EXPIRED]);

/** Terms are an arbitrary JSON object; the server enforces the 4 KB cap. */
export type Terms = Record<string, unknown>;

export interface PendingAuthorization {
  requestId: string;
  status: AuthorizationStatus;
  decideBy: string;
  idempotencyKey: string;
  /** True when the server answered from an earlier create. */
  replayed: boolean;
}

export interface AuthorizationResult {
  requestId: string;
  status: AuthorizationStatus;
  artifact?: string;
  // ISO timestamps as the server sent them; parse only if you need arithmetic.
  consentNotAfter?: string;
  decidedAt?: string;
}

export interface IntrospectionResult {
  valid: boolean;
  reason?: string;
  consumedNow?: boolean;
  sub?: string;
  jti?: string;
  decidedAt?: number;
  consentNotAfter?: number;
  terms?: Terms;
}

/**
 * A receipt that passed signature, issuer, claim-profile, exact-terms, freshness,
 * and consent checks. Holding one means "permission to act now", not just validity.
 */
export interface VerifiedReceipt {
  sub: string;
  jti: string;
  agentKeyId: string;
  decidedAt: number;
  matchOverlap: number;
  terms: Terms;
  consentNotAfter?: number;
}
