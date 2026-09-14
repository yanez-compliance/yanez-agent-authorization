from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from py_ecc.bls import G2Basic

CONFORMANCE = Path(__file__).resolve().parents[3] / "conformance"
FIXTURES = CONFORMANCE / "fixtures"

# The fixture generator is the single definition of a well-formed receipt, seeds and
# all. Tests that need a receipt the static fixtures cannot express mint one through it
# rather than keeping a second, drifting copy of the same construction.
sys.path.insert(0, str(CONFORMANCE))
import generate_fixtures as gen  # noqa: E402


@pytest.fixture(scope="session")
def jwks() -> dict:
    return json.loads((FIXTURES / "jwks.json").read_text())


@pytest.fixture(scope="session")
def receipts() -> dict:
    return json.loads((FIXTURES / "receipts.json").read_text())


@pytest.fixture(scope="session")
def http_fixtures() -> dict:
    return json.loads((FIXTURES / "http.json").read_text())


@pytest.fixture(scope="session")
def mint():
    """Mint a receipt carrying a consistent user proof.

    Overriding a claim by hand is not enough now that receipts carry two signatures: a
    receipt whose `yanez_terms` was edited no longer agrees with the bytes the user
    signed, so every such test would fail for the wrong reason. Pass `terms` to change
    both sides at once, `envelope` to change only what the user signed, and any other
    keyword to override a claim.
    """
    key = Ed25519PrivateKey.from_private_bytes(gen.SIGNING_SEED)
    user_sk = G2Basic.KeyGen(gen.USER_SEED)

    def _mint(*, terms=None, envelope=None, **claim_overrides) -> str:
        env = gen._envelope(**(envelope or {}))
        if terms is not None:
            env["terms"] = terms
            claim_overrides.setdefault("yanez_terms", terms)
        return gen._sign(key, gen.KID, gen._claims(user_sk, envelope=env, **claim_overrides))

    return _mint


@pytest.fixture(scope="session")
def user_keys() -> dict:
    return json.loads((FIXTURES / "user_keys.json").read_text())
