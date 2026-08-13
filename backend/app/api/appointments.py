from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.studies import NO_STORE
from app.auth.dependencies import get_booking_scope
from app.config import Settings, get_settings
from app.repositories.scheduling import (
    AppointmentRecord,
    BookingOutcome,
    BookingScope,
    ProviderSummary,
    ScheduleRefusalCode,
    SlotOffer,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["scheduling"])

#: How a refusal from the scheduling layer surfaces over HTTP. Booking conflicts answer 409
#: rather than 500: a slot being taken is an expected race, not a server fault (brief: Code
#: Quality & Engineering Practices).
REFUSAL_STATUS: dict[ScheduleRefusalCode, int] = {
    ScheduleRefusalCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ScheduleRefusalCode.SLOT_TAKEN: status.HTTP_409_CONFLICT,
    ScheduleRefusalCode.SLOT_UNAVAILABLE: status.HTTP_409_CONFLICT,
    ScheduleRefusalCode.INVALID_TRANSITION: status.HTTP_409_CONFLICT,
    ScheduleRefusalCode.BOOKED_SLOT_CONFLICT: status.HTTP_409_CONFLICT,
    ScheduleRefusalCode.TOO_LATE: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def unwrap(outcome: BookingOutcome) -> AppointmentRecord:
    """Return the appointment, or raise the refusal as an HTTP error.

    Args:
        outcome: The result from the scheduling layer.

    Returns:
        The appointment the caller asked for.

    Raises:
        HTTPException: Mapped from the refusal code, carrying the code so the UI can
            react to a lost race differently from a validation failure.
    """
    if outcome.appointment is not None:
        return outcome.appointment

    refusal = outcome.refusal
    if refusal is None:  # pragma: no cover - the outcome always carries one or the other
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Scheduling failed."
        )
    raise HTTPException(
        status_code=REFUSAL_STATUS[refusal.code],
        detail={"code": refusal.code.value, "message": refusal.message},
    )


class BookRequest(BaseModel):
    """A request to book one open slot."""

    slot_id: UUID
    # Client-generated per submission. A double-click or a retry replays the same key and
    # returns the original appointment rather than booking twice (edge case #10).
    idempotency_key: str | None = Field(default=None, max_length=200)


class RescheduleRequest(BaseModel):
    """A request to move an appointment to a different slot."""

    slot_id: UUID


class CancelRequest(BaseModel):
    """A request to cancel an appointment."""

    reason: str | None = Field(default=None, max_length=500)


@router.get("/providers", response_model=list[ProviderSummary])
async def list_providers(
    scope: Annotated[BookingScope, Depends(get_booking_scope)],
    response: Response,
) -> list[ProviderSummary]:
    """List the clinicians a patient can book with.

    Args:
        scope: The verified patient's booking scope.
        response: Used to set cache headers.

    Returns:
        Bookable providers.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_providers()


@router.get("/providers/{provider_id}/slots", response_model=list[SlotOffer])
async def list_slots(
    provider_id: UUID,
    scope: Annotated[BookingScope, Depends(get_booking_scope)],
    response: Response,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> list[SlotOffer]:
    """List genuinely open, future slots for one provider (Core #11).

    Args:
        provider_id: The clinician to search.
        scope: The verified patient's booking scope.
        response: Used to set cache headers.
        days: How far ahead to look.

    Returns:
        Open slots in chronological order.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_open_slots(provider_id, days=days)


@router.get("/appointments", response_model=list[AppointmentRecord])
async def list_appointments(
    scope: Annotated[BookingScope, Depends(get_booking_scope)],
    response: Response,
) -> list[AppointmentRecord]:
    """List the caller's own appointments.

    Args:
        scope: The verified patient's booking scope.
        response: Used to set cache headers.

    Returns:
        Their appointments, soonest first.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_appointments()


@router.post("/appointments", response_model=AppointmentRecord, status_code=status.HTTP_201_CREATED)
async def book_appointment(
    payload: BookRequest,
    scope: Annotated[BookingScope, Depends(get_booking_scope)],
    response: Response,
) -> AppointmentRecord:
    """Book an open slot for the caller (Core #11, #12).

    Args:
        payload: The slot and optional submission key.
        scope: The verified patient's booking scope.
        response: Used to set cache headers.

    Returns:
        The persisted appointment.

    Raises:
        HTTPException: 409 if the slot was taken or withdrawn.
    """
    outcome = await scope.book(payload.slot_id, idempotency_key=payload.idempotency_key)
    response.headers["Cache-Control"] = NO_STORE
    return unwrap(outcome)


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentRecord)
async def reschedule_appointment(
    appointment_id: UUID,
    payload: RescheduleRequest,
    scope: Annotated[BookingScope, Depends(get_booking_scope)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> AppointmentRecord:
    """Move one of the caller's appointments to another open slot (Core #13).

    Args:
        appointment_id: The appointment to move.
        payload: The target slot.
        scope: The verified patient's booking scope.
        settings: Application settings, for the notice policy.
        response: Used to set cache headers.

    Returns:
        The moved appointment.

    Raises:
        HTTPException: 404 if it is not theirs, 409 if the target was taken, 422 inside
            the minimum-notice window.
    """
    outcome = await scope.reschedule(
        appointment_id,
        payload.slot_id,
        min_notice_hours=settings.booking_min_notice_hours,
    )
    response.headers["Cache-Control"] = NO_STORE
    return unwrap(outcome)


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentRecord)
async def cancel_appointment(
    appointment_id: UUID,
    payload: CancelRequest,
    scope: Annotated[BookingScope, Depends(get_booking_scope)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> AppointmentRecord:
    """Cancel one of the caller's appointments, freeing the slot (Core #13).

    Args:
        appointment_id: The appointment to cancel.
        payload: Optional reason.
        scope: The verified patient's booking scope.
        settings: Application settings, for the notice policy.
        response: Used to set cache headers.

    Returns:
        The cancelled appointment.

    Raises:
        HTTPException: 404 if it is not theirs, 409 if it is already final, 422 inside
            the minimum-notice window.
    """
    outcome = await scope.cancel(
        appointment_id,
        min_notice_hours=settings.booking_min_notice_hours,
        reason=payload.reason,
    )
    response.headers["Cache-Control"] = NO_STORE
    return unwrap(outcome)
