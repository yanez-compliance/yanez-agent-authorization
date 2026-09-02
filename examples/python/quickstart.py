"""Agent side and relying-party side in one file.

    YANEZ_BASE_URL=... YANEZ_ISSUER=... YANEZ_EXPECTED_YID=... YANEZ_AGENT_API_KEY=yak_... \
        python quickstart.py

YANEZ_ISSUER is the issuer string your Yanez operator publishes for the deployment.
YANEZ_EXPECTED_YID is the approver's YID (shown in the YID app); a real relying party
takes it from its own account records.
"""
import asyncio
import os

from yanez_authz import AuthorizationClient, ReceiptVerifier

TERMS = {
    "action": "purchase",
    "summary": "Buy running shoes for $180 at Example Store",
    "merchant": "Example Store",
    "amount": "180.00",
    "currency": "USD",
}


async def main() -> None:
    base_url = os.environ["YANEZ_BASE_URL"]

    # Agent: ask, then wait for the human.
    async with AuthorizationClient(base_url, os.environ["YANEZ_AGENT_API_KEY"]) as client:
        pending = await client.request_authorization(terms=TERMS)
        print(f"created {pending.request_id}; approve it in the YID app")
        result = await client.wait_for_authorization(pending.request_id,
                                                     overall_timeout_seconds=900)
    print(f"decision: {result.status}")
    if result.status != "approved":
        return

    # Action executor: verify + consume, bound to the YID your records tie to this
    # account, then (and only then) act.
    verifier = ReceiptVerifier(base_url, expected_issuer=os.environ["YANEZ_ISSUER"])
    receipt = verifier.authorize_action(result.artifact, TERMS,
                                        max_age_seconds=900, consume=True,
                                        expected_sub=os.environ["YANEZ_EXPECTED_YID"])
    print(f"authorized: yid={receipt.sub} jti={receipt.jti} — executing the purchase now")


if __name__ == "__main__":
    asyncio.run(main())
