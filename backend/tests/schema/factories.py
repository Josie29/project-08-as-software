import uuid
from datetime import UTC, datetime, timedelta

import asyncpg


async def make_provider(conn: asyncpg.Connection, *, name: str = "Dr Lee") -> uuid.UUID:
    """Insert a provider and return its id.

    Args:
        conn: Open database connection.
        name: Display name for the provider.

    Returns:
        The new provider's id.
    """
    return await conn.fetchval(
        "INSERT INTO providers (display_name) VALUES ($1) RETURNING id", name
    )


async def make_patient(conn: asyncpg.Connection, *, account_id: str) -> uuid.UUID:
    """Insert a patient and return its id.

    Args:
        conn: Open database connection.
        account_id: The clinic-facing account identifier, which must be unique.

    Returns:
        The new patient's id.
    """
    return await conn.fetchval(
        """
        INSERT INTO patients (account_id, date_of_birth, first_name, last_name, email)
        VALUES ($1, DATE '1988-03-14', 'Test', 'Patient', $2)
        RETURNING id
        """,
        account_id,
        f"{account_id}@example.test",
    )


async def make_slot(
    conn: asyncpg.Connection, provider_id: uuid.UUID, *, days_ahead: int = 7
) -> uuid.UUID:
    """Insert a future open slot for a provider and return its id.

    Args:
        conn: Open database connection.
        provider_id: Owning provider.
        days_ahead: How far in the future the slot starts.

    Returns:
        The new slot's id.
    """
    start = datetime.now(UTC) + timedelta(days=days_ahead)
    return await conn.fetchval(
        """
        INSERT INTO appointment_slots (provider_id, start_utc, end_utc)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        provider_id,
        start,
        start + timedelta(minutes=30),
    )


async def book(
    conn: asyncpg.Connection,
    slot_id: uuid.UUID,
    patient_id: uuid.UUID,
    *,
    status: str = "confirmed",
    idempotency_key: str | None = None,
) -> uuid.UUID:
    """Insert an appointment against a slot and return its id.

    Args:
        conn: Open database connection.
        slot_id: Slot being booked.
        patient_id: Patient booking it.
        status: Appointment status to create it in.
        idempotency_key: Optional client-supplied deduplication key.

    Returns:
        The new appointment's id.

    Raises:
        asyncpg.UniqueViolationError: If the slot already holds a live appointment.
    """
    return await conn.fetchval(
        """
        INSERT INTO appointments (slot_id, patient_id, status, booked_at, idempotency_key)
        VALUES ($1, $2, $3, now(), $4)
        RETURNING id
        """,
        slot_id,
        patient_id,
        status,
        idempotency_key,
    )
