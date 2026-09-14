# yanez-agent-authorization (Python)

Async client for requesting verifiable human approval through Yanez, and a verifier
for the signed receipts. Import package: `yanez_authz`.

A receipt carries two signatures — Yanez's, and the approver's own over the decision
they made — and `verify` checks both.

```sh
pip install --pre yanez-agent-authorization   # pre-release; from a checkout: pip install -e packages/python
```

```python
from yanez_authz import AuthorizationClient, ReceiptVerifier

async with AuthorizationClient(base_url, agent_api_key) as client:
    pending = await client.request_authorization(terms={...})
    result = await client.wait_for_authorization(pending.request_id, 900)

receipt = ReceiptVerifier(base_url, expected_issuer).authorize_action(
    result.artifact, expected_terms, max_age_seconds=900,
    consume=True, consumer_token=job.token,  # yours, durable, reused on every retry
    expected_sub=account_yid,                # the YID your records tie to the account
    min_assurance_tier="high")               # your floor for the value at risk

receipt.assurance_tier   # the tier the approver's scan reached, from the bytes they signed
receipt.user_proof       # the full verified proof and decoded envelope
```

Already have a JWT library? Verify the receipt with it, then call the standalone proof
helper for the half a JWT library cannot do:

```python
from yanez_authz import verify_user_proof
proof = verify_user_proof(claims, expected_issuer=expected_issuer)
```

`terms` has a required shape that the server enforces with a `422`; every field is
documented on the [Terms page](https://yanez-compliance.github.io/yanez-agent-authorization/terms/).

`wait_for_authorization` raises the builtin `TimeoutError` when the local deadline
passes; rejection and expiry are returned as values. `expected_issuer` is the issuer
string your Yanez operator publishes for the deployment.

`consume=True` requires a `consumer_token`. On `ReservationHeldError` your own earlier
attempt already won and lost its response: reconcile downstream with your original
idempotency key rather than requesting a new approval.

Verifying the approver's signature, field by field:
https://yanez-compliance.github.io/yanez-agent-authorization/user-signed-approvals/

Docs and the full integration model: https://github.com/yanez-compliance/yanez-agent-authorization
