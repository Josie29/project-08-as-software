import asyncio
from datetime import date
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import AuthenticatedUser, get_authenticated_user
from app.config import Settings, get_settings
from app.db import get_db_session
from app.services.identity import (
    VerificationOutcome,
    attempt_verification,
    sleep_until_response_floor,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/identity", tags=["identity"])

#: The single message returned for every failed attempt. It must never indicate whether the
#: account id exists, whether the date of birth was wrong, or whether the record already
#: belongs to another login (Core #2).
GENERIC_FAILURE_MESSAGE = "We could not verify those details. Please check them and try again."


class VerifyIdentityRequest(BaseModel):
    """The two factors printed on a patient's clinic paperwork."""

    account_id: str = Field(min_length=1, max_length=64)
    date_of_birth: date


class VerifyIdentityResponse(BaseModel):
    """Confirmation that the caller is now verified."""

    verified: bool


@router.post("/verify", response_model=VerifyIdentityResponse)
async def verify_identity(
    payload: VerifyIdentityRequest,
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> VerifyIdentityResponse:
    """Match a signed-in user against their seeded clinical record.

    Args:
        payload: Submitted account id and date of birth.
        user: The signed-in caller.
        session: Database session.
        settings: Application settings.
        response: Used to set Retry-After when locked out.

    Returns:
        Confirmation of verification.

    Raises:
        HTTPException: 403 on any mismatch, 429 when locked out.
    """
    started_at = asyncio.get_running_loop().time()
    result = await attempt_verification(
        session,
        settings,
        auth_user_id=user.auth_user_id,
        account_id=payload.account_id.strip(),
        date_of_birth=payload.date_of_birth,
    )
    # Padding applies to every outcome. A fast lockout and a slow mismatch would tell an
    # attacker which bucket they had tripped.
    await sleep_until_response_floor(started_at)

    if result.outcome is VerificationOutcome.LOCKED_OUT:
        response.headers["Retry-After"] = str(result.retry_after_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=GENERIC_FAILURE_MESSAGE,
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    if result.outcome is VerificationOutcome.MISMATCH:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=GENERIC_FAILURE_MESSAGE)
    return VerifyIdentityResponse(verified=True)


@router.get("/status", response_model=VerifyIdentityResponse)
async def identity_status(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifyIdentityResponse:
    """Report whether the caller currently holds a live verification.

    Lets the frontend route to the verification screen without first provoking a 403 on a
    PHI request.

    Args:
        user: The signed-in caller.
        session: Database session.

    Returns:
        Whether the caller is verified.
    """
    from app.auth.dependencies import get_verified_patient

    try:
        await get_verified_patient(user, session)
    except HTTPException:
        return VerifyIdentityResponse(verified=False)
    return VerifyIdentityResponse(verified=True)
