# Security policy

Report vulnerabilities privately to **security@yanez.ai**. Do not open a
public issue for a security report. We aim to acknowledge within 3 business days.

In scope: everything in this repository — the SDKs, CLI, MCP server, skill text, and
the exported OpenAPI contract. The Yanez server itself is a separate codebase; server
reports are welcome at the same address.

Never include a live agent key (`yak_...`), a production artifact, or personal data in
a report. Fixture material in `conformance/fixtures/` is fake and safe to reference.
