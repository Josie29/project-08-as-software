from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Response

from app.api.studies import NO_STORE
from app.auth.dependencies import get_patient_scope
from app.repositories.phi import ActivityEntry, PatientScope

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["compliance"])


@router.get("/activity", response_model=list[ActivityEntry])
async def list_activity(
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ActivityEntry]:
    """Return the caller's own access log.

    Reading the log is not itself audited. An audited read of the audit log grows the table
    every time the screen is opened and buries the accesses a reviewer is actually looking
    for, without recording anything the session log does not already show.

    Args:
        scope: The verified patient's scope.
        response: Used to set cache headers.
        limit: Maximum entries to return.

    Returns:
        Their activity, newest first.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_activity(limit=limit)
