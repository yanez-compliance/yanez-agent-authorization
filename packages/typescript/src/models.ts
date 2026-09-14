// Wire statuses, verbatim. Exactly one per response; only `approved` carries an artifact.
export type AuthorizationStatus = "pending" | "approved" | "rejected" | "expired";

export const PENDING = "pending";
export const APPROVED = "approved";
export const REJECTED = "rejected";
export const EXPIRED = "expired";
export const TERMINAL: ReadonlySet<string> = new Set([APPROVED, REJECTED, EXPIRED]);

/**
 * What the human approves. The server rejects a create with 422 unless every required
 * field is present and well-formed, and the YID app renders them on the approval
 * screen. Extra keys are allowed at every level and are compared like everything else.
 * Field rules: https://yanez-compliance.github.io/yanez-agent-authorization/terms/
 */
export interface Terms {
  /** Terms profile version. Must currently be 1. */
  schema_version: 1;
  /** Short, lowercase, identical across identical operations; free-form for now. */
  action: string;
  /** The headline on the approval screen. */
  approval_title: string;
  /** One line stating the whole action, including the amount when present. */
  summary: string;
  /** The counterparty or service name as the approver knows it. */
  merchant: string;
  /** ISO 4217 code such as "USD". Optional when the action has no amount. */
  currency?: string;
  /** Omit for non-financial actions; YanezYID then hides the Amount row. */
  amount?: {
    /** Whole number of the currency's minor unit, 0 to 2^53-1: 18000 is $180.00 under USD. */
    minor_units: number;
    /** Must equal the top-level currency exactly. */
    currency: string;
    [extra: string]: unknown;
  };
  /** Rendered as a two-column table in array order. May be empty. */
  details: {
    label: string;
    value: string;
    emphasized?: boolean;
    [extra: string]: unknown;
  }[];
  /** Names the asking agent; omit or null to fall back to the agent key's label. */
  agent_name?: string | null;
  [extra: string]: unknown;
}

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
