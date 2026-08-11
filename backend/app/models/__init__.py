"""ORM models.

Each model module must be imported here so that `Base.metadata` is fully populated
before Alembic autogenerate runs — a model that is never imported is silently absent
from generated migrations.
"""

from app.db import Base
from app.models.audit import AuditLogEntry, ReminderSend
from app.models.identity import (
    IdentityAttempt,
    IdentityVerification,
    Patient,
    Provider,
    Staff,
)
from app.models.imaging import CineClip, CineFrame, Image, Study
from app.models.reports import Report
from app.models.scheduling import (
    Appointment,
    AppointmentSlot,
    AvailabilityRule,
    BlockedRange,
)
from app.models.sharing import ShareLink

__all__ = [
    "Appointment",
    "AppointmentSlot",
    "AuditLogEntry",
    "AvailabilityRule",
    "Base",
    "BlockedRange",
    "CineClip",
    "CineFrame",
    "IdentityAttempt",
    "IdentityVerification",
    "Image",
    "Patient",
    "Provider",
    "ReminderSend",
    "Report",
    "ShareLink",
    "Staff",
    "Study",
]
