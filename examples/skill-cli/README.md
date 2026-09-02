# Skill + CLI integration (no MCP)

For hosts that can run approved local commands. Install the CLI, expose the skill.

```sh
pip install yanez-authz-cli   # pre-release: not on PyPI yet; pip install -e packages/python -e cli
export YANEZ_BASE_URL=https://your-yanez-host
export YANEZ_AGENT_API_KEY=yak_...                      # env only; there is no key flag
```

Copy `skills/yanez-authorize/` into the host's skill directory. The agent writes the
terms to a file (never onto a command line, where they would land in shell history and
process listings); the skill then drives:

```sh
yanez-authz --json request --terms-file terms.json
yanez-authz --json wait azr_... --timeout 900
```

The relying party verifies and consumes independently:

```sh
yanez-authz --json verify --artifact-file artifact.jws \
  --expected-terms-file terms.json --issuer "$YANEZ_ISSUER" \
  --max-age 900 --consume --expected-sub "$ACCOUNT_YID"
```

`--issuer` is the issuer string your Yanez operator publishes for the deployment.
`--expected-sub` is the YID your records tie to the account being acted on; without it
a receipt proves only that some user approved these terms.

`--json` output, one object per command:

| Command | Fields |
|---|---|
| `request` | `request_id`, `status`, `decide_by`, `idempotency_key`, `replayed` |
| `get`, `wait` | `request_id`, `status`, `artifact`, `consent_not_after`, `decided_at` |
| `verify` | `sub`, `jti`, `agent_key_id`, `decided_at`, `match_overlap`, `terms`, `consent_not_after` |

Terms and artifacts travel through files or stdin so nothing sensitive lands in
process listings or shell history. Logs go to stderr; structured results to stdout.
