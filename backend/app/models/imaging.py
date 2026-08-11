import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FrameIntegrity, StudyStatus, pg_enum

#: Ceiling from Core #4 — a cine clip references up to 100 sequentially ordered frames.
MAX_CINE_FRAMES = 100


class Study(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One ultrasound visit and the images it produced.

    `patient_id` is the ownership root for every image, clip, and frame beneath it.
    """

    __tablename__ = "studies"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("providers.id", ondelete="SET NULL")
    )
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[StudyStatus] = mapped_column(
        pg_enum(StudyStatus, "study_status"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_studies_provider_id", "provider_id"),
        # Backs the patient's study list, excluding future and cancelled visits.
        Index(
            "ix_studies_patient_id_performed_at_completed",
            "patient_id",
            "performed_at",
            postgresql_where=text(f"status = '{StudyStatus.COMPLETED.value}'"),
        ),
    )


class Image(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single static ultrasound image; bytes live in object storage."""

    __tablename__ = "images"

    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Separate small object for thumbnail-first loading (Stretch #16).
    thumbnail_path: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("study_id", "sequence", name="uq_images_study_id_sequence"),
        CheckConstraint("width > 0 AND height > 0", name="images_positive_dimensions"),
        CheckConstraint("byte_size >= 0", name="images_non_negative_size"),
    )


class CineClip(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A multi-frame cine loop belonging to a study."""

    __tablename__ = "cine_clips"

    study_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("studies.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Compared against the frame row count to detect a partial manifest (edge case #2).
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    default_fps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="12")
    manifest_path: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("study_id", "sequence", name="uq_cine_clips_study_id_sequence"),
        CheckConstraint(
            f"frame_count BETWEEN 1 AND {MAX_CINE_FRAMES}",
            name="cine_clips_frame_count_within_limit",
        ),
        CheckConstraint("default_fps BETWEEN 1 AND 60", name="cine_clips_default_fps_playable"),
    )


class CineFrame(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One frame of a cine clip.

    Rows rather than a JSON blob so ordering is constrained and damage is queryable.
    """

    __tablename__ = "cine_frames"

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cine_clips.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    integrity: Mapped[FrameIntegrity] = mapped_column(
        pg_enum(FrameIntegrity, "frame_integrity"),
        nullable=False,
        server_default=FrameIntegrity.OK.value,
    )

    __table_args__ = (
        # A duplicate sequence would silently reorder playback.
        UniqueConstraint("clip_id", "sequence", name="uq_cine_frames_clip_id_sequence"),
        CheckConstraint(
            f"sequence BETWEEN 0 AND {MAX_CINE_FRAMES - 1}",
            name="cine_frames_sequence_within_limit",
        ),
    )
