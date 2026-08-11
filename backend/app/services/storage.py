import httpx
import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 15.0


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
    passes the same authorization check and lands in the audit log.
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
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(url, headers=self._headers)
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


def get_object_storage(settings: Settings) -> ObjectStorage:
    """Build an object storage client.

    Args:
        settings: Application settings.

    Returns:
        A configured client.
    """
    return ObjectStorage(settings)
