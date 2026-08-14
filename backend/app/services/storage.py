from typing import Annotated

import httpx
import structlog
from fastapi import Depends

from app.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 15.0

#: Connection ceiling for the shared client.
#:
#: Sized from the worst case rather than the typical one: a cine bundle fans out 16 ways and
#: concurrent viewers multiply that, so a ceiling near the fan-out turns the pool into a
#: queue and gives back the handshake it saved. This value has not been tuned against a
#: controlled measurement — see docs/benchmarks.md — it is reasoned from the fan-out.
_MAX_CONNECTIONS = 256

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the process-wide HTTP client used for storage reads.

    Shared rather than per-request because a new client means a new TCP and TLS handshake
    for every object. Measured against Supabase Storage that handshake costs ~134 ms per
    object — on a 100-frame cine clip it was the single largest component of the request,
    dwarfing the bytes themselves.

    Returns:
        The shared client, created on first use.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            limits=httpx.Limits(
                max_connections=_MAX_CONNECTIONS, max_keepalive_connections=_MAX_CONNECTIONS
            ),
        )
    return _client


async def close_http_client() -> None:
    """Close the shared client and reset module state, for shutdown and test teardown."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


class StorageError(Exception):
    """Raised when an object cannot be retrieved from object storage."""


class StorageObjectMissingError(StorageError):
    """Raised when the object does not exist.

    Distinct from a transport failure: a cine manifest may legitimately reference a frame
    that is absent, and the viewer degrades around it rather than failing (edge case #2).
    """


class ObjectStorage:
    """Reads PHI objects from Supabase Storage using the service-role credentials.

    Bytes are proxied through the API rather than served by signed URL so that every read
    passes the same authorization check and lands in the audit log. That choice costs a
    round trip per object, which is why the client below is pooled rather than per-call.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the client.

        Args:
            settings: Application settings holding the storage URL, key, and bucket.
        """
        self._base = f"{settings.supabase_url}/storage/v1/object"
        self._bucket = settings.supabase_storage_bucket
        # New-style `sb_secret_…` keys are not JWTs, so Storage rejects them as malformed
        # if presented as a Bearer token. Both headers are sent so a legacy key also works.
        self._headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        }

    async def download(self, path: str) -> bytes:
        """Fetch one object's bytes.

        Args:
            path: Storage path within the PHI bucket.

        Returns:
            The object's bytes.

        Raises:
            StorageObjectMissingError: If the object does not exist.
            StorageError: If storage is unreachable or returns an unexpected status.
        """
        url = f"{self._base}/{self._bucket}/{path}"
        try:
            response = await get_http_client().get(url, headers=self._headers)
        except httpx.HTTPError as exc:
            logger.warning("storage.unreachable", error=type(exc).__name__)
            raise StorageError("object storage is unavailable") from exc

        if response.status_code in (400, 404):
            logger.info("storage.object_missing")
            raise StorageObjectMissingError(path)
        if response.status_code != 200:
            logger.warning("storage.unexpected_status", status_code=response.status_code)
            raise StorageError(f"unexpected storage status {response.status_code}")
        return response.content


def get_object_storage(settings: Annotated[Settings, Depends(get_settings)]) -> ObjectStorage:
    """FastAPI dependency supplying the object storage client.

    Injected rather than constructed inside the route so tests can substitute a stub and
    exercise the delivery path without reaching the network.

    Args:
        settings: Application settings.

    Returns:
        A configured client.
    """
    return ObjectStorage(settings)
