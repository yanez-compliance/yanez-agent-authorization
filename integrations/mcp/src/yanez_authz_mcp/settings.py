"""Startup-only configuration. The agent key lives in the environment of this local
stdio process and nowhere else — never in a tool argument, resource URI, prompt field,
or command-line flag. Error messages may name a missing variable but never echo values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    base_url: str
    agent_api_key: str = field(repr=False)  # keep it out of tracebacks and locals dumps
    http_timeout_seconds: float


def load_settings() -> Settings:
    missing = [name for name in ("YANEZ_BASE_URL", "YANEZ_AGENT_API_KEY")
               if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"missing required environment: {', '.join(missing)}")
    return Settings(
        base_url=os.environ["YANEZ_BASE_URL"],
        agent_api_key=os.environ["YANEZ_AGENT_API_KEY"],
        http_timeout_seconds=float(os.environ.get("YANEZ_HTTP_TIMEOUT_SECONDS", "10")),
    )
