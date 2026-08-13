from datetime import datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator

from app.api.appointments import REFUSAL_STATUS, unwrap
from app.api.studies import NO_STORE
from app.auth.dependencies import get_provider_scope
from app.config import Settings, get_settings
from app.models.enums import AppointmentStatus
from app.repositories.scheduling import (
    AppointmentRecord,
    AvailabilityOutcome,
    AvailabilityRuleRecord,
    BlockedRangeRecord,
    ProviderScope,
)
from app.services.scheduling import SlotRule

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/provider", tags=["availability"])


class ReplaceRulesRequest(BaseModel):
    """The complete new set of working-hours rules for a provider.

    A full replacement rather than a patch: partial edits would leave the stored rules and
    the materialised slots able to drift apart.
    """

    rules: list[SlotRule] = Field(max_length=21)


class CreateBlockRequest(BaseModel):
    """A period the provider will not see patients."""

    start_utc: datetime
    end_utc: datetime
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _end_after_start(self) -> "CreateBlockRequest":
        """Reject an inverted range before it reaches the database.

        Returns:
            The validated request.

        Raises:
            ValueError: If the range ends at or before it starts.
        """
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        return self


class ChangeStatusRequest(BaseModel):
    """A staff-initiated appointment status change."""

    status: AppointmentStatus


def _unwrap_availability(outcome: AvailabilityOutcome) -> AvailabilityOutcome:
    """Return the availability result, or raise its refusal as an HTTP error.

    Args:
        outcome: The result from the scheduling layer.

    Returns:
        The successful outcome.

    Raises:
        HTTPException: 409 when the edit would have disturbed a booked slot.
    """
    if outcome.refusal is not None:
        raise HTTPException(
            status_code=REFUSAL_STATUS[outcome.refusal.code],
            detail={"code": outcome.refusal.code.value, "message": outcome.refusal.message},
        )
    return outcome


@router.get("/availability", response_model=list[AvailabilityRuleRecord])
async def list_availability(
    scope: Annotated[ProviderScope, Depends(get_provider_scope)],
    response: Response,
) -> list[AvailabilityRuleRecord]:
    """Return the caller's own working-hours rules.

    Args:
        scope: The staff member's provider scope.
        response: Used to set cache headers.

    Returns:
        The provider's rules.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_rules()


@router.put("/availability", response_model=AvailabilityOutcome)
async def replace_availability(
    payload: ReplaceRulesRequest,
    scope: Annotated[ProviderScope, Depends(get_provider_scope)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> AvailabilityOutcome:
    """Replace working hours and re-materialise bookable slots (Core #10).

    Args:
        payload: The complete new rule set.
        scope: The staff member's provider scope.
        settings: Application settings, for the materialisation horizon.
        response: Used to set cache headers.

    Returns:
        The stored rules and how many slots were created or withdrawn.

    Raises:
        HTTPException: 409 if a booked appointment falls outside the new hours.
    """
    outcome = await scope.replace_rules(payload.rules, horizon_days=settings.slot_horizon_days)
    response.headers["Cache-Control"] = NO_STORE
    return _unwrap_availability(outcome)


@router.get("/blocks", response_model=list[BlockedRangeRecord])
async def list_blocks(
    scope: Annotated[ProviderScope, Depends(get_provider_scope)],
    response: Response,
) -> list[BlockedRangeRecord]:
    """Return the caller's blocked ranges.

    Args:
        scope: The staff member's provider scope.
        response: Used to set cache headers.

    Returns:
        The provider's blocks, chronologically.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_blocks()


@router.post("/blocks", response_model=AvailabilityOutcome, status_code=status.HTTP_201_CREATED)
async def create_block(
    payload: CreateBlockRequest,
    scope: Annotated[ProviderScope, Depends(get_provider_scope)],
    response: Response,
) -> AvailabilityOutcome:
    """Block a period and withdraw the free slots inside it (Core #10).

    Args:
        payload: The range to block.
        scope: The staff member's provider scope.
        response: Used to set cache headers.

    Returns:
        How many slots were withdrawn.

    Raises:
        HTTPException: 409 if a booked appointment falls inside the range.
    """
    outcome = await scope.add_block(payload.start_utc, payload.end_utc, reason=payload.reason)
    response.headers["Cache-Control"] = NO_STORE
    return _unwrap_availability(outcome)


@router.get("/appointments", response_model=list[AppointmentRecord])
async def list_provider_appointments(
    scope: Annotated[ProviderScope, Depends(get_provider_scope)],
    response: Response,
) -> list[AppointmentRecord]:
    """Return the provider's upcoming appointments.

    Args:
        scope: The staff member's provider scope.
        response: Used to set cache headers.

    Returns:
        Appointments in chronological order.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_appointments()


@router.post("/appointments/{appointment_id}/status", response_model=AppointmentRecord)
async def change_appointment_status(
    appointment_id: UUID,
    payload: ChangeStatusRequest,
    scope: Annotated[ProviderScope, Depends(get_provider_scope)],
    response: Response,
) -> AppointmentRecord:
    """Move one of the provider's appointments through the lifecycle (Core #14).

    Args:
        appointment_id: The appointment to change.
        payload: The target status.
        scope: The staff member's provider scope.
        response: Used to set cache headers.

    Returns:
        The updated appointment.

    Raises:
        HTTPException: 404 if it is not this provider's, 409 for a transition the
            lifecycle does not allow.
    """
    outcome = await scope.change_status(appointment_id, payload.status)
    response.headers["Cache-Control"] = NO_STORE
    return unwrap(outcome)
