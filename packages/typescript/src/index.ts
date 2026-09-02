/**
 * Yanez agent authorization SDK.
 *
 * Two halves, deliberately separate:
 *
 * - `AuthorizationClient` — the agent side: ask the key's owner to approve terms,
 *   poll for the decision. Needs the yak_ agent key.
 * - `ReceiptVerifier` — the relying-party side: verify and (for single-use actions)
 *   consume a signed receipt. Needs no credentials at all.
 */
export {
  AuthorizationClient,
  requireTrustedOrigin,
  type AuthorizationClientOptions,
  type FetchLike,
  type RequestAuthorizationOptions,
} from "./client.js";
export {
  AlreadyConsumedError,
  AuthenticationError,
  ConflictError,
  ConsentPolicyError,
  FeatureUnavailableError,
  InvalidRequestError,
  NotFoundError,
  RateLimitError,
  ReceiptVerificationError,
  TermsTooLargeError,
  TransportError,
  YanezAuthzError,
  errorForStatus,
} from "./errors.js";
export {
  APPROVED,
  EXPIRED,
  PENDING,
  REJECTED,
  TERMINAL,
  type AuthorizationResult,
  type AuthorizationStatus,
  type IntrospectionResult,
  type PendingAuthorization,
  type Terms,
  type VerifiedReceipt,
} from "./models.js";
export { ReceiptVerifier, type ReceiptVerifierOptions, type VerifyOptions } from "./verifier.js";
