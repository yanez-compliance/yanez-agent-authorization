"""Agent side and relying-party side in one file.

    YANEZ_BASE_URL=... YANEZ_ISSUER=... YANEZ_EXPECTED_YID=... YANEZ_AGENT_API_KEY=yak_... \
        python quickstart.py

YANEZ_ISSUER is the issuer string your Yanez operator publishes for the deployment.
YANEZ_EXPECTED_YID is the approver's YID (shown in the YID app); a real relying party
takes it from its own account records.
"""
import asyncio
import os
import uuid

from yanez_authz import (
    AuthorizationClient,
    AlreadyConsumedError,
    ReceiptVerifier,
    ReservationHeldError,
    UserSignatureError,
)

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

    # Action executor. A real one is a separate service: it rebuilds the expected terms
    # from its own order record and never trusts the agent's copy.
    #
    # Both of these are written down BEFORE consuming, because both exist to survive a
    # crash between consuming and acting. A token minted after a lost response
    # identifies nothing.
    consumer_token = str(uuid.uuid4())     # persist this beside the order
    idempotency_key = f"order-{consumer_token}"

    verifier = ReceiptVerifier(base_url, expected_issuer=os.environ["YANEZ_ISSUER"])
    try:
        receipt = verifier.authorize_action(
            result.artifact, TERMS,
            max_age_seconds=900,
            consume=True,
            consumer_token=consumer_token,
            expected_sub=os.environ["YANEZ_EXPECTED_YID"],
            min_assurance_tier="medium",   # your floor for the value at risk
        )
    except UserSignatureError as e:
        # The Yanez signature may be fine. The approver did not sign this decision.
        print(f"refused, no valid approver signature: {e}")
        return
    except AlreadyConsumedError:
        print("another consumer already spent this receipt; not acting")
        return
    except ReservationHeldError:
        # Recovery, not failure: an earlier attempt of ours won and lost its response.
        print(f"already held; reconcile downstream with {idempotency_key}")
        return

    # Only reachable when the server confirmed the consumption.
    print(f"authorized: yid={receipt.sub} jti={receipt.jti} "
          f"tier={receipt.assurance_tier} signed_at={receipt.signed_at}")
    print(f"executing the purchase now, idempotency_key={idempotency_key}")


if __name__ == "__main__":
    asyncio.run(main())
