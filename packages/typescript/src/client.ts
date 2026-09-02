import { InvalidRequestError, TransportError, errorForStatus } from "./errors.js";
import {
  AuthorizationResult,
  PendingAuthorization,
  TERMINAL,
  Terms,
} from "./models.js";

/** Injectable for tests; defaults to the platform fetch. */
export type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1"]);

// Server ids look like azr_<hex>; anything else is a path splice, not an id.
const REQUEST_ID = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * HTTPS everywhere except loopback development hosts. The base URL is process
 * configuration, never a per-call (model-supplied) value.
 */
export function requireTrustedOrigin(baseUrl: string): string {
  let url: URL;
  try {
    url = new URL(baseUrl);
  } catch {
    throw new Error("baseUrl must be an absolute URL");
  }
  // URL keeps IPv6 hostnames bracketed ("[::1]"); compare the bare address.
  const host = url.hostname.replace(/^\[|\]$/g, "");
  if (url.protocol === "https:" || (url.protocol === "http:" && LOOPBACK.has(host))) {
    return baseUrl.replace(/\/+$/, "");
  }
  throw new Error("baseUrl must be https:// (plain http is allowed only for loopback)");
}

function errName(e: unknown): string {
  return e instanceof Error ? e.name : String(e);
}

/** User cancellation propagates as-is; only genuine network failures become TransportError. */
function rethrowIfAborted(e: unknown, signal?: AbortSignal): void {
  if (signal?.aborted) throw e;
}

export async function raiseFor(
  response: Response,
  options: { create?: boolean } = {},
): Promise<void> {
  if (response.status >= 300 && response.status < 400) {
    // Never carry the Authorization header across a redirect; a credentialed
    // request that gets redirected is treated as a transport failure.
    throw new TransportError("unexpected redirect");
  }
  if (response.ok) return;
  let detail: string | undefined;
  try {
    detail = ((await response.json()) as { detail?: string })?.detail;
  } catch {
    detail = undefined; // a non-JSON error body has no detail to extract
  }
  throw errorForStatus(response.status, detail, options);
}

export interface AuthorizationClientOptions {
  timeoutSeconds?: number;
  fetch?: FetchLike;
}

export interface RequestAuthorizationOptions {
  decisionWindowSeconds?: number;
  intentExpiresAt?: string;
  idempotencyKey?: string;
  signal?: AbortSignal;
}

/**
 * Agent-side client: create an authorization request and poll for its decision.
 *
 *     const client = new AuthorizationClient(baseUrl, agentApiKey);
 *     const pending = await client.requestAuthorization({ ... });
 *     const result = await client.waitForAuthorization(pending.requestId, 900);
 */
export class AuthorizationClient {
  private readonly baseUrl: string;
  // A true private field: util.inspect and JSON.stringify never expose the key.
  readonly #headers: Record<string, string>;
  private readonly timeoutSeconds: number;
  private readonly fetchFn: FetchLike;

  constructor(baseUrl: string, agentApiKey: string, options: AuthorizationClientOptions = {}) {
    this.baseUrl = requireTrustedOrigin(baseUrl);
    this.#headers = { Authorization: `Bearer ${agentApiKey}` };
    this.timeoutSeconds = options.timeoutSeconds ?? 10;
    this.fetchFn = options.fetch ?? globalThis.fetch;
  }

  private signalFor(timeoutSeconds: number, signal?: AbortSignal): AbortSignal {
    const timeout = AbortSignal.timeout(timeoutSeconds * 1000);
    return signal ? AbortSignal.any([signal, timeout]) : timeout;
  }

  /**
   * Create a request. One idempotency key is generated per call and reused for
   * the internal retry, so an ambiguous network failure can never prompt the user
   * twice — the retry replays instead.
   *
   * Supplying `idempotencyKey` yourself is for resuming one specific earlier create.
   * Derive it from randomness, never from the terms: a content-derived key makes a
   * second genuine purchase of the same item replay the first one instead of asking
   * the user, and the reservation is permanent.
   */
  async requestAuthorization(
    terms: Terms,
    options: RequestAuthorizationOptions = {},
  ): Promise<PendingAuthorization> {
    const { decisionWindowSeconds = 900, intentExpiresAt, signal } = options;
    const idempotencyKey = options.idempotencyKey ?? crypto.randomUUID();
    const body: Record<string, unknown> = {
      terms,
      decision_window_seconds: decisionWindowSeconds,
    };
    if (intentExpiresAt != null) body.intent_expires_at = intentExpiresAt;

    const response = await this.postWithOneRetry(
      "/api/agent/authorizations", JSON.stringify(body), idempotencyKey, signal);
    await raiseFor(response, { create: true });
    const data = (await response.json()) as any;
    return {
      requestId: data.request_id,
      status: data.status,
      decideBy: data.decide_by,
      idempotencyKey,
      replayed: response.headers.get("Idempotency-Replayed") === "true",
    };
  }

  private async postWithOneRetry(
    path: string,
    payload: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<Response> {
    const attempt = () =>
      this.fetchFn(this.baseUrl + path, {
        method: "POST",
        headers: {
          ...this.#headers,
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
        body: payload,
        redirect: "manual",
        signal: this.signalFor(this.timeoutSeconds, signal),
      });
    // Safe to retry ONLY because the idempotency key rides along unchanged.
    try {
      return await attempt();
    } catch (e) {
      rethrowIfAborted(e, signal);
      try {
        return await attempt();
      } catch (e2) {
        rethrowIfAborted(e2, signal);
        throw new TransportError(errName(e2));
      }
    }
  }

  /** One poll, long-polling server-side for up to `waitSeconds` (0-25). */
  async getAuthorization(
    requestId: string,
    waitSeconds = 0,
    options: { signal?: AbortSignal } = {},
  ): Promise<AuthorizationResult> {
    // The id may be model-supplied (an MCP tool argument); never let it splice the path.
    if (!REQUEST_ID.test(requestId)) throw new InvalidRequestError("malformed request id");
    const query = waitSeconds ? `?wait=${waitSeconds}` : "";
    let response: Response;
    try {
      response = await this.fetchFn(
        `${this.baseUrl}/api/agent/authorizations/${encodeURIComponent(requestId)}${query}`, {
          headers: { ...this.#headers },
          redirect: "manual",
          // The server holds the connection for the whole long-poll.
          signal: this.signalFor(this.timeoutSeconds + waitSeconds, options.signal),
        });
    } catch (e) {
      rethrowIfAborted(e, options.signal);
      throw new TransportError(errName(e));
    }
    await raiseFor(response);
    const data = (await response.json()) as any;
    return {
      requestId: data.request_id,
      status: data.status,
      artifact: data.artifact ?? undefined,
      consentNotAfter: data.consent_not_after ?? undefined,
      decidedAt: data.decided_at ?? undefined,
    };
  }

  /**
   * Repeat bounded long-polls until a terminal state.
   *
   * Rejection and expiry come back as values — they are answers, not failures.
   * Running out of local time throws a "TimeoutError" DOMException, and abort
   * propagates; neither touches the server-side request, which the user can
   * still decide.
   */
  async waitForAuthorization(
    requestId: string,
    overallTimeoutSeconds: number,
    options: { longPollSeconds?: number; signal?: AbortSignal } = {},
  ): Promise<AuthorizationResult> {
    const { longPollSeconds = 25, signal } = options;
    const deadline = performance.now() + overallTimeoutSeconds * 1000;
    for (;;) {
      signal?.throwIfAborted();
      const remainingMs = deadline - performance.now();
      if (remainingMs <= 0) {
        throw new DOMException(`no decision within ${overallTimeoutSeconds}s`, "TimeoutError");
      }
      const wait = Math.max(0, Math.min(longPollSeconds, Math.floor(remainingMs / 1000)));
      const started = performance.now();
      let result: AuthorizationResult;
      try {
        result = await this.getAuthorization(requestId, wait, { signal });
      } catch (e) {
        if (e instanceof TransportError) {
          // A dropped long-poll is routine; back off briefly and ask again.
          await sleep(Math.min(1000, Math.max(0, deadline - performance.now())), signal);
          continue;
        }
        throw e;
      }
      if (TERMINAL.has(result.status)) return result;
      // An early "pending" (or a sub-second remaining window, where wait floors
      // to 0) would otherwise spin the loop with no pause.
      const elapsed = performance.now() - started;
      if (elapsed < 1000) {
        await sleep(Math.max(0, Math.min(1000 - elapsed, deadline - performance.now())), signal);
      }
    }
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted();
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal!.reason);
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}
