import asyncio
import uuid
from datetime import timedelta

import asyncpg
import pytest

from tests.conftest import asyncpg_dsn
from tests.schema.factories import book, make_patient, make_provider, make_slot

#: Well above a plausible real collision, so a two-caller-only lock still fails here.
CONCURRENT_BOOKERS = 20


async def _attempt_booking(slot_id: uuid.UUID, patient_id: uuid.UUID) -> bool:
    """Book a slot on a connection of its own, so the database arbitrates.

    Args:
        slot_id: Slot every caller is competing for.
        patient_id: The patient this attempt books for.

    Returns:
        True if this attempt committed an appointment, False if it was rejected.
    """
    conn = await asyncpg.connect(asyncpg_dsn())
    try:
        async with conn.transaction():
            await book(conn, slot_id, patient_id)
        return True
    except asyncpg.UniqueViolationError:
        return False
    finally:
        await conn.close()


async def test_only_one_of_many_concurrent_bookings_wins(db: asyncpg.Connection) -> None:
    """Two confirmed appointments for one slot means a patient arrives to a taken room.
    Asserted at the database level, so it holds however many API instances run.
    """
    provider_id = await make_provider(db)
    slot_id = await make_slot(db, provider_id)
    patient_ids = [
        await make_patient(db, account_id=f"ACC-{index:03d}") for index in range(CONCURRENT_BOOKERS)
    ]

    results = await asyncio.gather(
        *(_attempt_booking(slot_id, patient_id) for patient_id in patient_ids)
    )

    assert sum(results) == 1, f"expected exactly one winner, got {sum(results)}"
    live_count = await db.fetchval(
        """
        SELECT count(*) FROM appointments
        WHERE slot_id = $1 AND status IN ('requested', 'confirmed')
        """,
        slot_id,
    )
    assert live_count == 1


async def test_cancelling_frees_the_slot_for_rebooking(db: asyncpg.Connection) -> None:
    """Catches a plain UNIQUE(slot_id) wedging a slot forever after a cancellation."""
    provider_id = await make_provider(db)
    slot_id = await make_slot(db, provider_id)
    first = await make_patient(db, account_id="ACC-A")
    second = await make_patient(db, account_id="ACC-B")

    appointment_id = await book(db, slot_id, first)
    # While the first booking is live, the slot is genuinely taken.
    with pytest.raises(asyncpg.UniqueViolationError):
        await book(db, slot_id, second)

    await db.execute(
        "UPDATE appointments SET status = 'cancelled', cancelled_at = now() WHERE id = $1",
        appointment_id,
    )

    rebooked = await book(db, slot_id, second)
    assert rebooked is not None


async def test_booked_slot_cannot_be_deleted_by_an_availability_change(
    db: asyncpg.Connection,
) -> None:
    """A provider shrinking their hours must not silently delete a booked patient's slot
    (edge case #8) — the delete has to fail loudly."""
    provider_id = await make_provider(db)
    slot_id = await make_slot(db, provider_id)
    patient_id = await make_patient(db, account_id="ACC-C")
    await book(db, slot_id, patient_id)

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await db.execute("DELETE FROM appointment_slots WHERE id = $1", slot_id)


async def test_repeated_booking_submissions_create_one_appointment(
    db: asyncpg.Connection,
) -> None:
    """A double-clicked or retried booking must not produce two appointments, deduped
    server-side rather than by a disabled button (edge case #10)."""
    provider_id = await make_provider(db)
    first_slot = await make_slot(db, provider_id, days_ahead=7)
    second_slot = await make_slot(db, provider_id, days_ahead=8)
    patient_id = await make_patient(db, account_id="ACC-D")

    await book(db, first_slot, patient_id, idempotency_key="submit-once")

    # Same key replayed against a different slot is still the same logical submission.
    with pytest.raises(asyncpg.UniqueViolationError):
        await book(db, second_slot, patient_id, idempotency_key="submit-once")


async def test_a_provider_cannot_hold_two_slots_at_one_instant(db: asyncpg.Connection) -> None:
    """Duplicate slots would show one time twice and let it be booked twice over."""
    provider_id = await make_provider(db)
    slot_id = await make_slot(db, provider_id)
    start = await db.fetchval("SELECT start_utc FROM appointment_slots WHERE id = $1", slot_id)

    with pytest.raises(asyncpg.UniqueViolationError):
        await db.execute(
            """
            INSERT INTO appointment_slots (provider_id, start_utc, end_utc)
            VALUES ($1, $2, $3)
            """,
            provider_id,
            start,
            start + timedelta(minutes=30),
        )
