"""Agent-client behavior: auth header, idempotency, error typing, redirect refusal,
and terminal-state polling. Async client driven through asyncio.run so the suite needs
no async pytest plugin."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from yanez_authz import (
    AuthenticationError,
    AuthorizationClient,
    ConflictError,
    FeatureUnavailableError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    TermsTooLargeError,
    TransportError,
)

BASE = "https://yanez.test"
KEY = "yak_abc123abc123_s3cr3t-value"
TERMS = {
    "schema_version": 1,
    "action": "purchase",
    "approval_title": "Purchase running shoes",
    "summary": "Buy running shoes for $180.00 at Example Store",
    "merchant": "Example Store",
    "currency": "USD",
    "amount": {"minor_units": 18000, "currency": "USD"},
    "details": [
        {"label": "Merchant", "value": "Example Store", "emphasized": False},
        {"label": "Item", "value": "Running shoes, model X, size 10", "emphasized": False},
        {"label": "Amount", "value": "$180.00", "emphasized": True},
    ],
}


def _client(handler, **kw) -> AuthorizationClient:
    return AuthorizationClient(BASE, KEY, transport=httpx.MockTransport(handler), **kw)


def test_create_sends_bearer_and_generated_idempotency_key(http_fixtures):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["idem"] = request.headers.get("Idempotency-Key")
        return httpx.Response(201, json=http_fixtures["create_response"])

    async def main():
        async with _client(handler) as client:
            return await client.request_authorization(TERMS)

    pending = asyncio.run(main())
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["idem"] and pending.idempotency_key == seen["idem"]
    assert pending.status == "pending" and not pending.replayed


def test_transport_retry_reuses_the_same_idempotency_key(http_fixtures):
    attempts = []

    class FlakyTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            attempts.append(request.headers.get("Idempotency-Key"))
            if len(attempts) == 1:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(201, json=http_fixtures["create_response"],
                                  headers={"Idempotency-Replayed": "true"})

    async def main():
        async with AuthorizationClient(BASE, KEY, transport=FlakyTransport()) as client:
            return await client.request_authorization(TERMS, idempotency_key="retry-1")

    pending = asyncio.run(main())
    assert attempts == ["retry-1", "retry-1"]
    assert pending.replayed is True


def test_a_schema_422_names_the_field_paths_and_never_echoes_the_payload():
    # The request validator's array carries the submitted value under `input`; the
    # message reaches stderr and MCP tool results, so only the paths may survive.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [
            {"type": "string_type", "loc": ["body", "terms", "details", 2, "emphasized"],
             "msg": "Input should be a valid boolean", "input": {"patient": "Jane Doe"}},
            {"type": "less_than_equal", "loc": ["body", "decision_window_seconds"],
             "msg": "Input should be <= 3600", "input": 99999},
        ]})

    async def main():
        async with _client(handler) as client:
            await client.request_authorization(TERMS)

    with pytest.raises(InvalidRequestError) as e:
        asyncio.run(main())
    assert str(e.value) == "invalid request: terms.details[2].emphasized, decision_window_seconds"
    assert "Jane Doe" not in str(e.value) and "99999" not in str(e.value)


@pytest.mark.parametrize("status,exc,create", [
    (401, AuthenticationError, True),
    (404, FeatureUnavailableError, True),   # the whole router is absent on create
    (404, NotFoundError, False),            # unknown or cross-key id on get
    (400, InvalidRequestError, True),
    (409, ConflictError, True),
    (413, TermsTooLargeError, True),
    (422, InvalidRequestError, True),
    (429, RateLimitError, True),
])
def test_http_errors_are_typed(status, exc, create):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": "nope"})

    async def main():
        async with _client(handler) as client:
            if create:
                await client.request_authorization(TERMS)
            else:
                await client.get_authorization("azr_x")

    with pytest.raises(exc):
        asyncio.run(main())


def test_errors_never_carry_the_agent_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"})

    async def main():
        async with _client(handler) as client:
            await client.request_authorization(TERMS)

    with pytest.raises(AuthenticationError) as e:
        asyncio.run(main())
    assert KEY not in str(e.value) and KEY not in repr(e.value)


def test_redirects_are_transport_errors_not_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"Location": "https://evil.example/"})

    async def main():
        async with _client(handler) as client:
            await client.get_authorization("azr_x")

    with pytest.raises(TransportError):
        asyncio.run(main())


def test_https_is_required_off_loopback():
    with pytest.raises(ValueError):
        AuthorizationClient("http://yanez.example", KEY)


def test_wait_returns_every_terminal_state_as_a_value(http_fixtures):
    for terminal in ("poll_approved", "poll_rejected", "poll_expired"):
        responses = iter([http_fixtures["poll_pending"], http_fixtures[terminal]])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(responses))

        async def main():
            async with _client(handler) as client:
                return await client.wait_for_authorization("azr_x", 30,
                                                           long_poll_seconds=0)

        result = asyncio.run(main())
        assert result.status == http_fixtures[terminal]["status"]
        assert (result.artifact is not None) == (result.status == "approved")


def test_wait_times_out_locally_without_touching_the_request(http_fixtures):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=http_fixtures["poll_pending"])

    async def main():
        async with _client(handler) as client:
            await client.wait_for_authorization("azr_x", 0.2, long_poll_seconds=0)

    with pytest.raises(TimeoutError):
        asyncio.run(main())


def test_malformed_request_id_is_rejected_before_any_request():
    """A model-supplied id must never steer the keyed request to another path."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    async def main():
        async with _client(handler) as client:
            await client.get_authorization("../../admin/keys?x=1")

    with pytest.raises(InvalidRequestError):
        asyncio.run(main())
    assert calls == []


def test_long_poll_sends_the_wait_query(http_fixtures):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=http_fixtures["poll_approved"])

    async def main():
        async with _client(handler) as client:
            return await client.get_authorization("azr_x", wait_seconds=25)

    asyncio.run(main())
    assert seen["url"] == f"{BASE}/api/agent/authorizations/azr_x?wait=25"


def test_user_keys_returns_the_rows_for_key_is_registered(user_keys):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=user_keys)

    async def main():
        async with _client(handler) as client:
            return await client.user_keys()

    result = asyncio.run(main())
    assert seen == {"url": f"{BASE}/api/agent/user_keys", "auth": f"Bearer {KEY}"}
    assert result.yid == user_keys["yid"] and result.keys == user_keys["keys"]


def test_user_keys_404_means_the_route_is_not_deployed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    async def main():
        async with _client(handler) as client:
            await client.user_keys()

    with pytest.raises(FeatureUnavailableError):
        asyncio.run(main())


def test_wait_paces_polls_when_the_server_answers_early(http_fixtures):
    """Wait 0 in the final second, or a proxy answering early, must not spin."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=http_fixtures["poll_pending"])

    async def main():
        async with _client(handler) as client:
            await client.wait_for_authorization("azr_x", 0.3, long_poll_seconds=0)

    with pytest.raises(TimeoutError):
        asyncio.run(main())
    assert len(calls) <= 3
