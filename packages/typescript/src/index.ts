/**
 * Yanez agent authorization SDK.
 *
 * Two halves, deliberately separate:
 *
 * - `AuthorizationClient` — the agent side: ask the key's owner to approve terms,
 *   poll for the decision. Needs the yak_ agent key.
 * - `ReceiptVerifier` — the relying-party side: verify and (for single-use actions)
 *   consume a signed receipt. Needs no credentials at all.
 *
 * A receipt carries two signatures: Yanez's Ed25519 signature over the receipt, and the
 * approver's own BLS signature over the decision they made. `ReceiptVerifier.verify`
 * checks both. If you decode receipts with your own JWT library, call `verifyUserProof`
 * directly — that is the half a JWT tutorial will not tell you about.
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
  ReservationHeldError,
  TermsTooLargeError,
  TransportError,
  UserSignatureError,
  YanezAuthzError,
  errorForStatus,
} from "./errors.js";
export {
  ENVELOPE_ACTION,
  ENVELOPE_VERSION,
  USER_SIG_ALG,
  UserProofError,
  decodeSignedMessage,
  keyIsRegistered,
  parseJsonStrict,
  termsEqual,
  verifyBlsSignature,
  verifyUserProof,
  type RegisteredKey,
  type UserProof,
} from "./proof.js";
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
  type UserKeys,
  type VerifiedReceipt,
} from "./models.js";
export {
  ReceiptVerifier,
  type AssuranceTier,
  type ReceiptVerifierOptions,
  type VerifyOptions,
} from "./verifier.js";
