import uuid
from datetime import datetime, time

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    LIVE_APPOINTMENT_STATUSES,
    AppointmentStatus,
    SlotStatus,
    pg_enum,
)

#: Slot-occupying statuses as a SQL literal, derived from the enum so they cannot diverge.
_LIVE_STATUS_SQL = ", ".join(f"'{status.value}'" for status in LIVE_APPOINTMENT_STATUSES)


class AvailabilityRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A provider's recurring working hours for one weekday.

    Times are local wall-clock in the provider's timezone, not UTC, so "9-5" survives DST.
    """

    __tablename__ = "availability_rules"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
    )
    # ISO-8601 weekday: 1 = Monday through 7 = Sunday.
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_local: Mapped[time] = mapped_column(Time, nullable=False)
    end_local: Mapped[time] = mapped_column(Time, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_availability_rules_provider_id", "provider_id"),
        CheckConstraint("weekday BETWEEN 1 AND 7", name="availability_rules_weekday_iso"),
        CheckConstraint("end_local > start_local", name="availability_rules_end_after_start"),
        CheckConstraint(
            "slot_minutes BETWEEN 5 AND 240", name="availability_rules_slot_minutes_sane"
        ),
    )


class BlockedRange(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An explicit period a provider is unavailable, overriding their working hours."""

    __tablename__ = "blocked_ranges"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
    )
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_blocked_ranges_provider_id_start_utc", "provider_id", "start_utc"),
        CheckConstraint("end_utc > start_utc", name="blocked_ranges_end_after_start"),
    )


class AppointmentSlot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A materialised bookable slot at an exact instant.

    Rows rather than computed, so a slot is a real object a constraint can protect.
    """

    __tablename__ = "appointment_slots"

    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
    )
    start_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[SlotStatus] = mapped_column(
        pg_enum(SlotStatus, "slot_status"), nullable=False, server_default=SlotStatus.OPEN.value
    )

    __table_args__ = (
        # Also makes slot generation idempotent.
        UniqueConstraint(
            "provider_id", "start_utc", name="uq_appointment_slots_provider_id_start_utc"
        ),
        # Backs slot discovery.
        Index(
            "ix_appointment_slots_provider_id_start_utc_open",
            "provider_id",
            "start_utc",
            postgresql_where=text(f"status = '{SlotStatus.OPEN.value}'"),
        ),
        CheckConstraint("end_utc > start_utc", name="appointment_slots_end_after_start"),
    )


class Appointment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A patient's booking of a slot.

    Concurrency safety comes from the partial unique index below, not application locking.
    """

    __tablename__ = "appointments"

    # RESTRICT so an availability edit cannot delete a booked slot (edge case #8).
    slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointment_slots.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        pg_enum(AppointmentStatus, "appointment_status"), nullable=False
    )

    # Client-supplied per attempt; dedupes double-clicks and retries (edge case #10).
    idempotency_key: Mapped[str | None] = mapped_column(Text)

    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # The no-double-booking guarantee. Scoped to live statuses so cancelling frees
        # the slot; a plain UNIQUE(slot_id) would wedge it forever.
        Index(
            "uq_appointments_slot_id_live",
            "slot_id",
            unique=True,
            postgresql_where=text(f"status IN ({_LIVE_STATUS_SQL})"),
        ),
        Index(
            "uq_appointments_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_appointments_patient_id", "patient_id"),
        # Retention and audit both rely on cancelled rows carrying a cancellation time.
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="appointments_cancelled_state_consistent",
        ),
    )
