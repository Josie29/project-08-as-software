from datetime import UTC, datetime
from enum import StrEnum, auto
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLogEntry
from app.models.enums import AuditAction, AuditActorType, ReportStatus, ShareResourceType
from app.models.imaging import Image
from app.models.reports import Report
from app.models.sharing import ShareLink
from app.services.sharing import MAX_OPENS, hash_token

logger = structlog.get_logger(__name__)


class ShareOutcome(StrEnum):
    """Why a share link did or did not resolve."""

    OK = auto()
    NOT_FOUND = auto()
    EXPIRED = auto()
    REVOKED = auto()
    EXHAUSTED = auto()


class ResolvedShare(BaseModel):
    """A resolved link and the resource it points at."""

    outcome: ShareOutcome
    share_id: UUID | None = None
    resource_type: ShareResourceType | None = None
    storage_path: str | None = None
    report_title: str | None = None
    report_body: str | None = None


async def resolve_share(
    session: AsyncSession, token: str, *, request_id: str | None = None
) -> ResolvedShare:
    """Resolve a share token to the resource it grants access to.

    This is the only unauthenticated path to protected health information in the system,
    so it is deliberately narrow: the token is the sole input, the resource is derived from
    the stored row, and nothing about the request can redirect it elsewhere. An endpoint
    that accepted a resource id alongside the token would let a valid link be pointed at
    someone else's record.

    Every outcome is audited, including refusals — a link being probed after expiry is
    exactly the event a review needs to see.

    Args:
        session: Database session.
        token: The raw token from the URL.
        request_id: Correlates the audit entry with the request log.

    Returns:
        The outcome, carrying resource details only when access is granted.
    """
    link = (
        await session.execute(select(ShareLink).where(ShareLink.token_hash == hash_token(token)))
    ).scalar_one_or_none()

    if link is None:
        # Nothing to attribute this to beyond the request itself; a guessed token has no
        # owner. Logged so a burst of them is visible.
        await _audit(session, None, AuditAction.SHARE_LINK_DENIED, None, request_id)
        return ResolvedShare(outcome=ShareOutcome.NOT_FOUND)

    if link.revoked_at is not None:
        await _audit(
            session, link.created_by_patient_id, AuditAction.SHARE_LINK_DENIED, link.id, request_id
        )
        return ResolvedShare(outcome=ShareOutcome.REVOKED, share_id=link.id)

    if link.expires_at <= datetime.now(UTC):
        await _audit(
            session, link.created_by_patient_id, AuditAction.SHARE_LINK_DENIED, link.id, request_id
        )
        return ResolvedShare(outcome=ShareOutcome.EXPIRED, share_id=link.id)

    if link.access_count >= MAX_OPENS:
        await _audit(
            session, link.created_by_patient_id, AuditAction.SHARE_LINK_DENIED, link.id, request_id
        )
        return ResolvedShare(outcome=ShareOutcome.EXHAUSTED, share_id=link.id)

    resolved = await _load_resource(session, link)
    if resolved is None:
        await _audit(
            session, link.created_by_patient_id, AuditAction.SHARE_LINK_DENIED, link.id, request_id
        )
        return ResolvedShare(outcome=ShareOutcome.NOT_FOUND, share_id=link.id)

    await session.execute(
        update(ShareLink)
        .where(ShareLink.id == link.id)
        .values(access_count=ShareLink.access_count + 1, last_accessed_at=datetime.now(UTC))
    )
    await _audit(
        session, link.created_by_patient_id, AuditAction.SHARE_LINK_USED, link.id, request_id
    )
    return resolved


async def _load_resource(session: AsyncSession, link: ShareLink) -> ResolvedShare | None:
    """Load the resource a link points at.

    Args:
        session: Database session.
        link: The resolved link.

    Returns:
        The populated outcome, or None if the resource has gone or is no longer shareable.
    """
    if link.resource_type is ShareResourceType.IMAGE:
        image = (
            await session.execute(select(Image).where(Image.id == link.resource_id))
        ).scalar_one_or_none()
        if image is None:
            return None
        return ResolvedShare(
            outcome=ShareOutcome.OK,
            share_id=link.id,
            resource_type=ShareResourceType.IMAGE,
            storage_path=image.storage_path,
        )

    report = (
        await session.execute(
            select(Report).where(
                Report.id == link.resource_id,
                # Re-checked at resolution, not just at issuance: a report that has been
                # pulled back to preliminary must stop being served through an existing
                # link rather than remaining readable because the link predates the change.
                Report.status.in_((ReportStatus.FINAL, ReportStatus.AMENDED)),
            )
        )
    ).scalar_one_or_none()
    if report is None:
        return None
    return ResolvedShare(
        outcome=ShareOutcome.OK,
        share_id=link.id,
        resource_type=ShareResourceType.REPORT,
        report_title=report.title,
        report_body=report.body,
    )


async def _audit(
    session: AsyncSession,
    patient_id: UUID | None,
    action: AuditAction,
    share_id: UUID | None,
    request_id: str | None,
) -> None:
    """Record a share-link event.

    Args:
        session: Database session.
        patient_id: The patient whose link it is, when known.
        action: What happened.
        share_id: The link involved, when known.
        request_id: Correlates with the request log.
    """
    session.add(
        AuditLogEntry(
            actor_type=AuditActorType.SHARE_LINK,
            actor_id=patient_id,
            action=action.value,
            resource_type="share_link",
            resource_id=share_id,
            request_id=request_id,
        )
    )
    await session.commit()
