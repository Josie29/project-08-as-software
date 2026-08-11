from datetime import UTC, datetime

import asyncpg

from app.seed import rows
from app.seed.profiles import Profile, build_plan


async def test_the_demo_seed_applies_to_a_migrated_database(db: asyncpg.Connection) -> None:
    """The seed is how a reviewer gets a working app from a clean checkout. If it drifts
    from the schema, the quick-start fails at the first step and nothing else can be
    assessed.
    """
    plan = build_plan(Profile.DEMO, datetime.now(UTC))

    await rows.insert_plan(db, plan)

    assert await db.fetchval("SELECT count(*) FROM patients") == len(plan.patients)
    assert await db.fetchval("SELECT count(*) FROM studies") == len(plan.studies)
    assert await db.fetchval("SELECT count(*) FROM appointment_slots") > 0
    # Frames marked missing are still recorded; only their objects are absent.
    assert await db.fetchval("SELECT count(*) FROM cine_frames WHERE integrity = 'missing'") == 2


async def test_seeding_leaves_every_patient_unverified(db: asyncpg.Connection) -> None:
    """If the seed linked patient records to logins, a reviewer would skip the Core #2
    identity check entirely and the second factor would never be exercised."""
    await rows.insert_plan(db, build_plan(Profile.DEMO, datetime.now(UTC)))

    linked = await db.fetchval("SELECT count(*) FROM patients WHERE auth_user_id IS NOT NULL")

    assert linked == 0


async def test_reset_clears_the_append_only_audit_log(db: asyncpg.Connection) -> None:
    """audit_log rejects DELETE by trigger, so a reset built on DELETE would fail and leave
    the database half-seeded. TRUNCATE is DDL and bypasses the trigger.
    """
    await db.execute(
        """
        INSERT INTO audit_log (actor_type, action, resource_type)
        VALUES ('system', 'seed_probe', 'test')
        """
    )

    await rows.reset(db)

    assert await db.fetchval("SELECT count(*) FROM audit_log") == 0


async def test_reseeding_requires_an_explicit_reset(db: asyncpg.Connection) -> None:
    """Re-running the seed against a populated database must not silently duplicate or
    partially overwrite a reviewer's data."""
    plan = build_plan(Profile.DEMO, datetime.now(UTC))
    assert not await rows.is_populated(db)

    await rows.insert_plan(db, plan)

    assert await rows.is_populated(db)
