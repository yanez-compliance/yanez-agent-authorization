# What the receipt is, and who enforces it

```text
this skill                 tells the model when and how to ask
  -> MCP tools / CLI       create and poll the authorization request
  -> Yanez HTTP API        <-> YID app + fresh biometric scan
  <- signed receipt        compact EdDSA JWS ("artifact")
  -> action executor       verifies terms, freshness, consent bound, replay state
  -> action executes
```

- The `yak_` agent key can ASK, not act. A stolen key can annoy the user with
  prompts; it cannot mint an approved receipt.
- Approval is bound to the verbatim terms stored on the request. The app cannot
  substitute different terms; the receipt carries the same JSON as `yanez_terms`.
- The enforcement boundary is the action executor, never this skill and never an MCP
  status field. Its trusted API takes both the proposed action and the receipt,
  reconstructs the expected terms, and verifies before executing. Single-use actions
  consume the receipt (introspection with `consume: true`) immediately before acting.
- Verification and permission to act are different questions. A receipt verifies
  forever — it is durable evidence. Whether it may be ACTED on now is gated by the
  relying party's freshness policy (`yanez_decided_at`), the consent bound the agent
  declared on the user's behalf (`yanez_consent_not_after`), and single-use consumption.
- Correct language: "Yanez signed a receipt asserting that a fresh biometric scan
  matching this YID approved these terms." Not "the user signed".

Builders may fork this skill to add domain-specific term schemas, but must not weaken
its stop rules, exact-term rules, or receipt handling.
