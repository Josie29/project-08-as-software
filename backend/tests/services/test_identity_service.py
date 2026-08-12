from datetime import UTC, datetime, timedelta
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.seed import rows
from app.seed.profiles import Profile, build_plan
from app.services.identity import (
    VerificationOutcome,
    attempt_verification,
    check_lockout,
)
from tests.conftest import asyncpg_dsn


@pytest.fixture
async def session(db: asyncpg.Connection):
    """Yield an ORM session against the migrated test database.

    The service takes a SQLAlchemy session, so these tests drive it directly rather than
    through HTTP — the endpoint has its own tests.

    Yields:
        An `AsyncSession`.
    """
    engine = create_async_engine(get_settings().sqlalchemy_url, pool_size=1, max_overflow=1)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as active:
        yield active
    await engine.dispose()


@pytest.fixture
async def seeded_patient(db: asyncpg.Connection) -> dict[str, object]:
    """Seed the demo dataset and return the primary patient's identifying details.

    Args:
        db: Connection to the migrated test database.

    Returns:
        The account id, date of birth, and patient id.
    """
    plan = build_plan(Profile.DEMO, datetime.now(UTC))
    await rows.insert_plan(db, plan)
    patient = plan.patients[0]
    return {
        "account_id": patient.account_id,
        "date_of_birth": patient.date_of_birth,
        "patient_id": patient.id,
    }


async def test_matching_details_link_the_login_to_the_record(
    session: AsyncSession, seeded_patient: dict[str, object]
) -> None:
    """This is the moment a portal account becomes a patient. If the link were not written,
    the caller would pass verification and still see nothing."""
    caller = uuid4()

    result = await attempt_verification(
        session,
        get_settings(),
        auth_user_id=caller,
        account_id=str(seeded_patient["account_id"]),
        date_of_birth=seeded_patient["date_of_birth"],  # type: ignore[arg-type]
    )

    assert result.outcome is VerificationOutcome.VERIFIED
    assert result.patient_id == seeded_patient["patient_id"]


async def test_a_wrong_date_of_birth_does_not_link_anything(
    session: AsyncSession, seeded_patient: dict[str, object]
) -> None:
    """Knowing only the account id — which is printed on paperwork anyone might see — must
    not be enough to claim a record."""
    result = await attempt_verification(
        session,
        get_settings(),
        auth_user_id=uuid4(),
        account_id=str(seeded_patient["account_id"]),
        date_of_birth=datetime(1900, 1, 1).date(),
    )

    assert result.outcome is VerificationOutcome.MISMATCH
    assert result.patient_id is None


async def test_a_record_claimed_by_another_login_cannot_be_taken_over(
    session: AsyncSession, seeded_patient: dict[str, object]
) -> None:
    """Once a record belongs to a login, a second person with the same paperwork must not
    be able to attach themselves to it."""
    settings = get_settings()
    first = uuid4()
    await attempt_verification(
        session,
        settings,
        auth_user_id=first,
        account_id=str(seeded_patient["account_id"]),
        date_of_birth=seeded_patient["date_of_birth"],  # type: ignore[arg-type]
    )

    second = await attempt_verification(
        session,
        settings,
        auth_user_id=uuid4(),
        account_id=str(seeded_patient["account_id"]),
        date_of_birth=seeded_patient["date_of_birth"],  # type: ignore[arg-type]
    )

    assert second.outcome is VerificationOutcome.MISMATCH


async def test_reverifying_supersedes_the_previous_verification(
    session: AsyncSession, db: asyncpg.Connection, seeded_patient: dict[str, object]
) -> None:
    """One login must never hold two live verifications, or the scope it resolves to
    depends on which row sorts first."""
    settings = get_settings()
    caller = uuid4()
    for _ in range(2):
        await attempt_verification(
            session,
            settings,
            auth_user_id=caller,
            account_id=str(seeded_patient["account_id"]),
            date_of_birth=seeded_patient["date_of_birth"],  # type: ignore[arg-type]
        )

    live = await db.fetchval(
        """
        SELECT count(*) FROM identity_verifications
        WHERE auth_user_id = $1 AND revoked_at IS NULL
        """,
        caller,
    )
    assert live == 1


async def test_repeated_failures_lock_the_account_out(
    session: AsyncSession, seeded_patient: dict[str, object]
) -> None:
    """Without lockout the date of birth is brute-forceable: a few tens of thousands of
    plausible values against an account id printed on paperwork."""
    settings = get_settings()
    caller = uuid4()
    account = str(seeded_patient["account_id"])

    for _ in range(settings.identity_max_attempts):
        await attempt_verification(
            session,
            settings,
            auth_user_id=caller,
            account_id=account,
            date_of_birth=datetime(1900, 1, 1).date(),
        )

    result = await attempt_verification(
        session,
        settings,
        auth_user_id=caller,
        account_id=account,
        date_of_birth=seeded_patient["date_of_birth"],  # type: ignore[arg-type]
    )

    # Locked out even with the correct details: the lock is on the attempt rate, not on
    # whether this particular guess happened to be right.
    assert result.outcome is VerificationOutcome.LOCKED_OUT
    assert result.retry_after_seconds > 0


async def test_a_success_resets_the_failure_count(
    session: AsyncSession, seeded_patient: dict[str, object]
) -> None:
    """A patient who mistypes once, succeeds, then mistypes again should not be one attempt
    from a lockout inherited from before they got in."""
    settings = get_settings()
    caller = uuid4()
    account = str(seeded_patient["account_id"])

    await attempt_verification(
        session,
        settings,
        auth_user_id=caller,
        account_id=account,
        date_of_birth=datetime(1900, 1, 1).date(),
    )
    await attempt_verification(
        session,
        settings,
        auth_user_id=caller,
        account_id=account,
        date_of_birth=seeded_patient["date_of_birth"],  # type: ignore[arg-type]
    )

    state = await check_lockout(session, settings, caller, account)

    assert state.locked is False


async def test_lockout_is_clear_for_an_untouched_account(session: AsyncSession) -> None:
    """The happy path: someone verifying for the first time is never pre-locked."""
    state = await check_lockout(session, get_settings(), uuid4(), "AS-999999")

    assert state.locked is False
    assert state.retry_after_seconds == 0


async def test_the_lockout_window_is_bounded(
    session: AsyncSession, db: asyncpg.Connection, seeded_patient: dict[str, object]
) -> None:
    """Failures age out, or a patient who mistyped last week would still be locked today."""
    settings = get_settings()
    caller = uuid4()
    account = str(seeded_patient["account_id"])

    stale = datetime.now(UTC) - timedelta(minutes=settings.identity_lockout_minutes + 30)
    for _ in range(settings.identity_max_attempts + 2):
        await db.execute(
            """
            INSERT INTO identity_attempts
                (auth_user_id, submitted_account_id, succeeded, created_at, updated_at)
            VALUES ($1, $2, false, $3, $3)
            """,
            caller,
            account,
            stale,
        )

    state = await check_lockout(session, settings, caller, account)

    assert state.locked is False


async def test_the_dsn_helper_strips_the_driver_suffix() -> None:
    """asyncpg rejects SQLAlchemy's `postgresql+asyncpg://` scheme, so every raw connection
    in the suite depends on this conversion."""
    assert asyncpg_dsn().startswith("postgresql://")
