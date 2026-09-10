"""CLI behavior: JSON output, stdin/file handling, env-only credentials, exit codes,
and delegation to the SDK (faked here — network behavior is the SDK suite's job)."""
from __future__ import annotations

import json

import pytest

from yanez_authz.models import AuthorizationResult, PendingAuthorization, VerifiedReceipt
from yanez_authz.proof import UserProof

TOKEN = "executor-attempt-1"


def _receipt(terms, sub="a" * 32, jti="azr_1", key_id="yak_x", decided_at=1767225600,
             overlap=213):
    """A verified receipt as the SDK now returns one: both signatures already checked."""
    proof = UserProof(
        assurance_tier="high", public_key="0x" + "ab" * 48, signature="0x" + "cd" * 96,
        signed_message=b"{}", envelope={"terms": terms}, signed_at=decided_at - 4,
        yid=sub, decision="approve", issuer="https://yanez.test", version=1,
    )
    return VerifiedReceipt(sub, jti, key_id, decided_at, overlap, terms,
                           assurance_tier="high", user_proof=proof)
import yanez_authz_cli.main as cli

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


class FakeClient:
    def __init__(self, base_url, agent_api_key, **kw):
        self.base_url = base_url
        self.key = agent_api_key

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def request_authorization(self, terms, **kw):
        assert terms == TERMS
        return PendingAuthorization("azr_1", "pending", "2026-01-01T00:15:00Z",
                                    "idem-1", False)

    async def get_authorization(self, request_id, wait_seconds=0):
        return AuthorizationResult(request_id, "approved", artifact="eyJ.x.y",
                                   decided_at="2026-01-01T00:00:00Z")

    async def wait_for_authorization(self, request_id, timeout, **kw):
        return AuthorizationResult(request_id, "rejected")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("YANEZ_BASE_URL", "https://yanez.test")
    monkeypatch.setenv("YANEZ_AGENT_API_KEY", "yak_abc_secret")
    monkeypatch.setattr(cli, "AuthorizationClient", FakeClient)


def _terms_file(tmp_path):
    path = tmp_path / "terms.json"
    path.write_text(json.dumps(TERMS))
    return str(path)


def test_request_emits_json_result(tmp_path, capsys):
    rc = cli.main(["--json", "request", "--terms-file", _terms_file(tmp_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["request_id"] == "azr_1" and out["status"] == "pending"


def test_terms_come_from_stdin_with_dash(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(TERMS)))
    assert cli.main(["--json", "request", "--terms-file", "-"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pending"


def test_wait_reports_rejection_as_an_answer_not_a_failure(capsys):
    rc = cli.main(["--json", "wait", "azr_1", "--timeout", "60"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


def test_missing_agent_key_fails_without_a_flag_fallback(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("YANEZ_AGENT_API_KEY")
    with pytest.raises(SystemExit):
        cli.main(["request", "--terms-file", _terms_file(tmp_path)])


def test_the_parser_has_no_credential_flag():
    """The key must never be acceptable as an argument — process listings leak."""
    for action in cli.build_parser()._actions:
        for opt in action.option_strings:
            assert "key" not in opt.lower()


def test_verify_delegates_to_authorize_action(monkeypatch, tmp_path, capsys):
    calls = {}

    class FakeVerifier:
        def __init__(self, base_url, issuer, **kw):
            calls["issuer"] = issuer

        def authorize_action(self, artifact, expected_terms, max_age, *, consume, **kw):
            calls["consume"] = consume
            return _receipt(TERMS)

    monkeypatch.setattr(cli, "ReceiptVerifier", FakeVerifier)
    artifact = tmp_path / "artifact.jws"
    artifact.write_text("eyJ.x.y\n")
    rc = cli.main(["--json", "verify", "--artifact-file", str(artifact),
                   "--expected-terms-file", _terms_file(tmp_path),
                   "--issuer", "https://yanez.test", "--max-age", "900",
                   "--consume", "--consumer-token", TOKEN])
    assert rc == 0
    assert calls == {"issuer": "https://yanez.test", "consume": True}
    out = json.loads(capsys.readouterr().out)
    assert out["jti"] == "azr_1"
    # The proof is reported, and the raw signed bytes are not: they are not JSON, and
    # an operator reading a terminal does not need them.
    assert out["assurance_tier"] == "high"
    assert out["user_signature_verified"] is True
    assert "signed_message" not in out


def test_sdk_errors_exit_one_and_go_to_stderr(monkeypatch, tmp_path, capsys):
    from yanez_authz import RateLimitError

    class Limited(FakeClient):
        async def request_authorization(self, terms, **kw):
            raise RateLimitError("rate limit exceeded")

    monkeypatch.setattr(cli, "AuthorizationClient", Limited)
    rc = cli.main(["request", "--terms-file", _terms_file(tmp_path)])
    captured = capsys.readouterr()
    assert rc == 1 and captured.out == ""
    assert "rate limit" in captured.err


def test_get_emits_the_poll_result(capsys):
    rc = cli.main(["--json", "get", "azr_1", "--wait", "25"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "approved" and out["artifact"] == "eyJ.x.y"


def test_usage_errors_exit_two():
    with pytest.raises(SystemExit) as e:
        cli.main(["request", "--terms-file", "t.json", "--json"])  # --json belongs first
    assert e.value.code == 2


def test_consent_refusal_and_local_timeout_exit_one(monkeypatch, tmp_path, capsys):
    class Refusing:
        def __init__(self, *a, **kw):
            pass

        def authorize_action(self, *a, **kw):
            raise cli.ConsentPolicyError("past the user's consent bound")

    monkeypatch.setattr(cli, "ReceiptVerifier", Refusing)
    artifact = tmp_path / "a.jws"
    artifact.write_text("eyJ.x.y")
    rc = cli.main(["verify", "--artifact-file", str(artifact),
                   "--expected-terms-file", _terms_file(tmp_path),
                   "--issuer", "https://yanez.test", "--max-age", "900"])
    assert rc == 1 and "refused for action" in capsys.readouterr().err

    async def timing_out(self, request_id, timeout, **kw):
        raise TimeoutError("no decision within 5s")

    monkeypatch.setattr(FakeClient, "wait_for_authorization", timing_out)
    rc = cli.main(["wait", "azr_1", "--timeout", "5"])
    assert rc == 1 and "error: no decision" in capsys.readouterr().err


def test_verify_forwards_the_identity_binding_flags(monkeypatch, tmp_path, capsys):
    seen = {}

    class Recording:
        def __init__(self, *a, **kw):
            pass

        def authorize_action(self, artifact, terms, max_age, **kw):
            seen.update(kw)
            return _receipt(terms, key_id="yak_1", decided_at=0, overlap=1)

    monkeypatch.setattr(cli, "ReceiptVerifier", Recording)
    artifact = tmp_path / "a.jws"
    artifact.write_text("eyJ.x.y")
    rc = cli.main(["--json", "verify", "--artifact-file", str(artifact),
                   "--expected-terms-file", _terms_file(tmp_path),
                   "--issuer", "https://yanez.test", "--max-age", "900",
                   "--consume", "--consumer-token", TOKEN,
                   "--expected-sub", "a" * 32, "--expected-agent-key-id", "yak_1",
                   "--min-assurance-tier", "high"])
    assert rc == 0
    assert seen == {"consume": True, "consumer_token": TOKEN, "expected_sub": "a" * 32,
                    "expected_agent_key_id": "yak_1", "min_assurance_tier": "high"}
    assert json.loads(capsys.readouterr().out)["sub"] == "a" * 32


def test_consume_without_a_token_is_a_usage_error(monkeypatch, tmp_path):
    """The token cannot be invented here: one minted at this moment could not survive
    the lost response it exists to recover from."""
    class Unused:
        def __init__(self, *a, **kw):
            raise AssertionError("must fail before any verification")

    monkeypatch.setattr(cli, "ReceiptVerifier", Unused)
    artifact = tmp_path / "a.jws"
    artifact.write_text("eyJ.x.y")
    base = ["--json", "verify", "--artifact-file", str(artifact),
            "--expected-terms-file", _terms_file(tmp_path),
            "--issuer", "https://yanez.test", "--max-age", "900"]

    with pytest.raises(SystemExit, match="consumer-token"):
        cli.main([*base, "--consume"])
    with pytest.raises(SystemExit, match="consumer-token"):
        cli.main([*base, "--consume", "--consumer-token", "  "])
    # Inspection is not consumption; a token without --consume is a mistake worth naming.
    with pytest.raises(SystemExit, match="only meaningful"):
        cli.main([*base, "--consumer-token", TOKEN])


def test_an_unsigned_decision_is_reported_as_its_own_failure(monkeypatch, tmp_path, capsys):
    """A verified Yanez signature over a decision nobody signed must not read like an
    ordinary terms mismatch."""
    from yanez_authz import UserSignatureError

    class Refusing:
        def __init__(self, *a, **kw):
            pass

        def authorize_action(self, *a, **kw):
            raise UserSignatureError("receipt carries no user proof")

    monkeypatch.setattr(cli, "ReceiptVerifier", Refusing)
    artifact = tmp_path / "a.jws"
    artifact.write_text("eyJ.x.y")
    rc = cli.main(["verify", "--artifact-file", str(artifact),
                   "--expected-terms-file", _terms_file(tmp_path),
                   "--issuer", "https://yanez.test", "--max-age", "900"])

    assert rc == 1
    assert "approver did not sign" in capsys.readouterr().err


def test_a_held_reservation_tells_the_operator_to_reconcile(monkeypatch, tmp_path, capsys):
    from yanez_authz import ReservationHeldError

    class Held:
        def __init__(self, *a, **kw):
            pass

        def authorize_action(self, *a, **kw):
            raise ReservationHeldError("this consumer already holds the reservation")

    monkeypatch.setattr(cli, "ReceiptVerifier", Held)
    artifact = tmp_path / "a.jws"
    artifact.write_text("eyJ.x.y")
    rc = cli.main(["verify", "--artifact-file", str(artifact),
                   "--expected-terms-file", _terms_file(tmp_path),
                   "--issuer", "https://yanez.test", "--max-age", "900",
                   "--consume", "--consumer-token", TOKEN])

    err = capsys.readouterr().err
    assert rc == 1
    assert "original idempotency key" in err
    assert "do not request a new approval" in err
