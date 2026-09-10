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
  party, not the agent) must verify <strong>both signatures</strong> — Yanez's, and the approver's
  own — compare the signed terms against the proposed action, apply its own freshness and
  assurance policy, and consume single-use receipts.</p>
</div>

## How it works

```mermaid
sequenceDiagram
    participant A as Agent
    participant Y as Yanez Pulse
    participant U as User (YID app)
    participant R as Relying party
    A->>Y: 1. POST /api/agent/authorizations (yak_ key, terms)
    Y-->>U: 2. Push notification
    U->>Y: 3. Approve or reject, gated on biometrics
    A->>Y: 4. GET /api/agent/authorizations/{id}?wait=25
    Y-->>A: approved + signed receipt, or rejected / expired
    A->>R: Proposed action + receipt
    R->>Y: 5. GET /api/authz/public-keys, POST /api/authz/introspect
    R->>R: Verify, consume, then act
```

1. **The agent creates a request.** It sends the exact `terms` to Yanez Pulse with its
   `yak_` agent API key. The key can ask, not act.
2. **Yanez Pulse notifies the user.** A push notification reaches the user's device.
3. **The user decides.** They approve or reject in the YID app, gated on a fresh biometric
   scan. Their own key signs the decision, and approval produces a receipt carrying both
   that signature and Yanez's: [user-signed approvals](user-signed-approvals.md).
4. **The agent polls for the decision.** It long-polls the request until it is `approved`
   (with the receipt), `rejected`, or `expired`.
5. **The relying party checks the receipt.** The action executor verifies Yanez's signature
   offline against Yanez's public keys and the approver's signature against the key inside
   the receipt, compares the signed terms with the proposed action, consumes the receipt
   when the action is single-use, and only then acts.

## Start here

Two ways in. Pick one.

<div class="cards">
  <a class="card" href="{{ '/ai-agents/' | relative_url }}">
    <div class="card-title">Let an AI agent integrate it</div>
    <div class="card-body">Paste one prompt into Claude Code, Cursor, Codex, or a chat assistant. It reads llms.txt and wires the integration in.</div>
  </a>
  <a class="card" href="{{ '/integration-options/' | relative_url }}">
    <div class="card-title">Integrate it yourself</div>
    <div class="card-body">Python, TypeScript, CLI + skill, MCP, or raw HTTP. Pick the highest layer your runtime supports, then follow its quickstart.</div>
  </a>
</div>

## Understand the model

<div class="cards">
  <a class="card" href="{{ '/terms/' | relative_url }}">
    <div class="card-title">Terms</div>
    <div class="card-body">The object the human actually approves, field by field.</div>
  </a>
  <a class="card" href="{{ '/receipts/' | relative_url }}">
    <div class="card-title">Receipts</div>
    <div class="card-body">What the signed artifact contains, how it is signed, and how its keys rotate.</div>
  </a>
  <a class="card" href="{{ '/user-signed-approvals/' | relative_url }}">
    <div class="card-title">User-signed approvals</div>
    <div class="card-body">The approver's own signature: what changed in the schema, and the steps to verify both signatures.</div>
  </a>
  <a class="card" href="{{ '/action-enforcement/' | relative_url }}">
    <div class="card-title">Action enforcement</div>
    <div class="card-body">The contract for the boundary where a receipt is turned into an action.</div>
  </a>
</div>
