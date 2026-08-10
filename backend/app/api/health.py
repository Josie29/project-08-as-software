import asyncio
from enum import StrEnum
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])

_DEPENDENCY_TIMEOUT_SECONDS = 3.0


class DependencyStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class HealthResponse(BaseModel):
    """Reachability of the app and each dependency the brief requires reporting on."""

    app: DependencyStatus
    database: DependencyStatus
    storage: DependencyStatus


async def _check_database(session: AsyncSession) -> DependencyStatus:
    """Probe database reachability with a trivial query.

    Args:
        session: Request-scoped database session.

    Returns:
        `OK` if the query succeeds, `DEGRADED` otherwise.
    """
    try:
        async with asyncio.timeout(_DEPENDENCY_TIMEOUT_SECONDS):
            await session.execute(text("SELECT 1"))
    except (TimeoutError, OSError) as exc:
        logger.warning("health.database_unreachable", error=str(exc))
        return DependencyStatus.DEGRADED
    except Exception as exc:  # SQLAlchemy wraps driver errors in many shapes.
        logger.warning("health.database_error", error=type(exc).__name__)
        return DependencyStatus.DEGRADED
    return DependencyStatus.OK


async def _check_storage(settings: Settings) -> DependencyStatus:
    """Probe object-storage reachability via the Supabase Storage bucket endpoint.

    Args:
        settings: Application settings holding the storage URL and service key.

    Returns:
        `OK` if the bucket responds, `DEGRADED` otherwise.
    """
    url = f"{settings.supabase_url}/storage/v1/bucket/{settings.supabase_storage_bucket}"
    # Sent as `apikey` rather than a Bearer token: new-style `sb_secret_…` keys are not
    # JWTs, and Storage rejects them as malformed if presented as Bearer. Both headers
    # are sent so a legacy JWT `service_role` key keeps working too.
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    try:
        async with httpx.AsyncClient(timeout=_DEPENDENCY_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("health.storage_unreachable", error=type(exc).__name__)
        return DependencyStatus.DEGRADED
    if response.status_code != status.HTTP_200_OK:
        logger.warning("health.storage_bad_status", status_code=response.status_code)
        return DependencyStatus.DEGRADED
    return DependencyStatus.OK


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Report app, database, and storage reachability.

    Returns 200 when every dependency is reachable and 503 otherwise, so an uptime
    check can treat the status code alone as the signal.

    Args:
        response: Injected so the status code can be set on partial failure.
        session: Request-scoped database session.
        settings: Application settings.

    Returns:
        Per-dependency status.
    """
    database, storage = await asyncio.gather(_check_database(session), _check_storage(settings))
    if DependencyStatus.DEGRADED in (database, storage):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(app=DependencyStatus.OK, database=database, storage=storage)
