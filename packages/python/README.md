# yanez-agent-authorization (Python)

Async client for requesting verifiable human approval through Yanez, and a verifier
for the signed receipts. Import package: `yanez_authz`.

```sh
pip install yanez-agent-authorization   # pre-release: not on PyPI yet; pip install -e packages/python
```

```python
from yanez_authz import AuthorizationClient, ReceiptVerifier

async with AuthorizationClient(base_url, agent_api_key) as client:
    pending = await client.request_authorization(terms={...})
    result = await client.wait_for_authorization(pending.request_id, 900)

receipt = ReceiptVerifier(base_url, expected_issuer).authorize_action(
    result.artifact, expected_terms, max_age_seconds=900, consume=True,
    expected_sub=account_yid)   # the YID your records tie to the account
```

`wait_for_authorization` raises the builtin `TimeoutError` when the local deadline
passes; rejection and expiry are returned as values. `expected_issuer` is the issuer
string your Yanez operator publishes for the deployment.

Docs and the full integration model: https://github.com/yanez-compliance/yanez-agent-authorization
