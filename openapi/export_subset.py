#!/usr/bin/env python3
"""Extract the agent/relying-party subset of the server's canonical openapi.yaml.

The contract is not maintained by hand in two repositories: the Yanez server
repository owns openapi.yaml, and this script re-derives
agent-authorization.openapi.yaml from it, recording the source digest in SOURCE.json.
CI only checks that the checked-in artifact parses; re-export against a tagged server
release before publishing.

    python openapi/export_subset.py path/to/server/openapi.yaml [--server-release TAG]

Requires PyYAML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

PATHS = [
    "/api/agent/authorizations",
    "/api/agent/authorizations/{request_id}",
    "/api/authz/public-keys",
    "/api/authz/introspect",
]
SECURITY_SCHEMES = ["AgentApiKey"]

OUT_DIR = Path(__file__).parent


def _schema_refs(node, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[1])
        for value in node.values():
            _schema_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _schema_refs(value, found)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="path to the server's canonical openapi.yaml")
    ap.add_argument("--server-release", default="unreleased",
                    help="server release tag this export was taken from")
    args = ap.parse_args()

    source = Path(args.source)
    raw = source.read_bytes()
    spec = yaml.safe_load(raw)

    paths = {p: spec["paths"][p] for p in PATHS}

    # Chase $refs transitively so the subset is self-contained.
    needed: set[str] = set()
    _schema_refs(paths, needed)
    while True:
        before = set(needed)
        for name in before:
            _schema_refs(spec["components"]["schemas"][name], needed)
        if needed == before:
            break

    subset = {
        "openapi": spec["openapi"],
        "info": {
            "title": "Yanez Agent Authorization",
            "description": "Agent and relying-party surface of the Yanez authorization "
                           "service. Exported from the canonical server openapi.yaml; do "
                           "not edit by hand — rerun openapi/export_subset.py.",
            "version": spec["info"]["version"],
        },
        "components": {
            "securitySchemes": {k: spec["components"]["securitySchemes"][k]
                                for k in SECURITY_SCHEMES},
            "schemas": {k: spec["components"]["schemas"][k] for k in sorted(needed)},
        },
        "paths": paths,
    }

    out = OUT_DIR / "agent-authorization.openapi.yaml"
    out.write_text(yaml.safe_dump(subset, sort_keys=True, allow_unicode=True))
    (OUT_DIR / "SOURCE.json").write_text(json.dumps({
        "source": "server openapi.yaml",
        "server_release": args.server_release,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2) + "\n")
    print(f"wrote {out.name} ({len(needed)} schemas) and SOURCE.json")


if __name__ == "__main__":
    main()
