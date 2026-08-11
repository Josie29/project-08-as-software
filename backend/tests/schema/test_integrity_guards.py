import asyncpg
import pytest

from tests.schema.factories import book, make_patient, make_provider, make_slot


async def test_reminder_cannot_be_recorded_twice_for_the_same_appointment(
    db: asyncpg.Connection,
) -> None:
    """Without this, a retried or overlapping reminder run double-sends to the patient."""
    provider_id = await make_provider(db)
    slot_id = await make_slot(db, provider_id)
    patient_id = await make_patient(db, account_id="ACC-R")
    appointment_id = await book(db, slot_id, patient_id)

    insert = """
        INSERT INTO reminder_sends (appointment_id, kind, status, attempted_at)
        VALUES ($1, 'pre_visit_24h', 'sent', now())
    """
    await db.execute(insert, appointment_id)

    with pytest.raises(asyncpg.UniqueViolationError):
        await db.execute(insert, appointment_id)


async def test_audit_entries_cannot_be_updated_or_deleted(db: asyncpg.Connection) -> None:
    """Someone who accessed the wrong patient's chart could otherwise erase the evidence."""
    entry_id = await db.fetchval(
        """
        INSERT INTO audit_log (actor_type, actor_id, action, resource_type, resource_id)
        VALUES ('patient', gen_random_uuid(), 'image_viewed', 'image', gen_random_uuid())
        RETURNING id
        """
    )

    with pytest.raises(asyncpg.RaiseError):
        await db.execute("UPDATE audit_log SET action = 'tampered' WHERE id = $1", entry_id)

    with pytest.raises(asyncpg.RaiseError):
        await db.execute("DELETE FROM audit_log WHERE id = $1", entry_id)

    assert (
        await db.fetchval("SELECT action FROM audit_log WHERE id = $1", entry_id) == "image_viewed"
    )


async def test_a_final_report_must_carry_a_signature_time(db: asyncpg.Connection) -> None:
    """Otherwise an unsigned report could be marked final and served to the patient as a
    finalised result (Core #7)."""
    provider_id = await make_provider(db)
    patient_id = await make_patient(db, account_id="ACC-S")
    study_id = await db.fetchval(
        """
        INSERT INTO studies (patient_id, provider_id, performed_at, status)
        VALUES ($1, $2, now(), 'completed') RETURNING id
        """,
        patient_id,
        provider_id,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            """
            INSERT INTO reports (study_id, patient_id, status, title, body)
            VALUES ($1, $2, 'final', 'Obstetric ultrasound', 'Findings...')
            """,
            study_id,
            patient_id,
        )


async def test_cine_frames_cannot_share_a_position(db: asyncpg.Connection) -> None:
    """Duplicate positions would reorder playback, showing a clip that never happened."""
    provider_id = await make_provider(db)
    patient_id = await make_patient(db, account_id="ACC-T")
    study_id = await db.fetchval(
        """
        INSERT INTO studies (patient_id, provider_id, performed_at, status)
        VALUES ($1, $2, now(), 'completed') RETURNING id
        """,
        patient_id,
        provider_id,
    )
    clip_id = await db.fetchval(
        """
        INSERT INTO cine_clips (study_id, sequence, frame_count)
        VALUES ($1, 0, 100) RETURNING id
        """,
        study_id,
    )

    insert_frame = """
        INSERT INTO cine_frames (clip_id, sequence, storage_path, byte_size)
        VALUES ($1, 0, 'frames/0.jpg', 1024)
    """
    await db.execute(insert_frame, clip_id)

    with pytest.raises(asyncpg.UniqueViolationError):
        await db.execute(insert_frame, clip_id)


async def test_a_clip_cannot_exceed_the_hundred_frame_ceiling(db: asyncpg.Connection) -> None:
    """The viewer and the performance budget are both built around Core #4's 100-frame
    ceiling, so a larger clip would silently blow the load target."""
    provider_id = await make_provider(db)
    patient_id = await make_patient(db, account_id="ACC-U")
    study_id = await db.fetchval(
        """
        INSERT INTO studies (patient_id, provider_id, performed_at, status)
        VALUES ($1, $2, now(), 'completed') RETURNING id
        """,
        patient_id,
        provider_id,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await db.execute(
            "INSERT INTO cine_clips (study_id, sequence, frame_count) VALUES ($1, 0, 101)",
            study_id,
        )
