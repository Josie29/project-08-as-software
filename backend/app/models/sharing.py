import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ShareResourceType, pg_enum


class ShareLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A time-limited, revocable link granting access to one image or report.

    Only the token's SHA-256 hash is stored, so a database dump holds no working links.
    `resource_id` cannot be a foreign key — it targets a different table per
    `resource_type`.
    """

    __tablename__ = "share_links"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)

    resource_type: Mapped[ShareResourceType] = mapped_column(
        pg_enum(ShareResourceType, "share_resource_type"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Scopes revocation and the patient's active-links list.
    created_by_patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    recipient_email: Mapped[str] = mapped_column(Text, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        Index("ix_share_links_created_by_patient_id", "created_by_patient_id"),
        Index("ix_share_links_resource_type_resource_id", "resource_type", "resource_id"),
    )
