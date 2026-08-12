from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Response

from app.api.studies import NO_STORE, not_found
from app.auth.dependencies import get_patient_scope
from app.repositories.phi import PatientScope, ReportDetail, ReportSummary

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=list[ReportSummary])
async def list_reports(
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> list[ReportSummary]:
    """List the reports the patient is permitted to read.

    Only signed reports appear. A preliminary read stays with the care team until a
    radiologist signs it (Core #7).

    Args:
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The patient's signed reports, newest first.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_signed_reports()


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> ReportDetail:
    """Return one signed report in full.

    Args:
        report_id: The report requested.
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The report body and metadata.

    Raises:
        HTTPException: 404 if it is missing, unsigned, or another patient's — all three
            answer identically so none of them can be told apart.
    """
    report = await scope.open_report(report_id)
    if report is None:
        raise not_found()
    response.headers["Cache-Control"] = NO_STORE
    return report
