from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import (
    AppointmentStatus,
    FrameIntegrity,
    ReportStatus,
    StaffRole,
    StudyStatus,
)


class FramePlan(BaseModel):
    """One cine frame. Frames marked MISSING are recorded but never uploaded."""

    id: UUID
    sequence: int
    storage_path: str
    integrity: FrameIntegrity = FrameIntegrity.OK


class ClipPlan(BaseModel):
    """A cine clip and its frames."""

    id: UUID
    sequence: int
    default_fps: int
    frames: list[FramePlan]

    @property
    def frame_count(self) -> int:
        """Return the number of frames the manifest declares.

        Includes frames marked MISSING — the declared count is what the viewer compares
        against the frames it can actually load.

        Returns:
            Total frames referenced by the clip.
        """
        return len(self.frames)


class ImagePlan(BaseModel):
    """A static image and its thumbnail."""

    id: UUID
    sequence: int
    storage_path: str
    thumbnail_path: str


class ReportPlan(BaseModel):
    """A report attached to a study."""

    id: UUID
    status: ReportStatus
    title: str
    body: str
    signed_at: datetime | None = None


class StudyPlan(BaseModel):
    """One imaging visit and everything produced by it."""

    id: UUID
    patient_id: UUID
    provider_id: UUID
    performed_at: datetime
    status: StudyStatus
    description: str
    images: list[ImagePlan] = Field(default_factory=list[ImagePlan])
    clips: list[ClipPlan] = Field(default_factory=list[ClipPlan])
    reports: list[ReportPlan] = Field(default_factory=list[ReportPlan])


class AppointmentPlan(BaseModel):
    """A booked slot. `slot_start_utc` is matched to a generated slot at insert time."""

    id: UUID
    patient_id: UUID
    provider_id: UUID
    slot_start_utc: datetime
    status: AppointmentStatus


class PatientPlan(BaseModel):
    """A patient, their studies, and their bookings."""

    id: UUID
    account_id: str
    date_of_birth: date
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    # Set only for demo accounts, which get a real Supabase Auth login.
    login_password: str | None = None
    studies: list[StudyPlan] = Field(default_factory=list[StudyPlan])
    appointments: list[AppointmentPlan] = Field(default_factory=list[AppointmentPlan])


class StaffPlan(BaseModel):
    """A provider or front-desk login."""

    id: UUID
    provider_id: UUID
    role: StaffRole
    email: str
    login_password: str | None = None


class ProviderPlan(BaseModel):
    """A clinician and their recurring availability."""

    id: UUID
    display_name: str
    specialty: str
    timezone: str
    weekdays: list[int]
    start_hour: int
    end_hour: int
    slot_minutes: int


class SeedPlan(BaseModel):
    """A complete, fully materialised dataset, built before any database or upload work.

    Identifiers are assigned here rather than by the database so that storage paths are
    known up front and the plan can be inspected, costed, and re-run deterministically.
    """

    name: str
    providers: list[ProviderPlan]
    staff: list[StaffPlan]
    patients: list[PatientPlan]
    slot_days: int

    @property
    def studies(self) -> list[StudyPlan]:
        """Return every study across all patients.

        Returns:
            All planned studies.
        """
        return [study for patient in self.patients for study in patient.studies]

    def asset_count(self) -> int:
        """Return how many objects will be uploaded.

        Frames marked MISSING are excluded — deliberately absent from storage.

        Returns:
            Number of storage objects the plan implies.
        """
        total = 0
        for study in self.studies:
            total += len(study.images) * 2  # image plus thumbnail
            for clip in study.clips:
                total += sum(1 for frame in clip.frames if frame.integrity is FrameIntegrity.OK)
        return total
