from datetime import UTC, date, datetime, time, timedelta

import asyncpg
import structlog

from app.models.enums import FrameIntegrity
from app.seed.images import STILL_SIZE
from app.seed.plan import SeedPlan
from app.services.scheduling import SlotRule, generate_slots

logger = structlog.get_logger(__name__)

#: Tables the seed owns, in dependency order for truncation.
_SEEDED_TABLES = (
    "reminder_sends",
    "appointments",
    "appointment_slots",
    "blocked_ranges",
    "availability_rules",
    "cine_frames",
    "cine_clips",
    "images",
    "reports",
    "studies",
    "share_links",
    "identity_verifications",
    "identity_attempts",
    "audit_log",
    "staff",
    "patients",
    "providers",
)

#: Placeholder byte sizes recorded at insert time. The upload pass corrects them to the
#: real encoded sizes, so a plan-only run still produces valid rows.
_ESTIMATED_STILL_BYTES = 21_000
_ESTIMATED_FRAME_BYTES = 7_200


async def reset(conn: asyncpg.Connection) -> None:
    """Remove all seeded data.

    `audit_log` is append-only and rejects DELETE, so TRUNCATE is used throughout — it is
    DDL and bypasses the row trigger.

    Args:
        conn: Open database connection.
    """
    await conn.execute(f"TRUNCATE {', '.join(_SEEDED_TABLES)} CASCADE")
    logger.info("seed.reset")


async def is_populated(conn: asyncpg.Connection) -> bool:
    """Report whether any patients already exist.

    Args:
        conn: Open database connection.

    Returns:
        True if the database already holds seeded data.
    """
    return bool(await conn.fetchval("SELECT EXISTS (SELECT 1 FROM patients)"))


async def _insert_providers(conn: asyncpg.Connection, plan: SeedPlan) -> None:
    """Insert providers, their availability rules, and their generated slots.

    Args:
        conn: Open database connection.
        plan: The dataset to insert.
    """
    today = datetime.now(UTC).date()
    for provider in plan.providers:
        await conn.execute(
            """
            INSERT INTO providers (id, display_name, specialty, timezone)
            VALUES ($1, $2, $3, $4)
            """,
            provider.id,
            provider.display_name,
            provider.specialty,
            provider.timezone,
        )

        slot_rows: list[tuple[object, ...]] = []
        for weekday in provider.weekdays:
            rule = SlotRule(
                weekday=weekday,
                start_local=time(provider.start_hour),
                end_local=time(provider.end_hour),
                slot_minutes=provider.slot_minutes,
            )
            await conn.execute(
                """
                INSERT INTO availability_rules
                    (provider_id, weekday, start_local, end_local, slot_minutes)
                VALUES ($1, $2, $3, $4, $5)
                """,
                provider.id,
                weekday,
                rule.start_local,
                rule.end_local,
                rule.slot_minutes,
            )
            window_start = today - timedelta(days=7)
            window_end = today + timedelta(days=plan.slot_days)
            slot_rows.extend(
                (provider.id, slot.start_utc, slot.end_utc)
                for slot in generate_slots(rule, window_start, window_end, provider.timezone)
            )

        await conn.executemany(
            "INSERT INTO appointment_slots (provider_id, start_utc, end_utc) VALUES ($1, $2, $3)",
            slot_rows,
        )
        logger.info("seed.provider", provider_uuid=str(provider.id), slots=len(slot_rows))


async def _insert_staff(conn: asyncpg.Connection, plan: SeedPlan) -> None:
    """Insert staff logins.

    Args:
        conn: Open database connection.
        plan: The dataset to insert.
    """
    await conn.executemany(
        "INSERT INTO staff (id, provider_id, role, email) VALUES ($1, $2, $3, $4)",
        [(member.id, member.provider_id, member.role.value, member.email) for member in plan.staff],
    )


async def _insert_patients(conn: asyncpg.Connection, plan: SeedPlan) -> None:
    """Insert patients, studies, images, cine clips and frames, and reports.

    `auth_user_id` is deliberately left null: a patient must still pass the Core #2
    identity check to link their login to this record.

    Args:
        conn: Open database connection.
        plan: The dataset to insert.
    """
    for patient in plan.patients:
        await conn.execute(
            """
            INSERT INTO patients
                (id, account_id, date_of_birth, first_name, last_name, email, phone)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            patient.id,
            patient.account_id,
            patient.date_of_birth,
            patient.first_name,
            patient.last_name,
            patient.email,
            patient.phone,
        )

        for study in patient.studies:
            await conn.execute(
                """
                INSERT INTO studies
                    (id, patient_id, provider_id, performed_at, status, description)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                study.id,
                study.patient_id,
                study.provider_id,
                study.performed_at,
                study.status.value,
                study.description,
            )

            await conn.executemany(
                """
                INSERT INTO images
                    (id, study_id, sequence, storage_path, thumbnail_path,
                     width, height, byte_size)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                [
                    (
                        image.id,
                        study.id,
                        image.sequence,
                        image.storage_path,
                        image.thumbnail_path,
                        STILL_SIZE[0],
                        STILL_SIZE[1],
                        _ESTIMATED_STILL_BYTES,
                    )
                    for image in study.images
                ],
            )

            for clip in study.clips:
                await conn.execute(
                    """
                    INSERT INTO cine_clips
                        (id, study_id, sequence, frame_count, default_fps)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    clip.id,
                    study.id,
                    clip.sequence,
                    clip.frame_count,
                    clip.default_fps,
                )
                await conn.executemany(
                    """
                    INSERT INTO cine_frames
                        (id, clip_id, sequence, storage_path, byte_size, integrity)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    [
                        (
                            frame.id,
                            clip.id,
                            frame.sequence,
                            frame.storage_path,
                            0
                            if frame.integrity is FrameIntegrity.MISSING
                            else _ESTIMATED_FRAME_BYTES,
                            frame.integrity.value,
                        )
                        for frame in clip.frames
                    ],
                )

            await conn.executemany(
                """
                INSERT INTO reports
                    (id, study_id, patient_id, status, title, body, signed_at,
                     signed_by_provider_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                [
                    (
                        report.id,
                        study.id,
                        patient.id,
                        report.status.value,
                        report.title,
                        report.body,
                        report.signed_at,
                        study.provider_id if report.signed_at else None,
                    )
                    for report in study.reports
                ],
            )


async def _insert_appointments(conn: asyncpg.Connection, plan: SeedPlan) -> None:
    """Book planned appointments against the nearest generated slot.

    Args:
        conn: Open database connection.
        plan: The dataset to insert.
    """
    for patient in plan.patients:
        for appointment in patient.appointments:
            slot_id = await conn.fetchval(
                """
                SELECT id FROM appointment_slots
                WHERE provider_id = $1 AND start_utc >= $2 AND status = 'open'
                ORDER BY start_utc
                LIMIT 1
                """,
                appointment.provider_id,
                appointment.slot_start_utc,
            )
            if slot_id is None:
                logger.warning("seed.appointment_no_slot", patient_uuid=str(patient.id))
                continue
            await conn.execute(
                """
                INSERT INTO appointments (id, slot_id, patient_id, status, booked_at)
                VALUES ($1, $2, $3, $4, now())
                """,
                appointment.id,
                slot_id,
                patient.id,
                appointment.status.value,
            )


async def insert_plan(conn: asyncpg.Connection, plan: SeedPlan) -> None:
    """Insert an entire plan in one transaction.

    Args:
        conn: Open database connection.
        plan: The dataset to insert.
    """
    async with conn.transaction():
        await _insert_providers(conn, plan)
        await _insert_staff(conn, plan)
        await _insert_patients(conn, plan)
        await _insert_appointments(conn, plan)
    logger.info(
        "seed.rows_inserted",
        profile=plan.name,
        patients=len(plan.patients),
        studies=len(plan.studies),
    )


async def update_asset_sizes(conn: asyncpg.Connection, sizes: dict[str, int]) -> None:
    """Correct recorded byte sizes to the real encoded sizes after upload.

    Args:
        conn: Open database connection.
        sizes: Storage path to encoded byte size.
    """
    await conn.executemany(
        "UPDATE images SET byte_size = $2 WHERE storage_path = $1",
        list(sizes.items()),
    )
    await conn.executemany(
        "UPDATE cine_frames SET byte_size = $2 WHERE storage_path = $1",
        list(sizes.items()),
    )


def today_utc() -> date:
    """Return today's UTC date.

    Returns:
        The current UTC date.
    """
    return datetime.now(UTC).date()


async def storage_object_names(conn: asyncpg.Connection, bucket: str) -> set[str]:
    """Return the full paths of every object already in a storage bucket.

    Read from `storage.objects` rather than the REST list endpoint, which is not recursive
    and returns only top-level folder entries for an empty prefix — matching nothing, so
    every object would be re-uploaded on a resumed run.

    Args:
        conn: Open database connection.
        bucket: Storage bucket name.

    Returns:
        Object paths currently stored.
    """
    rows_found = await conn.fetch("SELECT name FROM storage.objects WHERE bucket_id = $1", bucket)
    return {row["name"] for row in rows_found}
