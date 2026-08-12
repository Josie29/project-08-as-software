from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLogEntry
from app.models.enums import (
    AuditAction,
    AuditActorType,
    FrameIntegrity,
    ReportStatus,
    ShareResourceType,
    StudyStatus,
)
from app.models.identity import Patient
from app.models.imaging import CineClip, CineFrame, Image, Study
from app.models.reports import Report
from app.models.sharing import ShareLink
from app.services.sharing import hash_token, mint_token

logger = structlog.get_logger(__name__)


class StudySummary(BaseModel):
    """A study as the patient sees it in their list."""

    id: UUID
    performed_at: datetime
    description: str | None
    image_count: int


class ImageSummary(BaseModel):
    """Image metadata, without any bytes."""

    id: UUID
    sequence: int
    width: int
    height: int
    has_thumbnail: bool


class PatientProfile(BaseModel):
    """The patient's own details, as shown in their portal header."""

    display_name: str
    account_id: str
    # Masked at the source rather than in the UI: an unmasked date of birth should never
    # cross the wire when only a confirmation cue is needed.
    date_of_birth_masked: str


#: The only report states a patient may see. A preliminary read belongs to the care team
#: until a radiologist signs it (Core #7), so it is excluded in SQL rather than filtered
#: out later — there is then no code path that could serve one.
PATIENT_VISIBLE_REPORT_STATUSES = (ReportStatus.FINAL, ReportStatus.AMENDED)


class ReportSummary(BaseModel):
    """A report as it appears in the patient's list."""

    id: UUID
    study_id: UUID
    title: str
    status: ReportStatus
    signed_at: datetime | None


class ReportDetail(BaseModel):
    """A full report, including its body."""

    id: UUID
    study_id: UUID
    title: str
    status: ReportStatus
    body: str
    signed_at: datetime | None


class ShareRecord(BaseModel):
    """A share link as the patient sees it. Never carries the token itself."""

    id: UUID
    resource_type: ShareResourceType
    resource_id: UUID
    recipient_email: str
    expires_at: datetime
    revoked_at: datetime | None
    access_count: int


class MintedShare(BaseModel):
    """A newly created link. The raw token exists here and in the email, nowhere else."""

    record: ShareRecord
    token: str


class ImageAccess(BaseModel):
    """An authorised reference to one image's stored objects."""

    id: UUID
    storage_path: str
    thumbnail_path: str | None


class CineClipSummary(BaseModel):
    """A cine clip as it appears alongside a study's stills."""

    id: UUID
    study_id: UUID
    sequence: int
    frame_count: int
    default_fps: int
    available_frame_count: int


class CineFrameEntry(BaseModel):
    """One entry in a clip's manifest.

    `available` is resolved from the stored integrity flag rather than discovered when the
    player asks for the bytes, so a damaged clip is a known shape up front instead of a
    404 mid-playback (edge case #2).
    """

    sequence: int
    available: bool


class CineManifest(BaseModel):
    """The ordered frame list for one clip."""

    id: UUID
    study_id: UUID
    frame_count: int
    default_fps: int
    frames: list[CineFrameEntry]


class FrameAccess(BaseModel):
    """An authorised reference to one cine frame's stored object."""

    clip_id: UUID
    sequence: int
    storage_path: str


class PatientScope:
    """The only route to patient health information.

    Constructed solely by the verified-patient dependency, so a handler cannot reach PHI
    without having passed both the token check and the identity check.

    Every query filters on the scope's own `patient_id` inside the SQL rather than checking
    ownership after loading a row. A forgotten post-hoc check is the classic source of
    cross-patient leaks; there is nothing to forget if the row never loads.

    Methods return `None` for a resource that is missing *or* owned by someone else. The
    caller turns both into 404: distinguishing them would confirm that an id exists, which
    is exactly the oracle the adversarial id-walking test looks for.
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
            patient_id: The verified patient this scope may read.
            request_id: Correlates audit entries with the request log.
        """
        self._session = session
        self._patient_id = patient_id
        self._request_id = request_id

    async def _record(self, action: AuditAction, resource_type: str, resource_id: UUID) -> None:
        """Append an audit entry for a PHI access.

        Args:
            action: What was done.
            resource_type: The kind of resource touched.
            resource_id: Which resource.
        """
        self._session.add(
            AuditLogEntry(
                actor_type=AuditActorType.PATIENT,
                actor_id=self._patient_id,
                action=action.value,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=self._request_id,
            )
        )
        await self._session.commit()

    async def list_completed_studies(self) -> list[StudySummary]:
        """Return the patient's completed studies, newest first.

        Scheduled and cancelled visits are excluded: Core #3 limits the patient's view to
        completed visits, and a cancelled study's images must never be reachable.

        Returns:
            The patient's completed studies.
        """
        # Counted in one grouped join rather than a query per study, which would be an N+1
        # on the patient's most-used screen.
        result = await self._session.execute(
            select(Study, func.count(Image.id))
            .outerjoin(Image, Image.study_id == Study.id)
            .where(Study.patient_id == self._patient_id, Study.status == StudyStatus.COMPLETED)
            .group_by(Study.id)
            .order_by(Study.performed_at.desc())
        )
        return [
            StudySummary(
                id=study.id,
                performed_at=study.performed_at,
                description=study.description,
                image_count=image_count,
            )
            for study, image_count in result.all()
        ]

    async def list_images(self, study_id: UUID) -> list[ImageSummary] | None:
        """Return image metadata for one of the patient's completed studies.

        Args:
            study_id: The study to list.

        Returns:
            Image metadata, or None if the study is missing, not completed, or not theirs.
        """
        owns = await self._session.scalar(
            select(Study.id).where(
                Study.id == study_id,
                Study.patient_id == self._patient_id,
                Study.status == StudyStatus.COMPLETED,
            )
        )
        if owns is None:
            await self._record(AuditAction.STUDY_ACCESS_DENIED, "study", study_id)
            return None

        result = await self._session.execute(
            select(Image).where(Image.study_id == study_id).order_by(Image.sequence)
        )
        return [
            ImageSummary(
                id=image.id,
                sequence=image.sequence,
                width=image.width,
                height=image.height,
                has_thumbnail=image.thumbnail_path is not None,
            )
            for image in result.scalars().all()
        ]

    async def open_image(self, image_id: UUID, *, thumbnail: bool = False) -> ImageAccess | None:
        """Authorise access to one image and record the access.

        The audit entry is written here rather than by the caller so that reading and
        recording cannot drift apart. It is committed at authorisation time rather than
        after the bytes are served: for a PHI access log, recording a read that later failed
        mid-transfer is the safer direction than missing one that succeeded.

        Args:
            image_id: The image requested.
            thumbnail: Whether the thumbnail was requested rather than the full image.

        Returns:
            Storage references for the image, or None if it is missing, belongs to a
            non-completed study, or belongs to another patient.
        """
        result = await self._session.execute(
            select(Image)
            .join(Study, Image.study_id == Study.id)
            .where(
                Image.id == image_id,
                Study.patient_id == self._patient_id,
                Study.status == StudyStatus.COMPLETED,
            )
        )
        image = result.scalar_one_or_none()
        if image is None:
            # Core #6 requires rejected attempts to be logged, not merely refused. Recorded
            # here rather than in the handler so it cannot be omitted from a new route.
            await self._record(AuditAction.IMAGE_ACCESS_DENIED, "image", image_id)
            return None

        await self._record(AuditAction.IMAGE_VIEWED, "image", image.id)
        return ImageAccess(
            id=image.id,
            storage_path=image.thumbnail_path
            if thumbnail and image.thumbnail_path
            else image.storage_path,
            thumbnail_path=image.thumbnail_path,
        )

    async def list_clips(self, study_id: UUID) -> list[CineClipSummary] | None:
        """Return cine clips for one of the patient's completed studies.

        Args:
            study_id: The study to list.

        Returns:
            Clip summaries in capture order, or None if the study is missing, not
            completed, or not theirs.
        """
        owns = await self._session.scalar(
            select(Study.id).where(
                Study.id == study_id,
                Study.patient_id == self._patient_id,
                Study.status == StudyStatus.COMPLETED,
            )
        )
        if owns is None:
            await self._record(AuditAction.STUDY_ACCESS_DENIED, "study", study_id)
            return None

        result = await self._session.execute(
            select(
                CineClip,
                func.count(CineFrame.id).filter(CineFrame.integrity == FrameIntegrity.OK),
            )
            .outerjoin(CineFrame, CineFrame.clip_id == CineClip.id)
            .where(CineClip.study_id == study_id)
            .group_by(CineClip.id)
            .order_by(CineClip.sequence)
        )
        return [
            CineClipSummary(
                id=clip.id,
                study_id=clip.study_id,
                sequence=clip.sequence,
                frame_count=clip.frame_count,
                default_fps=clip.default_fps,
                available_frame_count=available,
            )
            for clip, available in result.all()
        ]

    async def open_clip(self, clip_id: UUID) -> CineManifest | None:
        """Authorise a cine clip and return its ordered frame manifest.

        This is the audited event for cine: one entry per clip opened, not one per frame.
        A hundred rows for a single playback would bury the access log without recording
        anything the manifest entry does not already say.

        Args:
            clip_id: The clip requested.

        Returns:
            The manifest, or None if the clip is missing, belongs to a non-completed
            study, or belongs to another patient.
        """
        clip = (
            await self._session.execute(
                select(CineClip)
                .join(Study, CineClip.study_id == Study.id)
                .where(
                    CineClip.id == clip_id,
                    Study.patient_id == self._patient_id,
                    Study.status == StudyStatus.COMPLETED,
                )
            )
        ).scalar_one_or_none()
        if clip is None:
            await self._record(AuditAction.CINE_ACCESS_DENIED, "cine_clip", clip_id)
            return None

        frames = (
            await self._session.execute(
                select(CineFrame.sequence, CineFrame.integrity)
                .where(CineFrame.clip_id == clip.id)
                .order_by(CineFrame.sequence)
            )
        ).all()

        await self._record(AuditAction.CINE_VIEWED, "cine_clip", clip.id)
        return CineManifest(
            id=clip.id,
            study_id=clip.study_id,
            frame_count=clip.frame_count,
            default_fps=clip.default_fps,
            frames=[
                CineFrameEntry(sequence=sequence, available=integrity is FrameIntegrity.OK)
                for sequence, integrity in frames
            ],
        )

    async def open_all_frames(self, clip_id: UUID) -> list[FrameAccess] | None:
        """Authorise every intact frame of a clip in one query.

        Backs the bundle endpoint. Frames the manifest marks damaged are excluded here
        rather than filtered later, so there is no path that could serve one.

        Args:
            clip_id: The clip requested.

        Returns:
            Storage references in playback order, or None if the clip is missing or not
            theirs.
        """
        owns = await self._session.scalar(
            select(CineClip.id)
            .join(Study, CineClip.study_id == Study.id)
            .where(
                CineClip.id == clip_id,
                Study.patient_id == self._patient_id,
                Study.status == StudyStatus.COMPLETED,
            )
        )
        if owns is None:
            await self._record(AuditAction.CINE_ACCESS_DENIED, "cine_clip", clip_id)
            return None

        frames = (
            await self._session.execute(
                select(CineFrame.sequence, CineFrame.storage_path)
                .where(CineFrame.clip_id == clip_id, CineFrame.integrity == FrameIntegrity.OK)
                .order_by(CineFrame.sequence)
            )
        ).all()
        return [
            FrameAccess(clip_id=clip_id, sequence=sequence, storage_path=path)
            for sequence, path in frames
        ]

    async def open_frame(self, clip_id: UUID, sequence: int) -> FrameAccess | None:
        """Authorise access to one frame's bytes.

        Ownership is re-checked here rather than inferred from the manifest call: the two
        are separate requests, and nothing stops a caller from skipping the first.

        Args:
            clip_id: The clip the frame belongs to.
            sequence: Zero-based frame position.

        Returns:
            A storage reference, or None if the frame is missing, damaged, or not theirs.
        """
        frame = (
            await self._session.execute(
                select(CineFrame)
                .join(CineClip, CineFrame.clip_id == CineClip.id)
                .join(Study, CineClip.study_id == Study.id)
                .where(
                    CineFrame.clip_id == clip_id,
                    CineFrame.sequence == sequence,
                    CineFrame.integrity == FrameIntegrity.OK,
                    Study.patient_id == self._patient_id,
                    Study.status == StudyStatus.COMPLETED,
                )
            )
        ).scalar_one_or_none()
        if frame is None:
            await self._record(AuditAction.CINE_ACCESS_DENIED, "cine_clip", clip_id)
            return None

        return FrameAccess(
            clip_id=clip_id, sequence=frame.sequence, storage_path=frame.storage_path
        )

    async def release(self) -> None:
        """Return this scope's database connection to the pool.

        Called by byte-serving routes once authorisation is settled. Object storage round
        trips take far longer than the query that authorised them, and a session held
        across one is a pooled connection doing nothing: with a small pool in front of a
        shared pooler, that alone caps how many scans the API can serve at once. The scope
        must not be used again afterwards.
        """
        await self._session.close()

    async def get_profile(self) -> PatientProfile | None:
        """Return the patient's own identifying details.

        Args:
            None.

        Returns:
            The profile, or None if the record has disappeared.
        """
        row = (
            await self._session.execute(
                select(
                    Patient.first_name, Patient.last_name, Patient.account_id, Patient.date_of_birth
                ).where(Patient.id == self._patient_id)
            )
        ).first()
        if row is None:
            return None
        return PatientProfile(
            display_name=f"{row.first_name} {row.last_name}",
            account_id=row.account_id,
            date_of_birth_masked=f"\u2022\u2022\u2022\u2022-\u2022\u2022-{row.date_of_birth.day:02d}",
        )

    async def list_signed_reports(self) -> list[ReportSummary]:
        """Return the patient's signed reports, newest first.

        Returns:
            Reports the patient is permitted to read.
        """
        result = await self._session.execute(
            select(Report)
            .where(
                Report.patient_id == self._patient_id,
                Report.status.in_(PATIENT_VISIBLE_REPORT_STATUSES),
            )
            .order_by(Report.signed_at.desc())
        )
        return [
            ReportSummary(
                id=report.id,
                study_id=report.study_id,
                title=report.title,
                status=report.status,
                signed_at=report.signed_at,
            )
            for report in result.scalars().all()
        ]

    async def open_report(self, report_id: UUID) -> ReportDetail | None:
        """Authorise a report read and record it.

        Args:
            report_id: The report requested.

        Returns:
            The report, or None if it is missing, unsigned, or another patient's.
        """
        report = (
            await self._session.execute(
                select(Report).where(
                    Report.id == report_id,
                    Report.patient_id == self._patient_id,
                    Report.status.in_(PATIENT_VISIBLE_REPORT_STATUSES),
                )
            )
        ).scalar_one_or_none()

        if report is None:
            await self._record(AuditAction.REPORT_ACCESS_DENIED, "report", report_id)
            return None

        await self._record(AuditAction.REPORT_VIEWED, "report", report.id)
        return ReportDetail(
            id=report.id,
            study_id=report.study_id,
            title=report.title,
            status=report.status,
            body=report.body,
            signed_at=report.signed_at,
        )

    async def _owns_resource(self, resource_type: ShareResourceType, resource_id: UUID) -> bool:
        """Check the patient owns a shareable resource, without recording a view.

        Sharing is not reading, so this deliberately does not write a view audit entry —
        the issuance entry is what belongs in the log.

        Args:
            resource_type: Whether the resource is an image or a report.
            resource_id: The resource in question.

        Returns:
            True if the resource belongs to this patient and is shareable.
        """
        if resource_type is ShareResourceType.IMAGE:
            found = await self._session.scalar(
                select(Image.id)
                .join(Study, Image.study_id == Study.id)
                .where(
                    Image.id == resource_id,
                    Study.patient_id == self._patient_id,
                    Study.status == StudyStatus.COMPLETED,
                )
            )
        else:
            found = await self._session.scalar(
                select(Report.id).where(
                    Report.id == resource_id,
                    Report.patient_id == self._patient_id,
                    Report.status.in_(PATIENT_VISIBLE_REPORT_STATUSES),
                )
            )
        return found is not None

    async def create_share(
        self,
        *,
        resource_type: ShareResourceType,
        resource_id: UUID,
        recipient_email: str,
        ttl_hours: int,
    ) -> MintedShare | None:
        """Mint a share link for a resource the patient owns.

        Ownership is checked here rather than trusted from the request. A link created for
        someone else's resource would be a permanent, unauthenticated cross-patient
        capability — far worse than a single unauthorised read.

        Args:
            resource_type: Image or report.
            resource_id: The resource to share.
            recipient_email: Who the link is being sent to.
            ttl_hours: How long the link stays valid.

        Returns:
            The new link and its raw token, or None if the resource is not theirs.
        """
        if not await self._owns_resource(resource_type, resource_id):
            await self._record(AuditAction.SHARE_LINK_CREATED, resource_type.value, resource_id)
            return None

        token = mint_token()
        link = ShareLink(
            token_hash=hash_token(token),
            resource_type=resource_type,
            resource_id=resource_id,
            created_by_patient_id=self._patient_id,
            recipient_email=recipient_email,
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
        )
        self._session.add(link)
        await self._session.flush()
        await self._record(AuditAction.SHARE_LINK_CREATED, "share_link", link.id)

        return MintedShare(record=_to_record(link), token=token)

    async def list_shares(self) -> list[ShareRecord]:
        """Return the links this patient has created, newest first.

        Returns:
            Their share links, active and past.
        """
        result = await self._session.execute(
            select(ShareLink)
            .where(ShareLink.created_by_patient_id == self._patient_id)
            .order_by(ShareLink.created_at.desc())
        )
        return [_to_record(link) for link in result.scalars().all()]

    async def revoke_share(self, share_id: UUID) -> bool:
        """Switch off one of the patient's links.

        Args:
            share_id: The link to revoke.

        Returns:
            True if a live link was revoked, False if it is missing or not theirs.
        """
        result = await self._session.execute(
            update(ShareLink)
            .where(
                ShareLink.id == share_id,
                ShareLink.created_by_patient_id == self._patient_id,
                ShareLink.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
            .returning(ShareLink.id)
        )
        revoked = result.scalar_one_or_none() is not None
        await self._record(AuditAction.SHARE_LINK_REVOKED, "share_link", share_id)
        return revoked


def _to_record(link: ShareLink) -> ShareRecord:
    """Convert a stored link to the shape the patient sees.

    Args:
        link: The stored row.

    Returns:
        The record, without the token digest.
    """
    return ShareRecord(
        id=link.id,
        resource_type=link.resource_type,
        resource_id=link.resource_id,
        recipient_email=link.recipient_email,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        access_count=link.access_count,
    )
