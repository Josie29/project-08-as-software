from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import structlog
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.audit import AuditLogEntry, ReminderSend
from app.models.enums import (
    LIVE_APPOINTMENT_STATUSES,
    AuditAction,
    AuditActorType,
    ReminderKind,
    ReminderStatus,
)
from app.models.identity import Patient, Provider
from app.models.scheduling import Appointment, AppointmentSlot
from app.services.email import EmailError, EmailSender

logger = structlog.get_logger(__name__)

#: Rendered into the reminder body, e.g. "Tuesday 18 August 2026 at 2:30 PM EDT".
_WHEN_FORMAT = "%A %d %B %Y at %-I:%M %p %Z"


class DueReminder(BaseModel):
    """One appointment owed a reminder, with everything needed to send it."""

    appointment_id: UUID
    patient_email: str
    start_utc: datetime
    provider_timezone: str


class ReminderRun(BaseModel):
    """What one pass of the reminder job did.

    Returned rather than logged alone so the CLI can print it and tests can assert on it.
    """

    due: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0


def render_when(start_utc: datetime, timezone: str) -> str:
    """Render an appointment time in the clinic's local zone.

    The clinic's zone rather than the patient's: it is where they physically have to be,
    and the browser zone a patient last used is not something a background job can know.

    Args:
        start_utc: The appointment's absolute start instant.
        timezone: The provider's IANA timezone.

    Returns:
        A human-readable local time carrying its zone abbreviation.
    """
    return start_utc.astimezone(ZoneInfo(timezone)).strftime(_WHEN_FORMAT)


async def find_due_reminders(
    session: AsyncSession, *, lead_hours: int, now: datetime
) -> list[DueReminder]:
    """Return live appointments starting inside the reminder window.

    Args:
        session: Database session.
        lead_hours: How far ahead of the start time a reminder is owed.
        now: Current time, injected so the window is testable.

    Returns:
        The appointments owed a reminder, soonest first.
    """
    result = await session.execute(
        select(Appointment.id, Patient.email, AppointmentSlot.start_utc, Provider.timezone)
        .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(Provider, Provider.id == AppointmentSlot.provider_id)
        .where(
            Appointment.status.in_(tuple(LIVE_APPOINTMENT_STATUSES)),
            AppointmentSlot.start_utc > now,
            AppointmentSlot.start_utc <= now + timedelta(hours=lead_hours),
        )
        .order_by(AppointmentSlot.start_utc)
    )
    return [
        DueReminder(
            appointment_id=appointment_id,
            patient_email=email,
            start_utc=start_utc,
            provider_timezone=timezone,
        )
        for appointment_id, email, start_utc, timezone in result.all()
    ]


async def _claim(session: AsyncSession, appointment_id: UUID, now: datetime) -> bool:
    """Take exclusive ownership of sending one reminder.

    The insert is the claim. Two overlapping runs both reach it and the unique constraint
    on (appointment_id, kind) lets exactly one through, so no reminder can be sent twice
    however often the job runs or however many API instances run it (edge case #9).

    Claiming before sending, rather than recording after, is deliberate: a crash between
    the two loses a reminder, whereas the reverse order would send a second one. The brief
    allows under-delivery within its 99% target and allows no duplicates at all.

    Args:
        session: Database session.
        appointment_id: The appointment to claim.
        now: Current time.

    Returns:
        True if this caller now owns the send, False if another run already claimed it.
    """
    claimed = await session.scalar(
        pg_insert(ReminderSend)
        .values(
            appointment_id=appointment_id,
            kind=ReminderKind.PRE_VISIT_24H,
            status=ReminderStatus.FAILED,
            attempted_at=now,
            error_detail="claimed, send not yet attempted",
        )
        .on_conflict_do_nothing(constraint="uq_reminder_sends_appointment_id_kind")
        .returning(ReminderSend.id)
    )
    await session.commit()
    return claimed is not None


async def _finalise(
    session: AsyncSession,
    appointment_id: UUID,
    *,
    status: ReminderStatus,
    provider_message_id: str | None = None,
    error_detail: str | None = None,
) -> None:
    """Record the outcome of a claimed send.

    Args:
        session: Database session.
        appointment_id: The appointment whose reminder was attempted.
        status: Whether the provider accepted the message.
        provider_message_id: Resend's id, for tracing a delivery complaint.
        error_detail: Why it failed, if it did.
    """
    await session.execute(
        update(ReminderSend)
        .where(
            ReminderSend.appointment_id == appointment_id,
            ReminderSend.kind == ReminderKind.PRE_VISIT_24H,
        )
        .values(status=status, provider_message_id=provider_message_id, error_detail=error_detail)
    )
    session.add(
        AuditLogEntry(
            # No actor id: the job runs on nobody's behalf, and the column is nullable
            # precisely for system actions like this one.
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            action=AuditAction.REMINDER_DISPATCHED.value,
            resource_type="appointment",
            resource_id=appointment_id,
        )
    )
    await session.commit()


async def dispatch_due_reminders(
    session: AsyncSession,
    settings: Settings,
    sender: EmailSender,
    *,
    now: datetime | None = None,
) -> ReminderRun:
    """Send reminders for every appointment inside the lead window that has not had one.

    Safe to run repeatedly and safe to overlap with itself: each appointment is claimed
    through a unique constraint before any mail is sent, so a second concurrent pass finds
    nothing to do rather than sending again (Core #15, edge case #9).

    Args:
        session: Database session.
        settings: Supplies the lead window and the portal URL.
        sender: Email transport.
        now: Current time, injected for tests.

    Returns:
        Counts for the pass.
    """
    moment = now or datetime.now(UTC)
    due = await find_due_reminders(session, lead_hours=settings.reminder_lead_hours, now=moment)
    run = ReminderRun(due=len(due))

    for reminder in due:
        if not await _claim(session, reminder.appointment_id, moment):
            run.skipped += 1
            continue

        try:
            message_id = await sender.send_appointment_reminder(
                reminder.patient_email,
                render_when(reminder.start_utc, reminder.provider_timezone),
                f"{settings.frontend_base_url}/appointments",
            )
        except EmailError as exc:
            # The address is not logged: it is a patient's contact detail.
            logger.warning(
                "reminder.send_failed",
                appointment_uuid=str(reminder.appointment_id),
                error=type(exc).__name__,
            )
            await _finalise(
                session,
                reminder.appointment_id,
                status=ReminderStatus.FAILED,
                error_detail=str(exc)[:500],
            )
            run.failed += 1
            continue

        await _finalise(
            session,
            reminder.appointment_id,
            status=ReminderStatus.SENT,
            provider_message_id=message_id,
        )
        run.sent += 1

    logger.info(
        "reminder.run_complete",
        due=run.due,
        sent=run.sent,
        failed=run.failed,
        skipped=run.skipped,
    )
    return run
