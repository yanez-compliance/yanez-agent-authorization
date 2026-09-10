/**
 * The user's own signature over the decision, and how to check it.
 *
 * A receipt carries two signatures. Yanez signs the receipt with Ed25519, which says
 * "Yanez saw this approval". The approver's own BLS key signs the decision message,
 * which says "the holder of this key approved these exact terms". The second one is
 * what makes a receipt more than a Yanez assertion, and it is the one an executor
 * copying a JWT tutorial will forget.
 *
 * Everything here works on a plain claims object, so you can use it without the rest of
 * this SDK — decode the receipt with any JWT library you already trust, then hand the
 * claims to `verifyUserProof`. The only dependency it adds is the BLS library.
 *
 * Protocol reference: docs/agent-authorization-signed-approval-spec.md §4.1, §4.7, §5.
 */
import { bls12_381 as bls } from "@noble/curves/bls12-381.js";

import type { Terms } from "./models.js";

/** The only signature scheme this version understands, as `yanez_user_sig_alg` spells it. */
export const USER_SIG_ALG = "BLS12-381-G2-basic";
/** The only decision-envelope version this SDK verifies. */
export const ENVELOPE_VERSION = 1;
/** `action` in the signed envelope. A signature over some other action is not a decision. */
export const ENVELOPE_ACTION = "agent_authorizations.decision";

const SIGNATURE_HEX_LEN = 192; // 96-byte compressed G2 point
const PUBLIC_KEY_HEX_LEN = 96; // 48-byte compressed G1 point
const MAX_MESSAGE_CHARS = 21846; // unpadded base64url of 16 KiB
const MAX_MESSAGE_BYTES = 16 * 1024;
const MAX_MESSAGE_DEPTH = 32;
// `signed_at` (device clock, at the ceremony) against `yanez_decided_at` (server clock,
// at submission). Bounding their DIFFERENCE is a statement about ingestion latency and
// clock skew. Comparing either against today's clock would fail every historical
// verification, which is exactly when a receipt matters most — see §4.7 step 5.
const INGESTION_SKEW_SECONDS = 600;

/**
 * The receipt's user signature is missing, malformed, or does not verify.
 *
 * Thrown by the standalone helpers here. `ReceiptVerifier` re-throws these as
 * `UserSignatureError` so a caller can catch the whole verification family at once.
 */
export class UserProofError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UserProofError";
  }
}

/**
 * A verified user signature and the envelope it covers.
 *
 * `signedMessage` is the exact bytes the signature was checked against. Never
 * re-serialize `envelope` to get them back: a re-encode is a different byte string and
 * will not verify.
 */
export interface UserProof {
  assuranceTier: string;
  publicKey: string;
  signature: string;
  signedMessage: Uint8Array;
  envelope: Record<string, unknown>;
  signedAt: number;
  yid: string;
  decision: "approve";
  issuer: string;
  version: number;
  consentNotAfter?: number;
  /** The terms the user signed, as distinct from the terms Yanez attested to. */
  terms: Terms;
}

// --- §3.3 comparison ---

/**
 * Structural equality for terms, per spec §3.3.
 *
 * Three rules that ordinary deep-equality helpers get wrong:
 *
 * - A boolean is never a number. `{n: true}` must not match `{n: 1}`.
 * - Numbers compare by value, so `-0` equals `0`. This is why the SDK no longer uses
 *   `isDeepStrictEqual`, which separates them: Python's `==` does not, and two
 *   verifiers reading the same bytes must reach the same verdict.
 * - Array order is significant. A reordered `details` array is different terms.
 *
 * Duplicate object keys and non-finite numbers are rejected at parse time by
 * `parseJsonStrict`, before either side becomes an object.
 */
export function termsEqual(a: unknown, b: unknown): boolean {
  if (typeof a === "boolean" || typeof b === "boolean") {
    return typeof a === "boolean" && typeof b === "boolean" && a === b;
  }
  if (typeof a === "number" || typeof b === "number") {
    // `===` makes -0 equal 0, matching Python's `==`.
    return typeof a === "number" && typeof b === "number" && a === b;
  }
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((item, i) => termsEqual(item, b[i]));
  }
  if (a !== null && typeof a === "object") {
    if (b === null || typeof b !== "object") return false;
    const left = a as Record<string, unknown>;
    const right = b as Record<string, unknown>;
    const leftKeys = Object.keys(left);
    if (leftKeys.length !== Object.keys(right).length) return false;
    return leftKeys.every(
      (k) => Object.prototype.hasOwnProperty.call(right, k) && termsEqual(left[k], right[k]),
    );
  }
  if (b !== null && typeof b === "object") return false;
  return a === b;
}

/**
 * Reject an object that names the same key twice.
 *
 * `JSON.parse` silently keeps the last one, so two verifiers reading one byte string
 * could compare different values and both believe they agree. The text is already known
 * to be valid JSON when this runs, so the walk only has to find which strings are keys:
 * a string immediately followed by `:` inside an object.
 */
function assertNoDuplicateKeys(text: string): void {
  const stack: (Set<string> | null)[] = [];
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "{") stack.push(new Set());
    else if (ch === "[") stack.push(null);
    else if (ch === "}" || ch === "]") stack.pop();
    else if (ch === '"') {
      let end = i + 1;
      while (end < text.length) {
        if (text[end] === "\\") end += 2;
        else if (text[end] === '"') break;
        else end += 1;
      }
      const raw = text.slice(i, end + 1);
      let after = end + 1;
      while (after < text.length && /\s/.test(text[after])) after += 1;
      const container = stack[stack.length - 1];
      if (text[after] === ":" && container instanceof Set) {
        const key = JSON.parse(raw) as string;
        if (container.has(key)) throw new Error(`duplicate object key: ${key}`);
        container.add(key);
      }
      i = end;
    }
  }
}

function jsonDepth(value: unknown): number {
  // Iterative on purpose: this exists to bound pathological nesting, and a recursive
  // walk would hit the limit it is meant to enforce.
  let depth = 0;
  let frontier: unknown[] = [value];
  while (frontier.length > 0) {
    depth += 1;
    const children: unknown[] = [];
    for (const node of frontier) {
      if (Array.isArray(node)) children.push(...node);
      else if (node !== null && typeof node === "object") {
        children.push(...Object.values(node as Record<string, unknown>));
      }
    }
    frontier = children;
  }
  return depth;
}

/**
 * `JSON.parse` with the §3.3 parse rules.
 *
 * `JSON.parse` already rejects NaN and Infinity, so only duplicate keys and nesting
 * depth need enforcing here.
 */
export function parseJsonStrict(text: string, maxDepth = MAX_MESSAGE_DEPTH): unknown {
  const value = JSON.parse(text);
  assertNoDuplicateKeys(text);
  if (jsonDepth(value) > maxDepth) throw new Error("json is nested too deeply");
  return value;
}

// --- §5 signature check ---

function unhex(value: unknown, expectedLen: number): Uint8Array | null {
  if (typeof value !== "string") return null;
  const cleaned = value.slice(0, 2).toLowerCase() === "0x" ? value.slice(2) : value;
  if (cleaned.length !== expectedLen || !/^[0-9a-fA-F]+$/.test(cleaned)) return null;
  const out = new Uint8Array(cleaned.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    out[i] = Number.parseInt(cleaned.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

/**
 * Verify one BLS signature under the parameters in spec §5.
 *
 * BLS12-381, minimal pubkey size (keys in G1, signatures in G2), the IRTF **basic**
 * scheme: no message augmentation, no proof of possession, DST
 * `BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_NUL_`. `longSignatures` is noble's name for
 * that variant, and its default DST is the basic one. Getting the scheme or the DST
 * wrong produces a verifier that rejects every genuine signature, or worse accepts
 * under parameters nobody else uses.
 *
 * Returns false for a malformed point, a wrong-length input, or a failed check — never
 * throws. `0x` prefixes are accepted on both hex arguments because the receipt claims
 * carry them and the registry does not.
 */
export function verifyBlsSignature(
  message: Uint8Array,
  signatureHex: unknown,
  publicKeyHex: unknown,
): boolean {
  const signature = unhex(signatureHex, SIGNATURE_HEX_LEN);
  const publicKey = unhex(publicKeyHex, PUBLIC_KEY_HEX_LEN);
  if (signature === null || publicKey === null) return false;
  try {
    return bls.longSignatures.verify(signature, bls.longSignatures.hash(message), publicKey);
  } catch {
    // A point that is not on the curve, not in the subgroup, or not decodable at all
    // arrives as a library exception. That is a failed verification, not a crash to
    // propagate into an executor's request handler.
    return false;
  }
}

/**
 * base64url-decode `yanez_signed_message` into the exact signed bytes.
 *
 * Canonical encoding is required: two base64url spellings of one message would both
 * decode, and only one of them can equal the bytes the issuer stored.
 */
export function decodeSignedMessage(signedMessage: unknown): Uint8Array {
  if (typeof signedMessage !== "string" || signedMessage === "") {
    throw new UserProofError("yanez_signed_message must be a non-empty string");
  }
  if (signedMessage.length > MAX_MESSAGE_CHARS) {
    throw new UserProofError("yanez_signed_message is too large");
  }
  if (!/^[A-Za-z0-9_-]+$/.test(signedMessage)) {
    throw new UserProofError("yanez_signed_message is not canonical base64url");
  }
  let raw: Uint8Array;
  try {
    raw = new Uint8Array(Buffer.from(signedMessage, "base64url"));
  } catch {
    throw new UserProofError("yanez_signed_message is not valid base64url");
  }
  if (raw.length > MAX_MESSAGE_BYTES) throw new UserProofError("yanez_signed_message is too large");
  if (Buffer.from(raw).toString("base64url") !== signedMessage) {
    // Node strips padding in base64url output, so this catches trailing-bit variants
    // as well as re-spellings.
    throw new UserProofError("yanez_signed_message is not canonical base64url");
  }
  return raw;
}

// --- §4.7 steps 4 and 5 ---

const PROOF_CLAIMS = [
  "yanez_assurance_tier",
  "yanez_user_public_key",
  "yanez_user_signature",
  "yanez_signed_message",
  "yanez_user_sig_alg",
] as const;

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

/**
 * Check the approver's signature and everything it is bound to.
 *
 * This is §4.7 step 4 (verify the signature) and step 5 (check what was signed), which
 * only make sense together: step 4 alone proves a key signed *some* decision, and step 5
 * is what ties that decision to *this* receipt. Skipping any of step 5's checks makes
 * step 4 decorative.
 *
 * Call it with the claims of a receipt whose Yanez signature you have **already**
 * verified. It does not check the JWT — `ReceiptVerifier.verify` does that first and
 * then calls this. Verifying the user proof on an unverified JWT tells you only that
 * someone assembled a self-consistent bundle.
 *
 * Throws `UserProofError` on any failure.
 */
export function verifyUserProof(
  claims: Record<string, unknown>,
  options: { expectedIssuer: string },
): UserProof {
  const { expectedIssuer } = options;

  if (PROOF_CLAIMS.every((name) => claims[name] == null)) {
    // A receipt minted before signed approvals. It records a real approval, but no user
    // signed it, so it does not meet this contract and must not pass under it.
    throw new UserProofError("receipt carries no user proof");
  }
  if (claims.yanez_user_sig_alg !== USER_SIG_ALG) {
    throw new UserProofError(`unsupported yanez_user_sig_alg ${JSON.stringify(claims.yanez_user_sig_alg)}`);
  }
  for (const name of ["yanez_user_signature", "yanez_user_public_key", "yanez_assurance_tier"] as const) {
    if (typeof claims[name] !== "string" || claims[name] === "") {
      throw new UserProofError(`claim ${name} must be a non-empty string`);
    }
  }
  const signature = claims.yanez_user_signature as string;
  const publicKey = claims.yanez_user_public_key as string;
  const tier = claims.yanez_assurance_tier as string;

  const raw = decodeSignedMessage(claims.yanez_signed_message);

  // Step 4, before parsing: unverified bytes get as little handling as possible.
  if (!verifyBlsSignature(raw, signature, publicKey)) {
    throw new UserProofError("user signature does not verify over yanez_signed_message");
  }

  let envelope: Record<string, unknown>;
  try {
    const parsed = parseJsonStrict(Buffer.from(raw).toString("utf8"));
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("not an object");
    }
    envelope = parsed as Record<string, unknown>;
  } catch (e) {
    throw new UserProofError(
      `signed message is not a valid JSON object: ${e instanceof Error ? e.message : String(e)}`,
    );
  }

  // Step 5. Every one of these, in the order the spec lists them.
  if (envelope.decision !== "approve") {
    // A rejection carries a signature that passes step 4 perfectly well.
    throw new UserProofError("signed decision is not an approval");
  }
  if (envelope.version !== ENVELOPE_VERSION) {
    throw new UserProofError(`unsupported signed envelope version ${JSON.stringify(envelope.version)}`);
  }
  if (envelope.issuer !== expectedIssuer) {
    throw new UserProofError("signed issuer does not match the expected issuer");
  }
  if (claims.iss !== expectedIssuer) {
    throw new UserProofError("receipt iss does not match the expected issuer");
  }
  if (envelope.action !== ENVELOPE_ACTION) {
    throw new UserProofError("signed action is not a decision");
  }
  if (envelope.authorization_request_id !== claims.jti) {
    throw new UserProofError("signed request id does not match the receipt jti");
  }
  if (envelope.yid !== claims.sub) {
    throw new UserProofError("signed yid does not match the receipt sub");
  }
  if (envelope.assurance_tier !== tier) {
    throw new UserProofError("signed assurance tier does not match the receipt claim");
  }

  const signedTerms = envelope.terms;
  if (signedTerms === null || typeof signedTerms !== "object" || Array.isArray(signedTerms)) {
    throw new UserProofError("signed terms must be an object");
  }
  if (!termsEqual(signedTerms, claims.yanez_terms)) {
    // Yanez's account of what was approved and the user's own must agree. When they
    // disagree, the user's copy is the one that was signed, and neither is safe.
    throw new UserProofError("signed terms do not match yanez_terms");
  }

  const bound = envelope.consent_not_after;
  if (bound != null && !isInteger(bound)) {
    throw new UserProofError("signed consent_not_after must be an integer or null");
  }
  const claimBound = claims.yanez_consent_not_after ?? null;
  if ((bound ?? null) !== claimBound) {
    throw new UserProofError("signed consent bound does not match the receipt claim");
  }

  if (!isInteger(envelope.signed_at)) throw new UserProofError("signed_at must be an integer");
  if (!isInteger(claims.yanez_decided_at)) {
    throw new UserProofError("yanez_decided_at must be an integer");
  }
  const signedAt = envelope.signed_at as number;
  if (Math.abs((claims.yanez_decided_at as number) - signedAt) > INGESTION_SKEW_SECONDS) {
    throw new UserProofError("signed_at and yanez_decided_at are too far apart");
  }

  return {
    assuranceTier: tier,
    publicKey,
    signature,
    signedMessage: raw,
    envelope,
    signedAt,
    yid: envelope.yid as string,
    decision: "approve",
    issuer: expectedIssuer,
    version: ENVELOPE_VERSION,
    consentNotAfter: bound == null ? undefined : (bound as number),
    terms: signedTerms as Terms,
  };
}

// --- §4.9 registry cross-check ---

function normalizeKey(value: unknown): string | null {
  if (typeof value !== "string" || value === "") return null;
  const cleaned = value.slice(0, 2).toLowerCase() === "0x" ? value.slice(2) : value;
  return cleaned.toLowerCase() || null;
}

/** One row of `GET /api/agent/user_keys` (spec §4.9). `tier` is null when the registry recorded none. */
export interface RegisteredKey {
  tier: string | null;
  public_key: string;
}

/**
 * Is this the user's key, at the tier it claims?
 *
 * `registeredKeys` is the `keys` array from `GET /api/agent/user_keys` (spec §4.9).
 * Both sides are normalized before comparison — the receipt claim carries a `0x` prefix
 * and the registry does not, and a raw string compare between the two silently reports
 * every key as unregistered.
 *
 * This is a second read path over Yanez's own storage, not independent verification:
 * the registry and the receipt have the same operator. It catches a receipt whose
 * embedded key was substituted while the registry was intact, and it is worth exactly
 * that much. See §4.9.
 */
export function keyIsRegistered(
  publicKey: unknown,
  tier: unknown,
  registeredKeys: unknown,
): boolean {
  const wanted = normalizeKey(publicKey);
  // A key recorded with no tier can never verify a decision (§4.3 step 9 resolves
  // candidates by exact tier), so a null tier on EITHER side matches nothing. Without
  // this guard, asking about a tierless key finds the tierless registry row.
  if (wanted === null || typeof tier !== "string" || tier === "" || !Array.isArray(registeredKeys)) {
    return false;
  }
  return registeredKeys.some((entry) => {
    if (entry === null || typeof entry !== "object") return false;
    const row = entry as Record<string, unknown>;
    return row.tier === tier && normalizeKey(row.public_key) === wanted;
  });
}
