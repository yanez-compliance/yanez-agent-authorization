"""MCP server behavior through the official SDK's in-memory session: tool discovery,
structured results for every status, sanitized errors, and startup config validation.
The fake client keeps every test offline; network behavior belongs to the SDK suite."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from yanez_authz import AuthenticationError
from yanez_authz.models import AuthorizationResult, PendingAuthorization
from yanez_authz_mcp.server import build_server
from yanez_authz_mcp.settings import Settings, load_settings

SETTINGS = Settings(base_url="https://yanez.test", agent_api_key="yak_x_secret",
                    http_timeout_seconds=10)
SECRET = SETTINGS.agent_api_key


class FakeClient:
    def __init__(self) -> None:
        self.results: list[AuthorizationResult] = []
        self.created: list[dict[str, Any]] = []

    async def request_authorization(self, terms, **kw):
        self.created.append(terms)
        return PendingAuthorization("azr_1", "pending", "2026-01-01T00:15:00Z",
                                    "idem-1", False)

    async def get_authorization(self, request_id, wait_seconds=0):
        return self.results.pop(0)


def _call(server, tool: str, args: dict) -> Any:
    async def main():
        async with create_connected_server_and_client_session(
                server._mcp_server) as session:
            return await session.call_tool(tool, args)

    return asyncio.run(main())


def test_exactly_the_two_documented_tools_are_exposed():
    server = build_server(SETTINGS, client=FakeClient())

    async def main():
        async with create_connected_server_and_client_session(
                server._mcp_server) as session:
            return await session.list_tools()

    tools = sorted(t.name for t in asyncio.run(main()).tools)
    assert tools == ["yanez_get_authorization", "yanez_request_authorization"]
    # No introspection/consume tool: consumption belongs to the action executor.


def test_request_returns_the_pending_result(capfd):
    fake = FakeClient()
    server = build_server(SETTINGS, client=fake)
    result = _call(server, "yanez_request_authorization",
                   {"terms": {"action": "purchase", "summary": "Buy shoes"}})
    assert not result.isError
    data = result.structuredContent
    assert data["request_id"] == "azr_1" and data["status"] == "pending"
    assert fake.created == [{"action": "purchase", "summary": "Buy shoes"}]
    # Nothing but protocol traffic on stdout; logs go to stderr.
    out, _err = capfd.readouterr()
    assert out == ""


@pytest.mark.parametrize("status,artifact", [
    ("pending", None), ("approved", "eyJ.x.y"), ("rejected", None), ("expired", None),
])
def test_every_status_is_a_structured_result_not_an_error(status, artifact):
    fake = FakeClient()
    fake.results = [AuthorizationResult("azr_1", status, artifact=artifact)]
    server = build_server(SETTINGS, client=fake)
    result = _call(server, "yanez_get_authorization", {"request_id": "azr_1"})
    assert not result.isError
    assert result.structuredContent["status"] == status
    assert result.structuredContent["artifact"] == artifact


def test_wait_seconds_is_clamped_to_the_contract():
    server = build_server(SETTINGS, client=FakeClient())
    result = _call(server, "yanez_get_authorization",
                   {"request_id": "azr_1", "wait_seconds": 26})
    assert result.isError


def test_tool_errors_are_sanitized_and_never_carry_the_key():
    class Failing(FakeClient):
        async def request_authorization(self, terms, **kw):
            raise AuthenticationError("Unauthorized")

    server = build_server(SETTINGS, client=Failing())
    result = _call(server, "yanez_request_authorization",
                   {"terms": {"action": "x", "summary": "y"}})
    assert result.isError
    text = " ".join(c.text for c in result.content if hasattr(c, "text"))
    assert "AuthenticationError" in text and SECRET not in text


def test_missing_configuration_fails_naming_the_variable_not_the_value(monkeypatch):
    monkeypatch.delenv("YANEZ_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("YANEZ_BASE_URL", "https://yanez.test")
    with pytest.raises(SystemExit) as e:
        load_settings()
    assert "YANEZ_AGENT_API_KEY" in str(e.value)
    assert "yak_" not in str(e.value)


def test_settings_repr_never_shows_the_key():
    assert SECRET not in repr(SETTINGS) and SECRET not in str(SETTINGS)


def test_intent_expires_at_is_passed_through_to_the_sdk():
    class Recording(FakeClient):
        async def request_authorization(self, terms, **kw):
            self.created.append(kw)
            return await super().request_authorization(terms)

    client = Recording()
    _call(build_server(SETTINGS, client=client), "yanez_request_authorization",
          {"terms": {"action": "purchase", "summary": "x"},
           "intent_expires_at": "2026-01-01T00:10:00Z"})
    assert client.created[0]["intent_expires_at"] == "2026-01-01T00:10:00Z"
