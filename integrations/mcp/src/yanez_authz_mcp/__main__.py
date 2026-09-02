from __future__ import annotations

import argparse
import logging
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="yanez-authz-mcp")
    parser.add_argument("--check", action="store_true",
                        help="operator diagnostic: confirm both environment variables are set "
                             "and the public-key route answers; never uses the agent key "
                             "or creates a request")
    args = parser.parse_args()

    from yanez_authz_mcp.settings import load_settings
    settings = load_settings()

    if args.check:
        import httpx

        from yanez_authz.async_client import require_trusted_origin

        base = require_trusted_origin(settings.base_url)
        response = httpx.get(f"{base}/api/authz/public-keys", timeout=10,
                             follow_redirects=False)
        response.raise_for_status()
        kids = [str(k.get("kid")) for k in response.json().get("keys", [])]
        print(f"ok: {len(kids)} signing key(s): {', '.join(kids)}", file=sys.stderr)
        return 0

    from yanez_authz_mcp.server import build_server

    # stdout is the protocol stream; configure logging here, never at import time.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    build_server(settings).run()  # stdio transport; blocks for the session
    return 0


if __name__ == "__main__":
    sys.exit(main())
