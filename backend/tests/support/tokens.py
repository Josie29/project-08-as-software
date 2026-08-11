from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth.jwt import SupabaseTokenVerifier
from app.config import get_settings

ISSUER = f"{get_settings().supabase_url}/auth/v1"
AUDIENCE = "authenticated"


class _StubKey:
    """Stands in for a PyJWK, exposing only the `key` attribute the verifier reads."""

    def __init__(self, key: Any) -> None:
        self.key = key


class StubResolver:
    """Returns a fixed public key, standing in for the JWKS endpoint.

    Substituting the resolver keeps the token tests offline and deterministic; the real
    `PyJWKClient` is exercised against the live endpoint by the health and seed flows.
    """

    def __init__(self, public_key: Any, *, fail: bool = False) -> None:
        self._public_key = public_key
        self._fail = fail

    def get_signing_key_from_jwt(self, token: str) -> _StubKey:
        """Return the stubbed signing key.

        Args:
            token: Unused; the stub does not inspect the header.

        Returns:
            The wrapped public key.

        Raises:
            LookupError: If the stub is configured to simulate an unknown `kid`.
        """
        if self._fail:
            raise LookupError("no matching signing key")
        return _StubKey(self._public_key)


@pytest.fixture(scope="session")
def signing_key() -> ec.EllipticCurvePrivateKey:
    """Generate an ES256 key pair for signing test tokens.

    Returns:
        A P-256 private key.
    """
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def verifier(signing_key: ec.EllipticCurvePrivateKey) -> SupabaseTokenVerifier:
    """Build a verifier wired to the test key pair.

    Args:
        signing_key: The generated private key.

    Returns:
        A verifier that trusts only the test key.
    """
    return SupabaseTokenVerifier(get_settings(), resolver=StubResolver(signing_key.public_key()))


@pytest.fixture
def make_token(signing_key: ec.EllipticCurvePrivateKey):
    """Return a factory that mints ES256 tokens with overridable claims.

    Args:
        signing_key: The private key to sign with.

    Returns:
        A callable producing encoded tokens.
    """

    def _make(**overrides: Any) -> str:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "sub": str(uuid4()),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(hours=1),
            "email": "patient@demo.test",
            "session_id": str(uuid4()),
        }
        claims.update(overrides)
        return jwt.encode(claims, signing_key, algorithm="ES256")

    return _make
