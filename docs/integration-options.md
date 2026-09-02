# Choosing an integration path

Four layers, from universal to most convenient. Every layer sits on the same HTTP
contract; pick the highest one your runtime supports.

| Your runtime | Use | Quickstart |
|---|---|---|
| Anything that speaks HTTP | The OpenAPI contract directly | `http-quickstart.md` |
| Python agent or relying party | `yanez-agent-authorization` (import `yanez_authz`) | `examples/python/` |
| Node agent or relying party | `@yanez/agent-authorization` | `examples/typescript/` |
| Shell-capable coding agent | `yanez-authz` CLI + the `yanez-authorize` skill | `examples/skill-cli/` |
| MCP-capable host | `yanez-authz-mcp` (stdio) + the skill | `examples/mcp/` |

Package names: PyPI `yanez-agent-authorization`, `yanez-authz-cli`, `yanez-authz-mcp`;
npm `@yanez/agent-authorization`. Pre-release: none is published yet, so install from a
checkout (`README.md`, Development).

MCP is **not required**. It is the preferred adapter when the host already supports it,
because it gives the model discoverable typed tools and keeps the credential in a
process the model never sees. A skill by itself is not a security boundary and cannot
make authenticated calls; pair it with the CLI or the MCP server.

Three parties, three responsibilities:

1. **The agent** creates an authorization request with exact terms and polls for the
   decision. Its `yak_` key can ask, not act.
2. **The user** approves or rejects in the YID app, gated on a fresh biometric scan.
3. **The action executor** (relying party) verifies the signed receipt against the
   proposed action and consumes it when single-use — `action-enforcement.md`.

Credential rules, everywhere: the `yak_` key comes from configuration
(`YANEZ_AGENT_API_KEY` or a secret manager), never from model prompts, tool arguments,
command-line flags, or logs. Never hand it to a sub-agent.
