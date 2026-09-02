# Contributing

- The HTTP contract is owned by the Yanez server repository and imported here as
  `openapi/agent-authorization.openapi.yaml`. Contract changes start there, never as a
  hand-edit of the artifact.
- Behavior changes to one SDK must land in both, with a shared fixture in
  `conformance/fixtures/` proving they agree. Regenerate fixtures only through
  `conformance/generate_fixtures.py`.
- The CLI delegates everything to the Python SDK; the MCP server delegates to it too.
  Neither grows independent HTTP or verification logic; the one exception is the MCP
  `--check` diagnostic's single GET of the public-key route.
- Never weaken: credential handling (env-only, never flags or tool arguments),
  redirect refusal, the EdDSA pin, exact-terms comparison, or the two-tool MCP surface.
- Run the full local suite before a PR (commands in README.md).
