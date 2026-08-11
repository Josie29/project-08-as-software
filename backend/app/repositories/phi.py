from datetime import datetime
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLogEntry
from app.models.enums import AuditAction, AuditActorType, StudyStatus
from app.models.identity import Patient
from app.models.imaging import Image, Study

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


class ImageAccess(BaseModel):
    """An authorised reference to one image's stored objects."""

    id: UUID
    storage_path: str
    thumbnail_path: str | None


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
