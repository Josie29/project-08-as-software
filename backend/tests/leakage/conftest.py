from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.auth.jwt import SupabaseTokenVerifier, get_token_verifier
from app.config import get_settings
from app.main import app
from app.seed import rows
from app.seed.profiles import Profile, build_plan
from tests.support.tokens import StubResolver


@pytest.fixture
async def seeded(db: asyncpg.Connection) -> dict[str, Any]:
    """Seed the demo dataset and return the ids the leakage tests need.

    Uses the real seed rather than bespoke fixtures so the tests run against the same data a
    reviewer sees, including the cancelled study whose images must stay unreachable.

    Args:
        db: Connection to the migrated test database.

    Returns:
        Ids for the demo patient, the neighbour patient, and their resources.
    """
    plan = build_plan(Profile.DEMO, datetime.now(UTC))
    await rows.insert_plan(db, plan)

    demo, neighbour = plan.patients[0], plan.patients[1]
    completed = [s for s in demo.studies if s.status.value == "completed"]
    cancelled = [s for s in demo.studies if s.status.value == "cancelled"]
    neighbour_study = neighbour.studies[0]

    # The two demo clips differ on purpose: one is whole, one has frames marked MISSING.
    whole_clip = completed[0].clips[0]
    damaged_clip = next(
        s.clips[0] for s in completed if any(f.integrity != "ok" for f in s.clips[0].frames)
    )

    return {
        "demo_patient_id": demo.id,
        "demo_account_id": demo.account_id,
        "demo_dob": demo.date_of_birth,
        "demo_study_id": completed[0].id,
        "demo_image_id": completed[0].images[0].id,
        "cancelled_study_id": cancelled[0].id,
        "cancelled_image_id": cancelled[0].images[0].id,
        "neighbour_patient_id": neighbour.id,
        "neighbour_account_id": neighbour.account_id,
        "neighbour_study_id": neighbour_study.id,
        "neighbour_image_id": neighbour_study.images[0].id,
        "neighbour_clip_id": neighbour_study.clips[0].id,
        "demo_clip_id": whole_clip.id,
        "demo_clip_frame_count": whole_clip.frame_count,
        "damaged_clip_id": damaged_clip.id,
        "damaged_clip_missing": tuple(
            frame.sequence for frame in damaged_clip.frames if frame.integrity != "ok"
        ),
    }


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
def auth_headers(make_token: Any) -> Callable[..., dict[str, str]]:
    """Return a factory building Authorization headers for a given subject.

    Args:
        make_token: Token factory from the auth fixtures.

    Returns:
        A callable producing headers.
    """

    def _headers(subject: UUID | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(sub=str(subject or uuid4()))}"}

    return _headers


async def verify_identity(
    db: asyncpg.Connection, auth_user_id: UUID, patient_id: UUID, *, minutes: int = 30
) -> None:
    """Insert a live identity verification directly, bypassing the endpoint.

    Lets access-control tests start from a verified session without re-exercising the
    verification flow, which has its own tests.

    Args:
        db: Database connection.
        auth_user_id: The signed-in caller.
        patient_id: The patient they are linked to.
        minutes: Lifetime of the verification.
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
        now + timedelta(minutes=minutes),
    )
