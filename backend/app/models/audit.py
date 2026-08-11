import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AuditActorType, ReminderKind, ReminderStatus, pg_enum


class AuditLogEntry(Base):
    """Append-only record of one PHI access or booking change.

    Carries no PHI — actor, action, target reference and timestamp only. Append-only is
    enforced by a trigger in the initial migration, not by convention.
    """

    __tablename__ = "audit_log"

    # Never addressed by URL; a monotonic key gives ordering and insert locality.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    actor_type: Mapped[AuditActorType] = mapped_column(
        pg_enum(AuditActorType, "audit_actor_type"), nullable=False
    )
    # Null for SYSTEM actors such as the reminder job.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Text, not an enum: this set grows with every PHI route and needs no migration.
    action: Mapped[str] = mapped_column(Text, nullable=False)

    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Correlates with the structured application log.
    request_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # "Everything that touched this record" — the compliance-review query.
        Index("ix_audit_log_resource_type_resource_id", "resource_type", "resource_id"),
        # "Everything this actor did", newest first.
        Index(
            "ix_audit_log_actor_type_actor_id_occurred_at", "actor_type", "actor_id", "occurred_at"
        ),
    )


class ReminderSend(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A record that one reminder was dispatched for one appointment.

    The unique constraint is the idempotency mechanism: overlapping or repeated runs of
    the reminder job cannot double-send. Correctness comes from it, not from timing.
    """

    __tablename__ = "reminder_sends"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ReminderKind] = mapped_column(
        pg_enum(ReminderKind, "reminder_kind"), nullable=False
    )
    status: Mapped[ReminderStatus] = mapped_column(
        pg_enum(ReminderStatus, "reminder_status"), nullable=False
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Traces a delivery complaint back to a send.
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("appointment_id", "kind", name="uq_reminder_sends_appointment_id_kind"),
    )
