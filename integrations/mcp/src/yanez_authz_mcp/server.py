"""The Yanez authorization MCP server: two tools over stdio, one configured agent key.

All logs go to stderr; stdout carries only the MCP protocol stream. The server never
exposes introspection with consume=true — consumption belongs to the trusted action
executor, and letting the planning agent spend a receipt before handing it over would
only create denial-of-service and retry failures.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from yanez_authz import AuthorizationClient, YanezAuthzError
from yanez_authz_mcp.settings import Settings, load_settings

logger = logging.getLogger("yanez_authz_mcp")

INSTRUCTIONS = """\
Yanez turns "the user approved" into portable, signed proof. Rules:

- Call yanez_request_authorization only after the proposed action and ALL material
  terms are known, and after showing those terms to the user in conversation.
- Poll with yanez_get_authorization. Do not file replacement requests while one is
  pending. Stop on rejection or expiry.
- The returned artifact is sensitive bearer proof: pass it to the protected action
  tool. An MCP status of "approved" is NOT authorization by itself — only the
  verified artifact is.
- Yanez signed a receipt asserting that a fresh biometric scan matching this YID
  approved these terms. The human did not cryptographically sign anything.
"""


def build_server(settings: Optional[Settings] = None,
                 client: Optional[AuthorizationClient] = None) -> FastMCP:
    """`client` is injectable for tests; production builds one from the environment."""
    cfg = settings or load_settings()
    mcp = FastMCP("yanez-authz", instructions=INSTRUCTIONS)
    state: dict[str, AuthorizationClient] = {}

    async def _client() -> AuthorizationClient:
        if client is not None:
            return client
        if "client" not in state:
            state["client"] = AuthorizationClient(
                cfg.base_url, cfg.agent_api_key,
                timeout_seconds=cfg.http_timeout_seconds)
        return state["client"]

    @mcp.tool()
    async def yanez_request_authorization(
        terms: dict[str, Any],
        decision_window_seconds: int = 900,
        intent_expires_at: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ask the user to approve the given terms in their YID app. Asks only — it
        never executes the action. State-changing and non-destructive: each call rings
        the user's phone once, so do not call it speculatively or in a loop. One
        idempotency key is created before the first HTTP attempt and reused for every
        internal retry."""
        try:
            pending = await (await _client()).request_authorization(
                terms, decision_window_seconds=decision_window_seconds,
                intent_expires_at=intent_expires_at)
        except YanezAuthzError as e:
            raise RuntimeError(f"{type(e).__name__}: {e}") from None
        logger.info("created request_id=%s", pending.request_id)
        return {"request_id": pending.request_id, "status": pending.status,
                "decide_by": pending.decide_by}

    @mcp.tool()
    async def yanez_get_authorization(
        request_id: str,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        """One poll for the user's decision, long-polling up to wait_seconds (0-25).
        pending, rejected, and expired are normal structured results (artifact null);
        only approved carries the signed artifact — sensitive bearer proof."""
        if not 0 <= wait_seconds <= 25:
            raise ValueError("wait_seconds must be 0-25")
        try:
            result = await (await _client()).get_authorization(
                request_id, wait_seconds=wait_seconds)
        except YanezAuthzError as e:
            raise RuntimeError(f"{type(e).__name__}: {e}") from None
        logger.info("poll request_id=%s status=%s", request_id, result.status)
        return {"request_id": result.request_id, "status": result.status,
                "artifact": result.artifact,
                "decided_at": result.decided_at,
                "consent_not_after": result.consent_not_after}

    return mcp
