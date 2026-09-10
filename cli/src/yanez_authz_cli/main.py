"""yanez-authz — the supported executable adapter for shell-capable agents.

A thin wrapper: every HTTP, polling, verification, error, and redaction behavior
belongs to the yanez_authz SDK, not here.

Conventions:
- The agent key comes ONLY from YANEZ_AGENT_API_KEY. There is no key flag, so the
  secret never appears in process listings or shell history.
- Terms and artifacts come from files or stdin ("-"), never command-line JSON.
- Structured results go to stdout; logs and errors go to stderr.
- Exit codes: 0 = the command produced an answer; 1 = refusal or failure; 2 = usage.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from yanez_authz import (
    AuthorizationClient,
    ConsentPolicyError,
    ReceiptVerifier,
    ReservationHeldError,
    UserSignatureError,
    YanezAuthzError,
)


def _read_json(path: str) -> Any:
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    return json.loads(text)


def _read_text(path: str) -> str:
    return (sys.stdin.read() if path == "-" else Path(path).read_text()).strip()


def _emit(result: Any, as_json: bool) -> None:
    data = dataclasses.asdict(result) if dataclasses.is_dataclass(result) else result
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        for key, value in data.items():
            print(f"{key:20} {value}")


def _base_url(args: argparse.Namespace) -> str:
    url = args.base_url or os.environ.get("YANEZ_BASE_URL")
    if not url:
        raise SystemExit("error: set YANEZ_BASE_URL or pass --base-url")
    return url


def _agent_key() -> str:
    key = os.environ.get("YANEZ_AGENT_API_KEY")
    if not key:
        raise SystemExit("error: YANEZ_AGENT_API_KEY is not set "
                         "(the key is never accepted as a flag)")
    return key


async def _cmd_request(args) -> Any:
    async with AuthorizationClient(_base_url(args), _agent_key()) as client:
        return await client.request_authorization(
            _read_json(args.terms_file),
            decision_window_seconds=args.decision_window,
            intent_expires_at=args.intent_expires_at,
        )


async def _cmd_get(args) -> Any:
    async with AuthorizationClient(_base_url(args), _agent_key()) as client:
        return await client.get_authorization(args.request_id, wait_seconds=args.wait)


async def _cmd_wait(args) -> Any:
    async with AuthorizationClient(_base_url(args), _agent_key()) as client:
        return await client.wait_for_authorization(args.request_id, args.timeout)


def _receipt_view(receipt) -> dict:
    """A flat, JSON-safe view of a verified receipt.

    `VerifiedReceipt` carries the signed message as raw bytes, which no JSON encoder
    will take, and the whole decoded envelope, which is too much for a terminal. Report
    what an operator reading this output needs: who approved, at what assurance, and
    which key to look up if they want to check it against the registry.
    """
    proof = receipt.user_proof
    return {
        "sub": receipt.sub,
        "jti": receipt.jti,
        "agent_key_id": receipt.agent_key_id,
        "decided_at": receipt.decided_at,
        "signed_at": receipt.signed_at,
        "match_overlap": receipt.match_overlap,
        "consent_not_after": receipt.consent_not_after,
        "assurance_tier": receipt.assurance_tier,
        "user_public_key": proof.public_key,
        "user_sig_alg": "BLS12-381-G2-basic",
        "user_signature_verified": True,
        "terms": receipt.terms,
    }


def _cmd_verify(args) -> Any:
    if args.consume and not (args.consumer_token or "").strip():
        # Usage, not refusal: the caller has not told us who is consuming, and a token
        # we invented here could not survive the lost response it exists for.
        raise SystemExit("error: --consume requires --consumer-token "
                         "(your own durable string, reused on every retry)")
    if args.consumer_token and not args.consume:
        raise SystemExit("error: --consumer-token is only meaningful with --consume")
    verifier = ReceiptVerifier(_base_url(args), args.issuer)
    receipt = verifier.authorize_action(
        _read_text(args.artifact_file),
        _read_json(args.expected_terms_file),
        args.max_age,
        consume=args.consume,
        consumer_token=args.consumer_token if args.consume else None,
        expected_sub=args.expected_sub,
        expected_agent_key_id=args.expected_agent_key_id,
        min_assurance_tier=args.min_assurance_tier,
    )
    return _receipt_view(receipt)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yanez-authz", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=None,
                        help="Yanez API origin (default: $YANEZ_BASE_URL)")
    parser.add_argument("--json", action="store_true", help="machine-readable stdout")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("request", help="ask the key's owner to approve terms")
    p.add_argument("--terms-file", required=True, help="JSON terms; '-' for stdin")
    p.add_argument("--decision-window", type=int, default=900, metavar="SECONDS")
    p.add_argument("--intent-expires-at", default=None, metavar="ISO8601")

    p = sub.add_parser("get", help="poll one request")
    p.add_argument("request_id")
    p.add_argument("--wait", type=int, default=0, choices=range(0, 26), metavar="0..25")

    p = sub.add_parser("wait", help="long-poll until the user decides")
    p.add_argument("request_id")
    p.add_argument("--timeout", type=int, required=True, metavar="SECONDS")

    p = sub.add_parser("verify",
                       help="verify both signatures (and optionally consume) a receipt")
    p.add_argument("--artifact-file", required=True, help="compact JWS; '-' for stdin")
    p.add_argument("--expected-terms-file", required=True)
    p.add_argument("--issuer", required=True)
    p.add_argument("--max-age", type=int, required=True, metavar="SECONDS")
    p.add_argument("--consume", action="store_true")
    p.add_argument("--consumer-token", default=None, metavar="TOKEN",
                   help="required with --consume: your own durable string identifying "
                        "this attempt, reused verbatim on every retry")
    p.add_argument("--min-assurance-tier", default=None,
                   choices=("low", "medium", "high"),
                   help="refuse an approval below this assurance tier")
    p.add_argument("--expected-sub", default=None, metavar="YID",
                   help="refuse unless this YID approved (bind the receipt to the account)")
    p.add_argument("--expected-agent-key-id", default=None, metavar="YAK_ID",
                   help="refuse unless this agent key requested the approval")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            result = _cmd_verify(args)
        else:
            runner = {"request": _cmd_request, "get": _cmd_get, "wait": _cmd_wait}
            result = asyncio.run(runner[args.command](args))
    except UserSignatureError as e:
        # The loudest failure this tool has. The Yanez signature may be perfectly good;
        # the person did not sign this.
        print(f"REFUSED, the approver did not sign this decision: {e}", file=sys.stderr)
        return 1
    except ReservationHeldError as e:
        # Not a failure. This caller already holds the reservation from an attempt whose
        # response was lost, and the downstream action may already have happened.
        print(f"reservation already held by this consumer: {e}", file=sys.stderr)
        print("reconcile downstream with your original idempotency key; "
              "do not request a new approval", file=sys.stderr)
        return 1
    except ConsentPolicyError as e:
        # Distinct wording: the receipt is genuine; only permission to act is refused.
        print(f"refused for action: {e} (the receipt itself remains valid evidence)",
              file=sys.stderr)
        return 1
    except (YanezAuthzError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _emit(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
