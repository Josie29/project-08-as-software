from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLogEntry
from app.models.enums import (
    LIVE_APPOINTMENT_STATUSES,
    AppointmentStatus,
    AuditAction,
    AuditActorType,
    SlotStatus,
)
from app.models.identity import Provider
from app.models.scheduling import Appointment, AppointmentSlot, AvailabilityRule, BlockedRange
from app.services.scheduling import SlotRule, check_transition, generate_slots, notice_shortfall

logger = structlog.get_logger(__name__)


class ProviderSummary(BaseModel):
    """A bookable clinician, as offered to a patient choosing who to see."""

    id: UUID
    display_name: str
    specialty: str | None
    timezone: str


class SlotOffer(BaseModel):
    """An open, future slot a patient may book."""

    id: UUID
    provider_id: UUID
    start_utc: datetime
    end_utc: datetime


class AppointmentRecord(BaseModel):
    """A patient's appointment with the context needed to display it."""

    id: UUID
    status: AppointmentStatus
    slot_id: UUID
    start_utc: datetime
    end_utc: datetime
    provider_id: UUID
    provider_name: str
    provider_timezone: str
    booked_at: datetime
    cancelled_at: datetime | None
    reason: str | None


class AvailabilityRuleRecord(BaseModel):
    """One weekday's working hours, in the provider's local wall-clock time."""

    id: UUID
    weekday: int
    start_local: time
    end_local: time
    slot_minutes: int


class BlockedRangeRecord(BaseModel):
    """A period the provider has marked unavailable."""

    id: UUID
    start_utc: datetime
    end_utc: datetime
    reason: str | None


class ScheduleRefusalCode(StrEnum):
    """Why a scheduling request was refused.

    Carried as a code rather than only a sentence so the router maps each to the right
    status without matching on message text.
    """

    NOT_FOUND = "not_found"
    SLOT_TAKEN = "slot_taken"
    SLOT_UNAVAILABLE = "slot_unavailable"
    TOO_LATE = "too_late"
    INVALID_TRANSITION = "invalid_transition"
    BOOKED_SLOT_CONFLICT = "booked_slot_conflict"


class ScheduleRefusal(BaseModel):
    """A refused scheduling request, phrased for the patient or staff member."""

    code: ScheduleRefusalCode
    message: str


class BookingOutcome(BaseModel):
    """The result of a booking, reschedule, cancel, or status change.

    Exactly one of the two fields is set.
    """

    appointment: AppointmentRecord | None = None
    refusal: ScheduleRefusal | None = None


class AvailabilityOutcome(BaseModel):
    """The result of an availability edit.

    `refusal` is set when the edit would have disturbed an already-booked slot.
    """

    rules: list[AvailabilityRuleRecord] = []
    slots_created: int = 0
    slots_removed: int = 0
    refusal: ScheduleRefusal | None = None


#: Message shown whenever a slot will not book. Deliberately identical for "already taken"
#: and "not offered", so probing slot ids cannot map out a provider's private calendar.
_SLOT_UNAVAILABLE_MESSAGE = "That time is no longer available."

#: Shared by both scopes: an appointment currently holding its slot.
_LIVE = tuple(LIVE_APPOINTMENT_STATUSES)


def _appointment_record(
    appointment: Appointment, slot: AppointmentSlot, provider: Provider
) -> AppointmentRecord:
    """Assemble the display record for one appointment.

    Args:
        appointment: The appointment row.
        slot: The slot it occupies.
        provider: The clinician the slot belongs to.

    Returns:
        The combined record.
    """
    return AppointmentRecord(
        id=appointment.id,
        status=appointment.status,
        slot_id=slot.id,
        start_utc=slot.start_utc,
        end_utc=slot.end_utc,
        provider_id=provider.id,
        provider_name=provider.display_name,
        provider_timezone=provider.timezone,
        booked_at=appointment.booked_at,
        cancelled_at=appointment.cancelled_at,
        reason=appointment.reason,
    )


class BookingScope:
    """The only route to a patient's scheduling data.

    Mirrors `PatientScope`: every query filters on the scope's own `patient_id` in SQL, so
    an appointment belonging to someone else never loads and there is no post-hoc ownership
    check to forget.
    """

    def __init__(
        self,
        session: AsyncSession,
        patient_id: UUID,
        *,
        request_id: str | None = None,
    ) -> None:
        """Initialise the scope.

        Args:
            session: Request-scoped database session.
            patient_id: The verified patient this scope may act for.
            request_id: Correlates audit entries with the request log.
        """
        self._session = session
        self._patient_id = patient_id
        self._request_id = request_id

    async def _record(self, action: AuditAction, resource_id: UUID) -> None:
        """Append an audit entry for a booking action.

        Args:
            action: What was done.
            resource_id: The appointment or slot touched.
        """
        self._session.add(
            AuditLogEntry(
                actor_type=AuditActorType.PATIENT,
                actor_id=self._patient_id,
                action=action.value,
                resource_type="appointment",
                resource_id=resource_id,
                request_id=self._request_id,
            )
        )
        await self._session.commit()

    async def list_providers(self) -> list[ProviderSummary]:
        """Return every bookable clinician.

        Returns:
            Providers in display-name order.
        """
        result = await self._session.scalars(select(Provider).order_by(Provider.display_name))
        return [
            ProviderSummary(
                id=provider.id,
                display_name=provider.display_name,
                specialty=provider.specialty,
                timezone=provider.timezone,
            )
            for provider in result.all()
        ]

    async def list_open_slots(
        self, provider_id: UUID, *, days: int = 30, now: datetime | None = None
    ) -> list[SlotOffer]:
        """Return genuinely open, future slots for one provider.

        A slot is offerable only if it is open, still in the future, and unclaimed. The
        unclaimed test is a NOT EXISTS against live appointments rather than a flag on the
        slot, so the list can never disagree with the constraint that arbitrates booking.

        Args:
            provider_id: The clinician to search.
            days: How far ahead to look.
            now: Current time, injected for tests.

        Returns:
            Open slots in chronological order.
        """
        moment = now or datetime.now(UTC)
        taken = (
            select(Appointment.id)
            .where(
                Appointment.slot_id == AppointmentSlot.id,
                Appointment.status.in_(_LIVE),
            )
            .correlate(AppointmentSlot)
        )
        result = await self._session.scalars(
            select(AppointmentSlot)
            .where(
                AppointmentSlot.provider_id == provider_id,
                AppointmentSlot.status == SlotStatus.OPEN,
                AppointmentSlot.start_utc > moment,
                AppointmentSlot.start_utc <= moment + timedelta(days=days),
                ~exists(taken),
            )
            .order_by(AppointmentSlot.start_utc)
        )
        return [
            SlotOffer(
                id=slot.id,
                provider_id=slot.provider_id,
                start_utc=slot.start_utc,
                end_utc=slot.end_utc,
            )
            for slot in result.all()
        ]

    async def _load(
        self, appointment_id: UUID
    ) -> tuple[Appointment, AppointmentSlot, Provider] | None:
        """Load one of the patient's own appointments with its slot and provider.

        Args:
            appointment_id: The appointment to load.

        Returns:
            The rows, or None if it is missing or another patient's.
        """
        result = await self._session.execute(
            select(Appointment, AppointmentSlot, Provider)
            .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .join(Provider, Provider.id == AppointmentSlot.provider_id)
            .where(Appointment.id == appointment_id, Appointment.patient_id == self._patient_id)
        )
        row = result.first()
        return None if row is None else (row[0], row[1], row[2])

    async def _find_by_key(self, idempotency_key: str) -> AppointmentRecord | None:
        """Return this patient's existing appointment for a submission key, if any.

        Args:
            idempotency_key: The client-supplied submission key.

        Returns:
            The already-created appointment, or None.
        """
        result = await self._session.execute(
            select(Appointment, AppointmentSlot, Provider)
            .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .join(Provider, Provider.id == AppointmentSlot.provider_id)
            .where(
                Appointment.idempotency_key == idempotency_key,
                Appointment.patient_id == self._patient_id,
            )
        )
        row = result.first()
        return None if row is None else _appointment_record(row[0], row[1], row[2])

    async def list_appointments(self) -> list[AppointmentRecord]:
        """Return the patient's appointments, soonest first.

        Returns:
            Every appointment they hold, including cancelled ones.
        """
        result = await self._session.execute(
            select(Appointment, AppointmentSlot, Provider)
            .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .join(Provider, Provider.id == AppointmentSlot.provider_id)
            .where(Appointment.patient_id == self._patient_id)
            .order_by(AppointmentSlot.start_utc.desc())
        )
        return [_appointment_record(row[0], row[1], row[2]) for row in result.all()]

    async def book(
        self,
        slot_id: UUID,
        *,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> BookingOutcome:
        """Book one open slot for the patient.

        Concurrency safety is the database's job: two callers racing for the last slot both
        reach the INSERT, and the partial unique index on live appointments rejects one of
        them. Checking availability first only improves the message in the common case — it
        is not what makes the guarantee hold (Core #12).

        Args:
            slot_id: The slot to book.
            idempotency_key: Client-supplied per submission; replaying it returns the
                original appointment instead of creating a second one (edge case #10).
            now: Current time, injected for tests.

        Returns:
            The appointment, or a refusal.
        """
        moment = now or datetime.now(UTC)

        if idempotency_key is not None:
            replayed = await self._find_by_key(idempotency_key)
            if replayed is not None:
                return BookingOutcome(appointment=replayed)

        slot = await self._session.scalar(
            select(AppointmentSlot).where(
                AppointmentSlot.id == slot_id,
                AppointmentSlot.status == SlotStatus.OPEN,
                AppointmentSlot.start_utc > moment,
            )
        )
        if slot is None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.SLOT_UNAVAILABLE, message=_SLOT_UNAVAILABLE_MESSAGE
                )
            )

        appointment = Appointment(
            slot_id=slot_id,
            patient_id=self._patient_id,
            status=AppointmentStatus.REQUESTED,
            idempotency_key=idempotency_key,
            booked_at=moment,
        )
        self._session.add(appointment)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            # Either the slot index or the submission-key index fired. Re-reading the key
            # tells them apart without parsing constraint names out of the driver error.
            if idempotency_key is not None:
                replayed = await self._find_by_key(idempotency_key)
                if replayed is not None:
                    return BookingOutcome(appointment=replayed)
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.SLOT_TAKEN, message=_SLOT_UNAVAILABLE_MESSAGE
                )
            )

        await self._record(AuditAction.APPOINTMENT_BOOKED, appointment.id)
        loaded = await self._load(appointment.id)
        if loaded is None:  # pragma: no cover - just committed it
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.NOT_FOUND, message="Appointment not found."
                )
            )
        return BookingOutcome(appointment=_appointment_record(*loaded))

    async def reschedule(
        self,
        appointment_id: UUID,
        new_slot_id: UUID,
        *,
        min_notice_hours: int,
        now: datetime | None = None,
    ) -> BookingOutcome:
        """Move a live appointment to another open slot.

        The move is a single UPDATE of `slot_id`, so the old slot is freed and the new one
        claimed in one statement — there is no window where the patient holds both or
        neither, and the partial unique index still arbitrates the target (Core #13).

        Args:
            appointment_id: The appointment to move.
            new_slot_id: The slot to move it to.
            min_notice_hours: Clinic notice policy.
            now: Current time, injected for tests.

        Returns:
            The updated appointment, or a refusal.
        """
        moment = now or datetime.now(UTC)
        loaded = await self._load(appointment_id)
        if loaded is None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.NOT_FOUND, message="Appointment not found."
                )
            )
        appointment, slot, _ = loaded

        if appointment.status not in _LIVE:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.INVALID_TRANSITION,
                    message=f"A {appointment.status.value} appointment cannot be moved.",
                )
            )
        if notice_shortfall(slot.start_utc, moment, min_notice_hours):
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.TOO_LATE,
                    message=(
                        f"Appointments cannot be changed within {min_notice_hours} hours of "
                        "the start time. Please call the clinic."
                    ),
                )
            )

        target = await self._session.scalar(
            select(AppointmentSlot).where(
                AppointmentSlot.id == new_slot_id,
                AppointmentSlot.status == SlotStatus.OPEN,
                AppointmentSlot.start_utc > moment,
            )
        )
        if target is None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.SLOT_UNAVAILABLE, message=_SLOT_UNAVAILABLE_MESSAGE
                )
            )

        try:
            await self._session.execute(
                update(Appointment)
                .where(
                    Appointment.id == appointment_id,
                    Appointment.patient_id == self._patient_id,
                    Appointment.status.in_(_LIVE),
                )
                .values(slot_id=new_slot_id)
            )
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.SLOT_TAKEN, message=_SLOT_UNAVAILABLE_MESSAGE
                )
            )

        await self._record(AuditAction.APPOINTMENT_RESCHEDULED, appointment_id)
        moved = await self._load(appointment_id)
        if moved is None:  # pragma: no cover - just updated it
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.NOT_FOUND, message="Appointment not found."
                )
            )
        return BookingOutcome(appointment=_appointment_record(*moved))

    async def cancel(
        self,
        appointment_id: UUID,
        *,
        min_notice_hours: int,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> BookingOutcome:
        """Cancel a live appointment, freeing its slot.

        The slot is freed implicitly: the partial unique index only covers live statuses, so
        leaving that set makes the slot bookable again with no second write to undo.

        Args:
            appointment_id: The appointment to cancel.
            min_notice_hours: Clinic notice policy.
            reason: Optional patient-supplied note.
            now: Current time, injected for tests.

        Returns:
            The cancelled appointment, or a refusal.
        """
        moment = now or datetime.now(UTC)
        loaded = await self._load(appointment_id)
        if loaded is None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.NOT_FOUND, message="Appointment not found."
                )
            )
        appointment, slot, _ = loaded

        refusal = check_transition(
            appointment.status, AppointmentStatus.CANCELLED, slot.start_utc, moment
        )
        if refusal is not None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.INVALID_TRANSITION, message=refusal.message
                )
            )
        if notice_shortfall(slot.start_utc, moment, min_notice_hours):
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.TOO_LATE,
                    message=(
                        f"Appointments cannot be cancelled within {min_notice_hours} hours of "
                        "the start time. Please call the clinic."
                    ),
                )
            )

        await self._session.execute(
            update(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.patient_id == self._patient_id,
                Appointment.status.in_(_LIVE),
            )
            .values(status=AppointmentStatus.CANCELLED, cancelled_at=moment, reason=reason)
        )
        await self._session.commit()
        await self._record(AuditAction.APPOINTMENT_CANCELLED, appointment_id)

        cancelled = await self._load(appointment_id)
        if cancelled is None:  # pragma: no cover - just updated it
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.NOT_FOUND, message="Appointment not found."
                )
            )
        return BookingOutcome(appointment=_appointment_record(*cancelled))


class ProviderScope:
    """A staff member's view of exactly one provider's schedule.

    The provider id comes from the caller's staff row, never from the request, so every
    query here is already constrained to the clinic they work for.
    """

    def __init__(
        self,
        session: AsyncSession,
        provider_id: UUID,
        *,
        actor_id: UUID,
        request_id: str | None = None,
    ) -> None:
        """Initialise the scope.

        Args:
            session: Request-scoped database session.
            provider_id: The provider this scope may manage.
            actor_id: The staff member acting, recorded in the audit log.
            request_id: Correlates audit entries with the request log.
        """
        self._session = session
        self._provider_id = provider_id
        self._actor_id = actor_id
        self._request_id = request_id

    async def _record(self, action: AuditAction, resource_type: str, resource_id: UUID) -> None:
        """Append an audit entry for a schedule change.

        Args:
            action: What was done.
            resource_type: The kind of resource touched.
            resource_id: Which resource.
        """
        self._session.add(
            AuditLogEntry(
                actor_type=AuditActorType.STAFF,
                actor_id=self._actor_id,
                action=action.value,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=self._request_id,
            )
        )
        await self._session.commit()

    async def _timezone(self) -> str:
        """Return the provider's IANA timezone.

        Returns:
            The zone availability rules are expressed in.

        Raises:
            ValueError: If the provider row has vanished.
        """
        zone = await self._session.scalar(
            select(Provider.timezone).where(Provider.id == self._provider_id)
        )
        if zone is None:
            raise ValueError("provider not found")
        return zone

    async def list_rules(self) -> list[AvailabilityRuleRecord]:
        """Return the provider's working-hours rules.

        Returns:
            Rules ordered by weekday then start time.
        """
        result = await self._session.scalars(
            select(AvailabilityRule)
            .where(AvailabilityRule.provider_id == self._provider_id)
            .order_by(AvailabilityRule.weekday, AvailabilityRule.start_local)
        )
        return [
            AvailabilityRuleRecord(
                id=rule.id,
                weekday=rule.weekday,
                start_local=rule.start_local,
                end_local=rule.end_local,
                slot_minutes=rule.slot_minutes,
            )
            for rule in result.all()
        ]

    async def list_blocks(self) -> list[BlockedRangeRecord]:
        """Return the provider's blocked ranges.

        Returns:
            Blocks in chronological order.
        """
        result = await self._session.scalars(
            select(BlockedRange)
            .where(BlockedRange.provider_id == self._provider_id)
            .order_by(BlockedRange.start_utc)
        )
        return [
            BlockedRangeRecord(
                id=block.id,
                start_utc=block.start_utc,
                end_utc=block.end_utc,
                reason=block.reason,
            )
            for block in result.all()
        ]

    async def _live_appointment_starts(self, slot_ids: list[UUID]) -> list[datetime]:
        """Return the start times of any live appointments among the given slots.

        Args:
            slot_ids: Slots about to be withdrawn.

        Returns:
            Start instants of the slots that are actually booked.
        """
        if not slot_ids:
            return []
        result = await self._session.scalars(
            select(AppointmentSlot.start_utc)
            .join(Appointment, Appointment.slot_id == AppointmentSlot.id)
            .where(AppointmentSlot.id.in_(slot_ids), Appointment.status.in_(_LIVE))
            .order_by(AppointmentSlot.start_utc)
        )
        return list(result.all())

    async def replace_rules(
        self,
        rules: list[SlotRule],
        *,
        horizon_days: int,
        now: datetime | None = None,
    ) -> AvailabilityOutcome:
        """Replace the provider's working hours and re-materialise their slots.

        Slots are rows, not a computed view, so a schedule change has to reconcile them.
        Future slots the new rules no longer cover are withdrawn — unless one is booked, in
        which case the whole edit is refused rather than silently deleting a patient's
        appointment (edge case #8). Refusing keeps the two sides consistent: a partially
        applied edit would leave working hours that disagree with the slots on offer.

        Args:
            rules: The complete new set of weekday rules.
            horizon_days: How far ahead to materialise slots.
            now: Current time, injected for tests.

        Returns:
            The stored rules and slot counts, or a refusal naming the clash.
        """
        moment = now or datetime.now(UTC)
        timezone = await self._timezone()

        horizon_end = (moment + timedelta(days=horizon_days)).date()
        wanted: set[datetime] = set()
        windows: dict[datetime, datetime] = {}
        for rule in rules:
            for window in generate_slots(rule, moment.date(), horizon_end, timezone):
                if window.start_utc > moment:
                    wanted.add(window.start_utc)
                    windows[window.start_utc] = window.end_utc

        existing = await self._session.scalars(
            select(AppointmentSlot).where(
                AppointmentSlot.provider_id == self._provider_id,
                AppointmentSlot.start_utc > moment,
            )
        )
        stale = [slot for slot in existing.all() if slot.start_utc not in wanted]

        booked_starts = await self._live_appointment_starts([slot.id for slot in stale])
        if booked_starts:
            listed = ", ".join(start.isoformat() for start in booked_starts[:3])
            return AvailabilityOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.BOOKED_SLOT_CONFLICT,
                    message=(
                        f"{len(booked_starts)} booked appointment(s) fall outside the new "
                        f"hours ({listed}). Move or cancel them first."
                    ),
                )
            )

        if stale:
            await self._session.execute(
                delete(AppointmentSlot).where(AppointmentSlot.id.in_([slot.id for slot in stale]))
            )

        await self._session.execute(
            delete(AvailabilityRule).where(AvailabilityRule.provider_id == self._provider_id)
        )
        for rule in rules:
            self._session.add(
                AvailabilityRule(
                    provider_id=self._provider_id,
                    weekday=rule.weekday,
                    start_local=rule.start_local,
                    end_local=rule.end_local,
                    slot_minutes=rule.slot_minutes,
                )
            )

        created = 0
        if wanted:
            # ON CONFLICT DO NOTHING against the (provider, start) unique constraint makes
            # re-materialising idempotent, so re-saving unchanged hours is a no-op rather
            # than an error or a duplicate.
            # RETURNING yields only the rows that actually inserted, so the count reflects
            # new slots rather than rows offered — `rowcount` would not distinguish them.
            inserted = await self._session.scalars(
                pg_insert(AppointmentSlot)
                .values(
                    [
                        {
                            "provider_id": self._provider_id,
                            "start_utc": start,
                            "end_utc": windows[start],
                            "status": SlotStatus.OPEN,
                        }
                        for start in sorted(wanted)
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_appointment_slots_provider_id_start_utc")
                .returning(AppointmentSlot.id)
            )
            created = len(inserted.all())

        await self._session.commit()
        await self._record(AuditAction.AVAILABILITY_CHANGED, "provider", self._provider_id)

        return AvailabilityOutcome(
            rules=await self.list_rules(),
            slots_created=created,
            slots_removed=len(stale),
        )

    async def add_block(
        self,
        start_utc: datetime,
        end_utc: datetime,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> AvailabilityOutcome:
        """Mark a period unavailable and withdraw the free slots inside it.

        Args:
            start_utc: When the block starts.
            end_utc: When it ends.
            reason: Optional note.
            now: Current time, injected for tests.

        Returns:
            The slot count withdrawn, or a refusal if a booked slot falls inside.
        """
        moment = now or datetime.now(UTC)
        overlapping = await self._session.scalars(
            select(AppointmentSlot).where(
                AppointmentSlot.provider_id == self._provider_id,
                AppointmentSlot.status == SlotStatus.OPEN,
                AppointmentSlot.start_utc < end_utc,
                AppointmentSlot.end_utc > start_utc,
                AppointmentSlot.start_utc > moment,
            )
        )
        slots = list(overlapping.all())

        booked_starts = await self._live_appointment_starts([slot.id for slot in slots])
        if booked_starts:
            listed = ", ".join(start.isoformat() for start in booked_starts[:3])
            return AvailabilityOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.BOOKED_SLOT_CONFLICT,
                    message=(
                        f"{len(booked_starts)} booked appointment(s) fall inside that range "
                        f"({listed}). Move or cancel them first."
                    ),
                )
            )

        block = BlockedRange(
            provider_id=self._provider_id, start_utc=start_utc, end_utc=end_utc, reason=reason
        )
        self._session.add(block)
        if slots:
            # Marked blocked rather than deleted: the slot keeps its identity, so unblocking
            # later restores the same times instead of minting new ids.
            await self._session.execute(
                update(AppointmentSlot)
                .where(AppointmentSlot.id.in_([slot.id for slot in slots]))
                .values(status=SlotStatus.BLOCKED)
            )
        await self._session.commit()
        await self._record(AuditAction.AVAILABILITY_CHANGED, "provider", self._provider_id)

        return AvailabilityOutcome(rules=await self.list_rules(), slots_removed=len(slots))

    async def list_appointments(self, *, days: int = 30) -> list[AppointmentRecord]:
        """Return the provider's upcoming appointments.

        Args:
            days: How far ahead to look.

        Returns:
            Appointments in chronological order.
        """
        moment = datetime.now(UTC)
        result = await self._session.execute(
            select(Appointment, AppointmentSlot, Provider)
            .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .join(Provider, Provider.id == AppointmentSlot.provider_id)
            .where(
                AppointmentSlot.provider_id == self._provider_id,
                AppointmentSlot.start_utc <= moment + timedelta(days=days),
            )
            .order_by(AppointmentSlot.start_utc)
        )
        return [_appointment_record(row[0], row[1], row[2]) for row in result.all()]

    async def change_status(
        self,
        appointment_id: UUID,
        target: AppointmentStatus,
        *,
        now: datetime | None = None,
    ) -> BookingOutcome:
        """Move one of the provider's appointments to a new status (Core #14).

        Args:
            appointment_id: The appointment to change.
            target: The status to move to.
            now: Current time, injected for tests.

        Returns:
            The updated appointment, or a refusal.
        """
        moment = now or datetime.now(UTC)
        result = await self._session.execute(
            select(Appointment, AppointmentSlot, Provider)
            .join(AppointmentSlot, AppointmentSlot.id == Appointment.slot_id)
            .join(Provider, Provider.id == AppointmentSlot.provider_id)
            .where(
                Appointment.id == appointment_id,
                AppointmentSlot.provider_id == self._provider_id,
            )
        )
        row = result.first()
        if row is None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.NOT_FOUND, message="Appointment not found."
                )
            )
        appointment, slot, provider = row

        refusal = check_transition(appointment.status, target, slot.start_utc, moment)
        if refusal is not None:
            return BookingOutcome(
                refusal=ScheduleRefusal(
                    code=ScheduleRefusalCode.INVALID_TRANSITION, message=refusal.message
                )
            )

        # The cancelled_at check constraint ties the timestamp to the status, so both move
        # together or the write is rejected.
        values: dict[str, object] = {"status": target}
        values["cancelled_at"] = moment if target is AppointmentStatus.CANCELLED else None

        await self._session.execute(
            update(Appointment).where(Appointment.id == appointment_id).values(**values)
        )
        await self._session.commit()
        await self._record(AuditAction.APPOINTMENT_STATUS_CHANGED, "appointment", appointment_id)

        await self._session.refresh(appointment)
        return BookingOutcome(appointment=_appointment_record(appointment, slot, provider))
