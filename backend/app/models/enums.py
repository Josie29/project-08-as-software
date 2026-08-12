from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    """Return the string values of an enum, in declaration order.

    Args:
        enum_class: The enum to read.

    Returns:
        Each member's value.
    """
    return [member.value for member in enum_class]


def pg_enum(enum_type: type[StrEnum], name: str) -> SAEnum:
    """Build a native Postgres enum column type from a Python StrEnum.

    `values_callable` is required: SQLAlchemy otherwise persists the member *names*
    rather than their values, so `AppointmentStatus.NO_SHOW` would be stored as
    `NO_SHOW` instead of `no_show`.

    Args:
        enum_type: The Python enum backing the column.
        name: Name of the Postgres type to create.

    Returns:
        A SQLAlchemy `Enum` bound to a native Postgres enum type.
    """
    return SAEnum(enum_type, name=name, native_enum=True, values_callable=_enum_values)


class StaffRole(StrEnum):
    """Non-patient portal roles. Admins are scoped to the provider they support."""

    PROVIDER = "provider"
    ADMIN = "admin"


class StudyStatus(StrEnum):
    """Lifecycle of an imaging study. Only COMPLETED exposes images (Core #3)."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReportStatus(StrEnum):
    """Report lifecycle. PRELIMINARY is never visible to a patient (Core #7)."""

    PRELIMINARY = "preliminary"
    FINAL = "final"
    AMENDED = "amended"


class FrameIntegrity(StrEnum):
    """Per-frame health, so a partial manifest degrades gracefully (edge case #2)."""

    OK = "ok"
    MISSING = "missing"
    CORRUPT = "corrupt"


class ShareResourceType(StrEnum):
    """What a share link points at. Images and reports share one link mechanism."""

    IMAGE = "image"
    REPORT = "report"


class SlotStatus(StrEnum):
    """Whether a generated slot is offerable. BLOCKED covers provider time off."""

    OPEN = "open"
    BLOCKED = "blocked"


class AppointmentStatus(StrEnum):
    """Appointment lifecycle (Core #14).

    REQUESTED and CONFIRMED are the live states the partial unique index keys off.
    """

    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


#: Statuses that occupy a slot. A slot is rebookable once an appointment leaves this set.
LIVE_APPOINTMENT_STATUSES: tuple[AppointmentStatus, ...] = (
    AppointmentStatus.REQUESTED,
    AppointmentStatus.CONFIRMED,
)


class ReminderKind(StrEnum):
    """Which reminder a send record represents; part of the idempotency key."""

    PRE_VISIT_24H = "pre_visit_24h"


class ReminderStatus(StrEnum):
    """Outcome of a reminder dispatch attempt."""

    SENT = "sent"
    FAILED = "failed"


class AuditActorType(StrEnum):
    """Who performed an audited action.

    SHARE_LINK covers reads by a link recipient with no signed-in portal user.
    """

    PATIENT = "patient"
    STAFF = "staff"
    SHARE_LINK = "share_link"
    SYSTEM = "system"


class AuditAction(StrEnum):
    """Audited actions. Stored as text so the set can grow without a migration."""

    IDENTITY_VERIFIED = "identity_verified"
    IDENTITY_FAILED = "identity_failed"
    IMAGE_VIEWED = "image_viewed"
    IMAGE_ACCESS_DENIED = "image_access_denied"
    STUDY_ACCESS_DENIED = "study_access_denied"
    CINE_VIEWED = "cine_viewed"
    REPORT_VIEWED = "report_viewed"
    REPORT_ACCESS_DENIED = "report_access_denied"
    SHARE_LINK_CREATED = "share_link_created"
    SHARE_LINK_USED = "share_link_used"
    SHARE_LINK_REVOKED = "share_link_revoked"
    SHARE_LINK_DENIED = "share_link_denied"
    APPOINTMENT_BOOKED = "appointment_booked"
    APPOINTMENT_RESCHEDULED = "appointment_rescheduled"
    APPOINTMENT_CANCELLED = "appointment_cancelled"
    APPOINTMENT_STATUS_CHANGED = "appointment_status_changed"
    AVAILABILITY_CHANGED = "availability_changed"
