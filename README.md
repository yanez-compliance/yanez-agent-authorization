# yanez-agent-authorization

Builder integrations for Yanez agent authorization: let an AI agent request **verifiable
human approval** for a sensitive action, and let the action's executor verify the signed
receipt before anything runs.

The HTTP/OpenAPI contract is the source of truth; everything else here is an adapter:

| Piece | Where | For |
|---|---|---|
| OpenAPI contract | `openapi/agent-authorization.openapi.yaml` | Raw HTTP clients in any language |
| Python SDK | `packages/python/` (`yanez-agent-authorization`, import `yanez_authz`) | Custom agents and relying parties |
| TypeScript SDK | `packages/typescript/` (`@yanez/agent-authorization`) | Node agents and relying parties |
| CLI | `cli/` (`yanez-authz`) | Shell-capable agents; skill+CLI needs no MCP |
| MCP server | `integrations/mcp/` (`yanez-authz-mcp`, stdio) | MCP-capable hosts |
| Skill | `skills/yanez-authorize/` | Teaches an agent when and how to ask |
| Conformance fixtures | `conformance/fixtures/` | Both SDKs must reach the same verdicts |
| Examples | `examples/` | One small runnable example per integration path |

**Documentation: <https://yanez-compliance.github.io/yanez-agent-authorization/>**

Start with [Choosing an integration path](docs/integration-options.md) to pick a path,
then the matching quickstart.

## Install

Pre-release: none of these packages is on PyPI or npm yet. Until they are, install
from a checkout with the commands under Development.

| Path | Install |
|---|---|
| Python SDK | `pip install yanez-agent-authorization` |
| CLI | `pip install yanez-authz-cli` (installs `yanez-authz`) |
| MCP server | `pip install yanez-authz-mcp` (installs `yanez-authz-mcp`) |
| TypeScript SDK | `npm install @yanez/agent-authorization` |

## The one rule that matters

A receipt authorizes nothing by itself. The **action executor** must verify the
signature, compare the signed terms with the proposed action by deep JSON equality,
apply its own freshness policy, and consume single-use receipts.
[Action enforcement](docs/action-enforcement.md) is the contract for that boundary.

## Status

Pre-release staging. The OpenAPI artifact is exported from the Yanez server
repository (`openapi/SOURCE.json` records the source digest); rerun
`python openapi/export_subset.py <path-to-server-openapi.yaml> --server-release <tag>`
(needs PyYAML) against a tagged server release before publishing. An OpenAI plugin package (`plugins/openai/`) is deferred
until the hosted-MCP authentication design exists.

## Development

- Python: `pip install -e "packages/python[test]" -e cli -e integrations/mcp`, then
  `pytest packages/python/tests cli/tests integrations/mcp/tests`
- TypeScript: `cd packages/typescript && npm install && npm test`
- Fixtures: `python conformance/generate_fixtures.py` (deterministic; commit the result)

No production hosts, keys, biometric material, or agent credentials belong in this
repository — test fixtures use fixed, obviously fake seeds.
