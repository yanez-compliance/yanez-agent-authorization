# MCP integration

The stdio MCP server holds one agent credential and exposes exactly two tools:
`yanez_request_authorization` and `yanez_get_authorization`. There is deliberately no
consume tool — consumption belongs to the action executor.

Install: `pip install yanez-authz-mcp` (pre-release: from a checkout,
`pip install -e packages/python -e integrations/mcp`).

Host configuration (Claude Desktop / Claude Code style):

```json
{
  "mcpServers": {
    "yanez-authz": {
      "command": "yanez-authz-mcp",
      "env": {
        "YANEZ_BASE_URL": "https://your-yanez-host",
        "YANEZ_AGENT_API_KEY": "yak_..."
      }
    }
  }
}
```

`YANEZ_HTTP_TIMEOUT_SECONDS` (default 10) bounds each HTTP call.

Operator check. It confirms both variables are set and the public-key route answers;
it never uses the agent key and creates no request:

```sh
YANEZ_BASE_URL=... YANEZ_AGENT_API_KEY=... yanez-authz-mcp --check
```

The key never appears in tool schemas, tool results, or stdout; logs go to stderr.
Pair with `skills/yanez-authorize/` so the model knows when to ask.
