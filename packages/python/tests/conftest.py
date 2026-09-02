from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "conformance" / "fixtures"


@pytest.fixture(scope="session")
def jwks() -> dict:
    return json.loads((FIXTURES / "jwks.json").read_text())


@pytest.fixture(scope="session")
def receipts() -> dict:
    return json.loads((FIXTURES / "receipts.json").read_text())


@pytest.fixture(scope="session")
def http_fixtures() -> dict:
    return json.loads((FIXTURES / "http.json").read_text())
