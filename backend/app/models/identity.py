import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import StaffRole, pg_enum


class Patient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A clinical patient record, seeded before any portal signup.

    `auth_user_id` links to the portal login once identity is verified; null until then.
    """

    __tablename__ = "patients"

    # Printed on clinic paperwork; the first verification factor.
    account_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)

    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)

    # No FK into auth.users: Supabase owns that schema and CI's Postgres lacks it.
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)


class Provider(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A clinician patients book with. Purely clinical — logins live on `staff`."""

    __tablename__ = "providers"

    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    specialty: Mapped[str | None] = mapped_column(Text)
    # IANA zone. Availability is local wall-clock in this zone, materialised to UTC slots.
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="America/New_York")


class Staff(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A non-patient portal login, scoped to one provider.

    A clinician points at their own provider record; an admin at the one they support.
    """

    __tablename__ = "staff"

    # Nullable like patients.auth_user_id: a staff member exists as an employment record
    # before their login is provisioned, and after it is revoked.
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[StaffRole] = mapped_column(pg_enum(StaffRole, "staff_role"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("ix_staff_provider_id", "provider_id"),)


class IdentityVerification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A successful ID + date-of-birth match, valid for a limited window.

    A row rather than a session flag so it survives token refresh and can be revoked.
    """

    __tablename__ = "identity_verifications"

    auth_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_identity_verifications_patient_id", "patient_id"),
        # "Is this caller verified right now" runs on every PHI read.
        Index("ix_identity_verifications_auth_user_id_expires_at", "auth_user_id", "expires_at"),
    )


class IdentityAttempt(Base, TimestampMixin):
    """One identity-verification attempt, successful or not.

    Persisted so lockout survives deploys and holds across API instances. The submitted
    date of birth is deliberately not stored — a failed attempt is often someone else's.
    """

    __tablename__ = "identity_attempts"

    # Never addressed by URL, so a sequential key is fine.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    auth_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    submitted_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        # Lockout counts recent failures per user.
        Index("ix_identity_attempts_auth_user_id_created_at", "auth_user_id", "created_at"),
    )
