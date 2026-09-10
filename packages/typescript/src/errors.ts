/**
 * Typed errors, one per failure class of the agent-authorization contract.
 *
 * Messages never contain the agent key, the Authorization header, or a raw artifact —
 * only HTTP status and the server's sanitized detail string.
 */

/** Base for every error this SDK throws deliberately. */
export class YanezAuthzError extends Error {
  constructor(message: string) {
    super(message);
    this.name = new.target.name;
  }
}

/** Missing, malformed, or revoked agent key. Do not retry; reissue the key. */
export class AuthenticationError extends YanezAuthzError {}

/** Invalid terms, time, or schema. Fix the request. */
export class InvalidRequestError extends YanezAuthzError {}

/** Terms exceed the server's 4 KB cap. Reduce without losing material facts. */
export class TermsTooLargeError extends YanezAuthzError {}

/** Request or pending limit reached. Wait; never create a replacement loop. */
export class RateLimitError extends YanezAuthzError {}

/** Idempotency mismatch or terminal transition. Inspect the original request. */
export class ConflictError extends YanezAuthzError {}

/** Unknown or cross-key request id. The server discloses nothing more. */
export class NotFoundError extends YanezAuthzError {}

/** Authorization routes are disabled or not deployed. Operator action needed. */
export class FeatureUnavailableError extends YanezAuthzError {}

/**
 * Timeout, TLS, DNS, connection failure — or an unexpected redirect, which is
 * never followed with credentials.
 */
export class TransportError extends YanezAuthzError {}

/** Bad signature, issuer, claims, or exact terms. Never execute the action. */
export class ReceiptVerificationError extends YanezAuthzError {}

/**
 * The approver's own signature is missing, malformed, or does not cover this decision.
 * The Yanez JWT may be perfectly valid; that is not enough. Never execute.
 *
 * Extends `ReceiptVerificationError`, so code that catches the general case still
 * catches this one.
 */
export class UserSignatureError extends ReceiptVerificationError {}

/**
 * The receipt is genuine but stale, past the user's bound, or below your assurance
 * floor. Request new approval.
 */
export class ConsentPolicyError extends YanezAuthzError {}

/** A genuine single-use receipt was previously spent by SOMEONE ELSE. Never execute again. */
export class AlreadyConsumedError extends YanezAuthzError {}

/**
 * **You** already hold this receipt's reservation, from an earlier attempt whose
 * response you lost. This is a successful recovery, not a refusal.
 *
 * The opposite of `AlreadyConsumedError`, which means somebody else holds it and you
 * must never act. Here the receipt is yours to spend, and the danger is the reverse:
 * your earlier attempt may already have performed the downstream action.
 *
 * **Reconcile, do not restart.** Re-send or query the downstream system with the
 * ORIGINAL idempotency key you derived from `jti`. Do not request a new approval —
 * that mints a second `jti` for an action that may already have succeeded, and the
 * duplicate is invisible to every consumption check. See spec §4.8.
 */
export class ReservationHeldError extends YanezAuthzError {
  /** The verified receipt, so you can reconcile without verifying it again. */
  readonly receipt?: unknown;

  constructor(message: string, receipt?: unknown) {
    super(message);
    this.receipt = receipt;
  }
}

/**
 * Map a non-2xx agent-API response to a typed error.
 *
 * A 404 means two different things by route: on create, the whole router is absent
 * (feature disabled); on get, the request id is unknown or belongs to another key.
 */
export function errorForStatus(
  status: number,
  detail: string | undefined,
  options: { create?: boolean } = {},
): YanezAuthzError {
  const message = detail ?? `HTTP ${status}`;
  if (status === 401) return new AuthenticationError(message);
  if (status === 404) {
    return options.create ? new FeatureUnavailableError(message) : new NotFoundError(message);
  }
  if (status === 409) return new ConflictError(message);
  if (status === 413) return new TermsTooLargeError(message);
  if (status === 429) return new RateLimitError(message);
  if (status === 400 || status === 422) return new InvalidRequestError(message);
  return new TransportError(`unexpected HTTP ${status}`);
}
