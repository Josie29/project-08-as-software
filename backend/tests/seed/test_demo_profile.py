from datetime import UTC, datetime

from app.models.enums import FrameIntegrity, ReportStatus, StudyStatus
from app.seed.profiles import Profile, build_plan

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def test_demo_includes_a_hundred_frame_clip() -> None:
    """Core #4 and every performance target are written around a 100-frame clip. Without
    one seeded, the flagship case cannot be demonstrated or benchmarked."""
    plan = build_plan(Profile.DEMO, NOW)

    frame_counts = {clip.frame_count for study in plan.studies for clip in study.clips}

    assert 100 in frame_counts


def test_demo_includes_a_clip_with_missing_frames() -> None:
    """Edge case #2 requires a cine manifest referencing frames that are not there. If the
    seed only produced intact clips, graceful degradation could never be shown or tested.
    """
    plan = build_plan(Profile.DEMO, NOW)

    missing = [
        frame
        for study in plan.studies
        for clip in study.clips
        for frame in clip.frames
        if frame.integrity is FrameIntegrity.MISSING
    ]

    assert missing, "no deliberately missing frames were planned"
    # The declared count still includes them, which is what makes the gap detectable.
    clip = next(
        c
        for s in plan.studies
        for c in s.clips
        if any(f.integrity is FrameIntegrity.MISSING for f in c.frames)
    )
    assert clip.frame_count == len(clip.frames)


def test_demo_includes_a_preliminary_report_that_must_stay_hidden() -> None:
    """Core #7 says a preliminary report is never shown to the patient. That rule is
    unprovable unless one exists in the data."""
    plan = build_plan(Profile.DEMO, NOW)

    statuses = {report.status for study in plan.studies for report in study.reports}

    assert ReportStatus.PRELIMINARY in statuses
    assert ReportStatus.FINAL in statuses


def test_demo_includes_studies_that_must_not_appear_in_the_patient_list() -> None:
    """Core #3 limits the patient's view to completed visits. Cancelled and future studies
    have to exist for that exclusion to mean anything."""
    plan = build_plan(Profile.DEMO, NOW)

    statuses = {study.status for study in plan.studies}

    assert StudyStatus.CANCELLED in statuses
    assert StudyStatus.SCHEDULED in statuses


def test_demo_includes_a_second_patient_with_real_data() -> None:
    """The cross-patient leakage tests need a victim. With only one populated patient,
    every unauthorised request would return empty for the wrong reason and the test would
    pass against a completely broken authorization layer.
    """
    plan = build_plan(Profile.DEMO, NOW)

    populated = [patient for patient in plan.patients if patient.studies]

    assert len(populated) >= 2
    neighbour = populated[1]
    assert any(study.images for study in neighbour.studies)
    assert any(study.reports for study in neighbour.studies)


def test_no_patient_starts_out_identity_verified() -> None:
    """A reviewer must see the Core #2 identity check. If the seed pre-linked logins to
    patient records, the portal would open straight to the images."""
    plan = build_plan(Profile.DEMO, NOW)

    # The plan carries no auth linkage at all; verification is what creates it.
    assert all(not hasattr(patient, "auth_user_id") for patient in plan.patients)


def test_the_plan_is_deterministic() -> None:
    """Storage paths derive from these ids. If they changed between runs, re-seeding would
    orphan every previously uploaded object instead of overwriting it."""
    first = build_plan(Profile.DEMO, NOW)
    second = build_plan(Profile.DEMO, NOW)

    assert [study.id for study in first.studies] == [study.id for study in second.studies]
    assert [image.storage_path for study in first.studies for image in study.images] == [
        image.storage_path for study in second.studies for image in study.images
    ]


def test_full_profile_matches_the_briefs_stated_scale() -> None:
    """The performance benchmarks are only comparable against the dataset the brief
    specifies: roughly 50 patients and 10 providers."""
    plan = build_plan(Profile.FULL, NOW)

    assert len(plan.providers) == 10
    assert len(plan.patients) >= 50
    assert plan.asset_count() > 1000
