from __future__ import annotations

import asyncio
import re
import secrets
import time
from typing import Any, Optional
from urllib.parse import quote, urlsplit

import httpx

from yanez_authz.errors import InvalidRequestError, TransportError, error_for_status
from yanez_authz.models import TERMINAL, AuthorizationResult, PendingAuthorization

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# Server ids look like azr_<hex>; anything outside this set could only be an attempt
# to steer the keyed request at another path.
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def require_trusted_origin(base_url: str) -> str:
    """HTTPS everywhere except loopback development hosts. The base URL is process
    configuration, never a per-call (model-supplied) value."""
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return base_url.rstrip("/")
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return base_url.rstrip("/")
    raise ValueError("base_url must be https:// (plain http is allowed only for loopback)")


def _raise_for(response: httpx.Response, *, create: bool = False) -> None:
    if response.is_redirect:
        # Never carry the Authorization header across a redirect; a credentialed
        # request that gets redirected is treated as a transport failure.
        raise TransportError("unexpected redirect")
    if response.is_success:
        return
    try:
        detail = response.json().get("detail")
    except Exception:  # noqa: BLE001 — a non-JSON error body has no detail to extract
        detail = None
    raise error_for_status(response.status_code, detail, create=create)


class AuthorizationClient:
    """Agent-side client: create an authorization request and poll for its decision.

    Async and context-managed:

        async with AuthorizationClient(base_url, agent_api_key) as client:
            pending = await client.request_authorization(terms={...})
            result = await client.wait_for_authorization(pending.request_id, 900)
    """

    def __init__(self, base_url: str, agent_api_key: str, *,
                 timeout_seconds: float = 10.0,
                 transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        self._base_url = require_trusted_origin(base_url)
        self._timeout = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {agent_api_key}"},
            follow_redirects=False,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "AuthorizationClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request_authorization(
        self,
        terms: dict[str, Any],
        *,
        decision_window_seconds: int = 900,
        intent_expires_at: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> PendingAuthorization:
        """Create a request. One idempotency key is generated per call and reused for
        the internal retry, so an ambiguous network failure can never prompt the user
        twice — the retry replays instead.

        Supplying `idempotency_key` yourself is for resuming one specific earlier
        create. Derive it from randomness, never from the terms: a content-derived key
        makes a second genuine purchase of the same item replay the first one instead
        of asking the user, and the reservation is permanent.
        """
        if idempotency_key is None:
            idempotency_key = secrets.token_urlsafe(16)
        body: dict[str, Any] = {"terms": terms,
                                "decision_window_seconds": decision_window_seconds}
        if intent_expires_at is not None:
            body["intent_expires_at"] = intent_expires_at

        response = await self._post_with_one_retry(
            "/api/agent/authorizations", body, {"Idempotency-Key": idempotency_key})
        _raise_for(response, create=True)
        data = response.json()
        return PendingAuthorization(
            request_id=data["request_id"],
            status=data["status"],
            decide_by=data["decide_by"],
            idempotency_key=idempotency_key,
            replayed=response.headers.get("Idempotency-Replayed") == "true",
        )

    async def _post_with_one_retry(self, path: str, body: dict,
                                   headers: dict[str, str]) -> httpx.Response:
        # Safe to retry ONLY because the idempotency key rides along unchanged.
        try:
            return await self._client.post(path, json=body, headers=headers)
        except httpx.TransportError:
            try:
                return await self._client.post(path, json=body, headers=headers)
            except httpx.TransportError as e:
                raise TransportError(type(e).__name__) from None

    async def get_authorization(self, request_id: str,
                                wait_seconds: int = 0) -> AuthorizationResult:
        """One poll, long-polling server-side for up to `wait_seconds` (0-25)."""
        if not _REQUEST_ID.fullmatch(request_id):
            # The id may come from a model (MCP tool argument): validate before it
            # touches the URL, and encode so it can never rewrite the path.
            raise InvalidRequestError("malformed request id")
        params = {"wait": wait_seconds} if wait_seconds else None
        try:
            response = await self._client.get(
                f"/api/agent/authorizations/{quote(request_id, safe='')}", params=params,
                # The server holds the connection for the whole long-poll.
                timeout=self._timeout + wait_seconds,
            )
        except httpx.TransportError as e:
            raise TransportError(type(e).__name__) from None
        _raise_for(response)
        data = response.json()
        return AuthorizationResult(
            request_id=data["request_id"], status=data["status"],
            artifact=data.get("artifact"),
            consent_not_after=data.get("consent_not_after"),
            decided_at=data.get("decided_at"),
        )

    async def wait_for_authorization(
        self,
        request_id: str,
        overall_timeout_seconds: float,
        *,
        long_poll_seconds: int = 25,
    ) -> AuthorizationResult:
        """Repeat bounded long-polls until a terminal state.

        Rejection and expiry come back as values — they are answers, not failures.
        Running out of local time raises TimeoutError, and cancellation propagates;
        neither touches the server-side request, which the user can still decide.
        """
        deadline = time.monotonic() + overall_timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no decision within {overall_timeout_seconds}s")
            wait = max(0, min(long_poll_seconds, int(remaining)))
            started = time.monotonic()
            try:
                result = await self.get_authorization(request_id, wait_seconds=wait)
            except TransportError:
                # A dropped long-poll is routine; back off briefly and ask again.
                await asyncio.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                continue
            if result.status in TERMINAL:
                return result
            # A non-terminal reply that came back in under a second (wait 0 in the
            # final second, or a proxy answering early) must not become a tight loop.
            elapsed = time.monotonic() - started
            if elapsed < 1.0:
                await asyncio.sleep(min(1.0 - elapsed, max(0.0, deadline - time.monotonic())))
