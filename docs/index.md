---
title: Overview
description: Let an AI agent request verifiable human approval for a sensitive action, and verify the signed receipt before anything runs.
---

# Agent Authorization

Let an AI agent request **verifiable human approval** for a sensitive action, and let the
action's executor (the relying party) verify the signed receipt before anything runs.

The HTTP/OpenAPI contract is the source of truth. Every SDK, the CLI, the MCP server, and
the skill are adapters over that same contract — pick the highest layer your runtime
supports.

<div class="callout">
  <div class="callout-title">The one rule that matters</div>
  <p>A receipt authorizes nothing by itself. The <strong>action executor</strong> (the relying
  party, not the agent) must verify the signature, compare the signed terms against the proposed
  action by deep JSON equality, apply its own freshness policy, and consume single-use receipts.</p>
</div>

## Start here

<div class="cards">
  <a class="card" href="{{ '/integration-options/' | relative_url }}">
    <div class="card-title">Choosing an integration path</div>
    <div class="card-body">Four layers, from raw HTTP to MCP. Find the one that matches your runtime.</div>
  </a>
  <a class="card" href="{{ '/http-quickstart/' | relative_url }}">
    <div class="card-title">HTTP quickstart</div>
    <div class="card-body">Create, poll, verify, consume — the four routes, end to end.</div>
  </a>
  <a class="card" href="{{ '/terms-and-receipts/' | relative_url }}">
    <div class="card-title">Terms and receipts</div>
    <div class="card-body">What the human actually approves, and what the signed artifact contains.</div>
  </a>
  <a class="card" href="{{ '/action-enforcement/' | relative_url }}">
    <div class="card-title">Action enforcement</div>
    <div class="card-body">The contract for the boundary where a receipt is turned into an action.</div>
  </a>
</div>

## Three parties, three responsibilities

1. **The agent** creates an authorization request with exact terms and polls for the
   decision. Its `yak_` key can ask, not act.
2. **The user** approves or rejects in the YID app, gated on a fresh biometric scan.
3. **The action executor** (relying party) verifies the signed receipt against the proposed
   action and consumes it when single-use.

## Install

Pre-release: none of these packages is published to PyPI or npm yet. Until they are,
install from a checkout — see Development in the
[repository README]({{ site.github_repo }}#development).

| Path | Install |
|---|---|
| Python SDK | `pip install yanez-agent-authorization` |
| CLI | `pip install yanez-authz-cli` (installs `yanez-authz`) |
| MCP server | `pip install yanez-authz-mcp` |
| TypeScript SDK | `npm install @yanez/agent-authorization` |

## Credential rules

The `yak_` key comes from configuration (`YANEZ_AGENT_API_KEY` or a secret manager) — never
from model prompts, tool arguments, command-line flags, or logs. Never hand it to a
sub-agent.
