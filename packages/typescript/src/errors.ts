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

/** The receipt is genuine but stale or past the user's bound. Request new approval. */
export class ConsentPolicyError extends YanezAuthzError {}

/** A genuine single-use receipt was previously spent. Never execute again. */
export class AlreadyConsumedError extends YanezAuthzError {}

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
