import random
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid5

from app.models.enums import (
    AppointmentStatus,
    FrameIntegrity,
    ReportStatus,
    StaffRole,
    StudyStatus,
)
from app.seed.plan import (
    AppointmentPlan,
    ClipPlan,
    FramePlan,
    ImagePlan,
    PatientPlan,
    ProviderPlan,
    ReportPlan,
    SeedPlan,
    StaffPlan,
    StudyPlan,
)

#: Namespace for deterministic identifiers. Re-running the seed produces the same UUIDs,
#: so storage objects already uploaded can be recognised and skipped.
_NAMESPACE = UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")

#: Password for every seeded login. Documented in the README; these are demo accounts on
#: synthetic data, never real credentials.
DEMO_PASSWORD = "PortalDemo!2026"

_FULL_SEED = 20260811


class Profile(StrEnum):
    """Which dataset to build."""

    DEMO = "demo"
    FULL = "full"


def _uid(*parts: object) -> UUID:
    """Derive a stable UUID from its logical path.

    Args:
        *parts: Components identifying the entity.

    Returns:
        A deterministic UUID.
    """
    return uuid5(_NAMESPACE, ":".join(str(part) for part in parts))


def _image(study_id: UUID, index: int) -> ImagePlan:
    """Build one static image plan.

    Args:
        study_id: Owning study.
        index: Position within the study.

    Returns:
        The image plan with its storage paths.
    """
    image_id = _uid("image", study_id, index)
    return ImagePlan(
        id=image_id,
        sequence=index,
        storage_path=f"studies/{study_id}/images/{image_id}.jpg",
        thumbnail_path=f"studies/{study_id}/images/{image_id}_thumb.jpg",
    )


def _clip(
    study_id: UUID, index: int, frame_count: int, *, missing: tuple[int, ...] = ()
) -> ClipPlan:
    """Build one cine clip plan.

    Args:
        study_id: Owning study.
        index: Position within the study.
        frame_count: Frames the manifest declares.
        missing: Sequence numbers to mark MISSING and never upload, for the corrupt
            manifest edge case.

    Returns:
        The clip plan with all frame plans.
    """
    clip_id = _uid("clip", study_id, index)
    frames = [
        FramePlan(
            id=_uid("frame", clip_id, sequence),
            sequence=sequence,
            storage_path=f"studies/{study_id}/cine/{clip_id}/{sequence:03d}.jpg",
            integrity=FrameIntegrity.MISSING if sequence in missing else FrameIntegrity.OK,
        )
        for sequence in range(frame_count)
    ]
    return ClipPlan(id=clip_id, sequence=index, default_fps=12, frames=frames)


_REPORT_BODY = (
    "TECHNIQUE\nComplete {region} ultrasound performed with a curvilinear transducer.\n\n"
    "FINDINGS\n{findings}\n\n"
    "IMPRESSION\n{impression}"
)


def _report(
    study_id: UUID,
    status: ReportStatus,
    *,
    signed_at: datetime | None,
    region: str,
    findings: str,
    impression: str,
) -> ReportPlan:
    """Build a report plan.

    Args:
        study_id: Owning study.
        status: Report status.
        signed_at: Signing time, required for final and amended reports.
        region: Anatomical region named in the technique section.
        findings: Findings paragraph.
        impression: Impression paragraph.

    Returns:
        The report plan.
    """
    return ReportPlan(
        id=_uid("report", study_id, status),
        status=status,
        title=f"{region.title()} Ultrasound",
        body=_REPORT_BODY.format(region=region, findings=findings, impression=impression),
        signed_at=signed_at,
    )


def _demo_providers() -> tuple[list[ProviderPlan], list[StaffPlan]]:
    """Build the demo providers and their logins.

    Two timezones on purpose, so the cross-timezone display rule has something to exercise.

    Returns:
        Providers and the staff logins attached to them.
    """
    providers = [
        ProviderPlan(
            id=_uid("provider", "lee"),
            display_name="Dr Amara Lee",
            specialty="Obstetric ultrasound",
            timezone="America/New_York",
            weekdays=[1, 2, 3, 4, 5],
            start_hour=9,
            end_hour=17,
            slot_minutes=30,
        ),
        ProviderPlan(
            id=_uid("provider", "okafor"),
            display_name="Dr Nnamdi Okafor",
            specialty="Vascular ultrasound",
            timezone="America/Los_Angeles",
            weekdays=[1, 3, 5],
            start_hour=8,
            end_hour=14,
            slot_minutes=20,
        ),
    ]
    staff = [
        StaffPlan(
            id=_uid("staff", "lee"),
            provider_id=providers[0].id,
            role=StaffRole.PROVIDER,
            email="provider@demo.test",
            login_password=DEMO_PASSWORD,
        ),
        StaffPlan(
            id=_uid("staff", "frontdesk"),
            provider_id=providers[0].id,
            role=StaffRole.ADMIN,
            email="admin@demo.test",
            login_password=DEMO_PASSWORD,
        ),
    ]
    return providers, staff


def _demo_patient(provider_id: UUID, now: datetime) -> PatientPlan:
    """Build the primary demo patient.

    Deliberately loaded so every Priority 1 and 2 behaviour has something to show: a
    100-frame clip, a clip with holes in it, a report that must be visible and one that
    must not, and studies that must be excluded from the patient's list.

    Args:
        provider_id: Provider who performed the studies.
        now: Reference time.

    Returns:
        The demo patient plan.
    """
    patient_id = _uid("patient", "demo")

    recent = _uid("study", patient_id, "recent")
    earlier = _uid("study", patient_id, "earlier")
    pending = _uid("study", patient_id, "pending")
    cancelled = _uid("study", patient_id, "cancelled")
    upcoming = _uid("study", patient_id, "upcoming")

    studies = [
        StudyPlan(
            id=recent,
            patient_id=patient_id,
            provider_id=provider_id,
            performed_at=now - timedelta(days=9),
            status=StudyStatus.COMPLETED,
            description="Second trimester anatomy survey",
            images=[_image(recent, index) for index in range(6)],
            # The flagship performance case from Core #4.
            clips=[_clip(recent, 0, 100)],
            reports=[
                _report(
                    recent,
                    ReportStatus.FINAL,
                    signed_at=now - timedelta(days=8),
                    region="obstetric",
                    findings=(
                        "Single intrauterine gestation with cardiac activity present. "
                        "Biometry is concordant with dates. Amniotic fluid volume is normal. "
                        "Placenta is posterior and clear of the internal os."
                    ),
                    impression="Normal second trimester survey. No sonographic abnormality.",
                )
            ],
        ),
        StudyPlan(
            id=earlier,
            patient_id=patient_id,
            provider_id=provider_id,
            performed_at=now - timedelta(days=54),
            status=StudyStatus.COMPLETED,
            description="Dating scan",
            images=[_image(earlier, index) for index in range(3)],
            # Two frames deliberately absent, so the viewer's gap handling is real.
            clips=[_clip(earlier, 0, 24, missing=(9, 10))],
            reports=[
                _report(
                    earlier,
                    ReportStatus.FINAL,
                    signed_at=now - timedelta(days=53),
                    region="obstetric",
                    findings=(
                        "Single viable intrauterine pregnancy. "
                        "Crown-rump length consistent with dates."
                    ),
                    impression="Viable intrauterine pregnancy.",
                )
            ],
        ),
        StudyPlan(
            id=pending,
            patient_id=patient_id,
            provider_id=provider_id,
            performed_at=now - timedelta(days=2),
            status=StudyStatus.COMPLETED,
            description="Growth follow-up",
            images=[_image(pending, index) for index in range(2)],
            # Preliminary only: this report must never reach the patient (Core #7).
            reports=[
                _report(
                    pending,
                    ReportStatus.PRELIMINARY,
                    signed_at=None,
                    region="obstetric",
                    findings="Interval growth appears appropriate. Awaiting radiologist review.",
                    impression="Preliminary — not for release.",
                )
            ],
        ),
        StudyPlan(
            id=cancelled,
            patient_id=patient_id,
            provider_id=provider_id,
            performed_at=now - timedelta(days=20),
            status=StudyStatus.CANCELLED,
            description="Cancelled visit",
            images=[_image(cancelled, 0)],
        ),
        StudyPlan(
            id=upcoming,
            patient_id=patient_id,
            provider_id=provider_id,
            performed_at=now + timedelta(days=14),
            status=StudyStatus.SCHEDULED,
            description="Third trimester growth scan",
        ),
    ]

    return PatientPlan(
        id=patient_id,
        account_id="AS-100241",
        date_of_birth=date(1991, 6, 24),
        first_name="Rowan",
        last_name="Whitfield",
        email="patient@demo.test",
        phone="+1-555-0142",
        login_password=DEMO_PASSWORD,
        studies=studies,
    )


def _neighbour_patient(provider_id: UUID, now: datetime) -> PatientPlan:
    """Build a second patient whose data the leakage tests attempt to reach.

    Without a populated neighbour, an adversarial test proves nothing: every unauthorised
    request would return empty simply because no other data exists.

    Args:
        provider_id: Provider who performed the study.
        now: Reference time.

    Returns:
        The neighbour patient plan.
    """
    patient_id = _uid("patient", "neighbour")
    study_id = _uid("study", patient_id, "only")
    return PatientPlan(
        id=patient_id,
        account_id="AS-100377",
        date_of_birth=date(1985, 2, 9),
        first_name="Devon",
        last_name="Marsh",
        email="neighbour@demo.test",
        login_password=DEMO_PASSWORD,
        studies=[
            StudyPlan(
                id=study_id,
                patient_id=patient_id,
                provider_id=provider_id,
                performed_at=now - timedelta(days=30),
                status=StudyStatus.COMPLETED,
                description="Carotid duplex",
                images=[_image(study_id, index) for index in range(3)],
                clips=[_clip(study_id, 0, 20)],
                reports=[
                    _report(
                        study_id,
                        ReportStatus.FINAL,
                        signed_at=now - timedelta(days=29),
                        region="carotid",
                        findings=(
                            "No haemodynamically significant stenosis in either carotid system."
                        ),
                        impression="Normal carotid duplex.",
                    )
                ],
            )
        ],
    )


def build_demo_plan(now: datetime) -> SeedPlan:
    """Build the fast demo dataset.

    Args:
        now: Reference time, so study and appointment dates sit sensibly around today.

    Returns:
        The demo seed plan.
    """
    providers, staff = _demo_providers()
    primary = _demo_patient(providers[0].id, now)
    neighbour = _neighbour_patient(providers[1].id, now)

    primary.appointments = [
        AppointmentPlan(
            id=_uid("appointment", primary.id, "upcoming"),
            patient_id=primary.id,
            provider_id=providers[0].id,
            slot_start_utc=now + timedelta(days=10),
            status=AppointmentStatus.CONFIRMED,
        )
    ]

    return SeedPlan(
        name=Profile.DEMO,
        providers=providers,
        staff=staff,
        patients=[primary, neighbour],
        slot_days=45,
    )


def build_full_plan(now: datetime) -> SeedPlan:
    """Build the benchmark-scale dataset described in the brief.

    Args:
        now: Reference time.

    Returns:
        The full seed plan.
    """
    rng = random.Random(_FULL_SEED)
    demo = build_demo_plan(now)

    providers = list(demo.providers)
    zones = ("America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles")
    for index in range(len(providers), 10):
        providers.append(
            ProviderPlan(
                id=_uid("provider", index),
                display_name=f"Dr Provider {index:02d}",
                specialty="Diagnostic ultrasound",
                timezone=zones[index % len(zones)],
                weekdays=[1, 2, 3, 4, 5],
                start_hour=9,
                end_hour=17,
                slot_minutes=30,
            )
        )

    patients = list(demo.patients)
    for index in range(50):
        patient_id = _uid("patient", "bulk", index)
        studies: list[StudyPlan] = []
        for visit in range(rng.randint(1, 5)):
            study_id = _uid("study", patient_id, visit)
            provider = providers[rng.randrange(len(providers))]
            clips: list[ClipPlan] = []
            for clip_index in range(rng.randint(0, 2)):
                clips.append(_clip(study_id, clip_index, rng.choice([24, 40, 60, 100])))
            studies.append(
                StudyPlan(
                    id=study_id,
                    patient_id=patient_id,
                    provider_id=provider.id,
                    performed_at=now - timedelta(days=rng.randint(3, 400)),
                    status=StudyStatus.COMPLETED,
                    description="Diagnostic ultrasound",
                    images=[_image(study_id, i) for i in range(rng.randint(1, 10))],
                    clips=clips,
                    reports=[
                        _report(
                            study_id,
                            ReportStatus.FINAL,
                            signed_at=now - timedelta(days=rng.randint(1, 3)),
                            region="abdominal",
                            findings="No focal abnormality identified.",
                            impression="Normal study.",
                        )
                    ],
                )
            )
        patients.append(
            PatientPlan(
                id=patient_id,
                account_id=f"AS-2{index:05d}",
                date_of_birth=date(
                    1960 + rng.randint(0, 45), rng.randint(1, 12), rng.randint(1, 28)
                ),
                first_name=f"Patient{index:02d}",
                last_name="Testcase",
                email=f"patient{index:02d}@seed.test",
                studies=studies,
            )
        )

    return SeedPlan(
        name=Profile.FULL,
        providers=providers,
        staff=demo.staff,
        patients=patients,
        slot_days=120,
    )


def build_plan(profile: Profile, now: datetime | None = None) -> SeedPlan:
    """Build the plan for a profile.

    Args:
        profile: Which dataset to build.
        now: Reference time; defaults to the current instant.

    Returns:
        The seed plan.
    """
    reference = now or datetime.now(UTC)
    return build_demo_plan(reference) if profile is Profile.DEMO else build_full_plan(reference)
