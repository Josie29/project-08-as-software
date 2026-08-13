import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import BaseModel

from app.auth.jwt import SupabaseTokenVerifier, get_token_verifier
from app.config import get_settings
from app.main import app
from tests.support.tokens import StubResolver


class Clinic(BaseModel):
    """Ids for a minimal bookable clinic: one provider, their staff login, two patients."""

    provider_id: uuid.UUID
    staff_auth_id: uuid.UUID
    patient_id: uuid.UUID
    patient_auth_id: uuid.UUID
    neighbour_id: uuid.UUID
    neighbour_auth_id: uuid.UUID


async def _verify_identity(
    db: asyncpg.Connection, auth_user_id: uuid.UUID, patient_id: uuid.UUID
) -> None:
    """Link a login to a patient and insert a live identity verification.

    Bypasses the verification endpoint, which has its own tests, so these tests start from
    a verified session.

    Args:
        db: Database connection.
        auth_user_id: The signed-in caller.
        patient_id: The patient they are linked to.
    """
    now = datetime.now(UTC)
    await db.execute(
        "UPDATE patients SET auth_user_id = $1 WHERE id = $2", auth_user_id, patient_id
    )
    await db.execute(
        """
        INSERT INTO identity_verifications (auth_user_id, patient_id, verified_at, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        auth_user_id,
        patient_id,
        now,
        now + timedelta(minutes=30),
    )


@pytest.fixture
async def clinic(db: asyncpg.Connection) -> Clinic:
    """Create one provider with a staff login and two verified patients.

    Args:
        db: Connection to the migrated test database.

    Returns:
        The ids the scheduling tests act on.
    """
    provider_id = await db.fetchval(
        "INSERT INTO providers (display_name, timezone) VALUES ($1, $2) RETURNING id",
        "Dr Lee",
        "America/New_York",
    )
    staff_auth_id = uuid.uuid4()
    await db.execute(
        """
        INSERT INTO staff (auth_user_id, provider_id, role, email)
        VALUES ($1, $2, 'provider', $3)
        """,
        staff_auth_id,
        provider_id,
        "lee@clinic.test",
    )

    patients: list[tuple[uuid.UUID, uuid.UUID]] = []
    for account in ("SCH-001", "SCH-002"):
        patient_id = await db.fetchval(
            """
            INSERT INTO patients (account_id, date_of_birth, first_name, last_name, email)
            VALUES ($1, DATE '1990-01-01', 'Test', 'Patient', $2)
            RETURNING id
            """,
            account,
            f"{account}@example.test",
        )
        auth_id = uuid.uuid4()
        await _verify_identity(db, auth_id, patient_id)
        patients.append((patient_id, auth_id))

    return Clinic(
        provider_id=provider_id,
        staff_auth_id=staff_auth_id,
        patient_id=patients[0][0],
        patient_auth_id=patients[0][1],
        neighbour_id=patients[1][0],
        neighbour_auth_id=patients[1][1],
    )


@pytest.fixture
async def make_slot(db: asyncpg.Connection) -> Callable[..., Any]:
    """Return a factory inserting an open slot at a chosen offset from now.

    Args:
        db: Database connection.

    Returns:
        An async callable returning the new slot's id.
    """

    async def _make(provider_id: uuid.UUID, *, hours_ahead: float = 72) -> uuid.UUID:
        start = datetime.now(UTC) + timedelta(hours=hours_ahead)
        return await db.fetchval(
            """
            INSERT INTO appointment_slots (provider_id, start_utc, end_utc)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            provider_id,
            start,
            start + timedelta(minutes=30),
        )

    return _make


@pytest.fixture
async def api(signing_key: Any) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an API client whose token verifier trusts the test signing key.

    Args:
        signing_key: The session-scoped EC key pair.

    Yields:
        A client bound to the ASGI app.
    """
    app.dependency_overrides[get_token_verifier] = lambda: SupabaseTokenVerifier(
        get_settings(), resolver=StubResolver(signing_key.public_key())
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    app.dependency_overrides.clear()


@pytest.fixture
def headers(make_token: Any) -> Callable[[uuid.UUID], dict[str, str]]:
    """Return a factory building Authorization headers for a given subject.

    Args:
        make_token: Token factory from the auth fixtures.

    Returns:
        A callable producing headers.
    """

    def _headers(subject: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(sub=str(subject))}"}

    return _headers
