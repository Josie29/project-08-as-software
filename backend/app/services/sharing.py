import hashlib
import secrets

#: 32 random bytes, url-safe encoded. The token is the entire credential for an
#: unauthenticated PHI read, so it has to be infeasible to guess — not merely unlikely.
TOKEN_BYTES = 32

#: Opens allowed on one link before it stops working. A share link can be forwarded,
#: quoted in a reply chain, or archived by a mail provider; capping use bounds how long a
#: leaked one keeps paying out, without breaking a recipient who reloads the page.
MAX_OPENS = 50


def mint_token() -> str:
    """Generate a share token.

    Returns:
        A url-safe token with 256 bits of entropy.
    """
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """Hash a share token for storage and lookup.

    Only the digest is ever persisted, so a database dump — or anyone with read access to
    the table — holds no working links. SHA-256 rather than a password hash is deliberate:
    the token already has full entropy, so there is nothing to brute force, and lookups
    have to be indexable.

    Args:
        token: The raw token from a share URL.

    Returns:
        The digest to store or compare.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()
