# yanez-authz-mcp

A local stdio MCP server that holds one Yanez agent credential and exposes two tools,
`yanez_request_authorization` and `yanez_get_authorization`. There is no consume
tool: consuming a receipt belongs to the action executor, not the planning agent.

```sh
pip install yanez-authz-mcp          # pre-release: not on PyPI yet; pip install -e integrations/mcp
YANEZ_BASE_URL=https://your-yanez-host YANEZ_AGENT_API_KEY=yak_... yanez-authz-mcp
```

The key is read from `YANEZ_AGENT_API_KEY` at startup and never appears in tool
schemas, tool results, or stdout. `YANEZ_HTTP_TIMEOUT_SECONDS` (default 10) bounds
each HTTP call. Host configuration and the operator check: `examples/mcp/README.md`
in the repository.
