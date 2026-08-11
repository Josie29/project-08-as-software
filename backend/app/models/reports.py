import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReportStatus, pg_enum


class Report(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A radiology report for a study.

    Body is text in Postgres, not object storage: reports are small and must render
    in-browser. `patient_id` is denormalised so the ownership check needs no join.
    """

    __tablename__ = "reports"

    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(
        pg_enum(ReportStatus, "report_status"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL")
    )

    __table_args__ = (
        Index("ix_reports_study_id", "study_id"),
        Index("ix_reports_signed_by_provider_id", "signed_by_provider_id"),
        # Patients only ever see signed reports.
        Index(
            "ix_reports_patient_id_signed",
            "patient_id",
            postgresql_where=text(
                f"status IN ('{ReportStatus.FINAL.value}', '{ReportStatus.AMENDED.value}')"
            ),
        ),
        # Signed status and signing timestamp must agree, or an unsigned report could be
        # served to the patient as final.
        CheckConstraint(
            "(status = 'preliminary' AND signed_at IS NULL)"
            " OR (status IN ('final', 'amended') AND signed_at IS NOT NULL)",
            name="reports_signed_state_consistent",
        ),
    )
