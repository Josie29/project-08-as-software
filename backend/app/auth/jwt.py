import asyncio
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID

import jwt
import structlog
from jwt import PyJWKClient
from pydantic import BaseModel

from app.config import Settings, get_settings

logger = structlog.get_logger(__name__)

#: Supabase signs with ES256. Pinning the algorithm stops a token that declares `alg: none`
#: or a symmetric algorithm from being accepted against a public key.
ALLOWED_ALGORITHMS = ["ES256"]

#: Matches the 10-minute Supabase Edge cache on the JWKS endpoint. Caching longer would
#: delay revocation when a signing key is rotated.
JWKS_CACHE_SECONDS = 600

_EXPECTED_AUDIENCE = "authenticated"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or not trustworthy."""


class TokenClaims(BaseModel):
    """The claims we are willing to act on.

    Only `sub` establishes identity. `user_metadata` is deliberately absent: it is
    user-editable in Supabase and must never inform an authorization decision.
    """

    subject: UUID
    email: str | None = None
    session_id: str | None = None


class SigningKeyResolver(Protocol):
    """The slice of `PyJWKClient` this module depends on, so tests can substitute it."""

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class SupabaseTokenVerifier:
    """Verifies Supabase access tokens locally against the project's public keys.

    Verification is local by design: calling Supabase to validate every request would add a
    network round trip to every PHI read and put the sub-second p95 targets out of reach.

    A valid signature proves the token was issued, not that the session is still live —
    deleting a user does not invalidate tokens already handed out. Short token lifetimes are
    the mitigation.
    """

    def __init__(self, settings: Settings, resolver: SigningKeyResolver | None = None) -> None:
        """Initialise the verifier.

        Args:
            settings: Application settings supplying the JWKS URL and project URL.
            resolver: Signing-key source; defaults to a caching JWKS client.
        """
        self._issuer = f"{settings.supabase_url}/auth/v1"
        self._resolver: SigningKeyResolver = resolver or PyJWKClient(
            settings.supabase_jwks_url,
            cache_keys=True,
            lifespan=JWKS_CACHE_SECONDS,
        )

    async def verify(self, token: str) -> TokenClaims:
        """Verify a bearer token and return the claims it is safe to trust.

        Args:
            token: The raw JWT from the Authorization header.

        Returns:
            The verified claims.

        Raises:
            TokenError: If the token is malformed, expired, signed by an unknown key, or
                carries the wrong issuer or audience.
        """
        try:
            # PyJWKClient is synchronous and refetches the key set on a cache miss, which
            # would otherwise block the event loop for the duration of that HTTP call.
            signing_key = await asyncio.to_thread(self._resolver.get_signing_key_from_jwt, token)
            payload: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=ALLOWED_ALGORITHMS,
                audience=_EXPECTED_AUDIENCE,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            # The reason is logged but never returned: telling a caller why their token was
            # rejected helps an attacker tune it.
            logger.info("auth.token_rejected", reason=type(exc).__name__)
            raise TokenError("token is not valid") from exc
        except Exception as exc:
            logger.warning("auth.jwks_unavailable", error=type(exc).__name__)
            raise TokenError("token could not be verified") from exc

        try:
            return TokenClaims(
                subject=UUID(str(payload["sub"])),
                email=payload.get("email"),
                session_id=payload.get("session_id"),
            )
        except (KeyError, ValueError) as exc:
            logger.info("auth.token_subject_invalid")
            raise TokenError("token is not valid") from exc


@lru_cache
def get_token_verifier() -> SupabaseTokenVerifier:
    """Return the process-wide verifier, so the JWKS cache is shared across requests.

    Returns:
        The cached verifier.
    """
    return SupabaseTokenVerifier(get_settings())
