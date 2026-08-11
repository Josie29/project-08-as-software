import asyncio
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum, auto
from uuid import UUID

import structlog
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.identity import IdentityAttempt, IdentityVerification, Patient

logger = structlog.get_logger(__name__)

#: Every response from the verification endpoint is padded to this duration. A real
#: constant-time implementation is not achievable in Python, but a fixed floor swamps the
#: microsecond difference between "no such account" and "wrong date of birth", and throttles
#: online guessing at the same time. It applies to success, failure and lockout alike: a
#: fast rejection and a slow one are themselves an oracle.
RESPONSE_FLOOR_SECONDS = 0.25


class VerificationOutcome(StrEnum):
    """Result of an identity attempt. Only VERIFIED is ever distinguishable to the caller."""

    VERIFIED = auto()
    MISMATCH = auto()
    LOCKED_OUT = auto()


class LockoutState(BaseModel):
    """Whether attempts are currently barred, and for how long."""

    locked: bool
    retry_after_seconds: int


class VerificationResult(BaseModel):
    """Outcome of one verification attempt."""

    outcome: VerificationOutcome
    patient_id: UUID | None = None
    retry_after_seconds: int = 0


#: Counts recent failures in two independent buckets and returns the worse of the two.
#:
#: The account bucket is what makes lockout meaningful. A per-login bucket alone is bypassed
#: by signing up again — Supabase self-signup is unlimited — so it protects nothing about a
#: targeted patient. Keying on the submitted account id closes that, at the cost of letting
#: someone lock out an account id they know. The account threshold is therefore set higher.
#:
#: Failures are counted only since the most recent success, so a legitimate patient who
#: fixes a typo is not still one attempt from lockout.
_LOCKOUT_SQL = text("""
WITH recent AS (
    SELECT auth_user_id, submitted_account_id, succeeded, created_at
    FROM identity_attempts
    WHERE created_at >= now() - make_interval(mins => :window_minutes)
      AND (auth_user_id = :auth_user_id OR submitted_account_id = :account_id)
),
user_bucket AS (
    SELECT count(*) AS failures, max(created_at) AS last_failure_at
    FROM recent
    WHERE auth_user_id = :auth_user_id
      AND NOT succeeded
      AND created_at > COALESCE(
          (SELECT max(created_at) FROM recent WHERE auth_user_id = :auth_user_id AND succeeded),
          '-infinity'::timestamptz)
),
account_bucket AS (
    SELECT count(*) AS failures, max(created_at) AS last_failure_at
    FROM recent
    WHERE submitted_account_id = :account_id
      AND NOT succeeded
      AND created_at > COALESCE(
          (SELECT max(created_at) FROM recent
           WHERE submitted_account_id = :account_id AND succeeded),
          '-infinity'::timestamptz)
)
SELECT
    u.failures AS user_failures,
    a.failures AS account_failures,
    GREATEST(
        COALESCE(u.last_failure_at, '-infinity'::timestamptz),
        COALESCE(a.last_failure_at, '-infinity'::timestamptz)
    ) AS last_failure_at
FROM user_bucket u CROSS JOIN account_bucket a
""")


async def check_lockout(
    session: AsyncSession, settings: Settings, auth_user_id: UUID, account_id: str
) -> LockoutState:
    """Report whether further attempts are barred.

    Args:
        session: Database session.
        settings: Supplies the attempt threshold and window.
        auth_user_id: The signed-in caller.
        account_id: The account id being submitted.

    Returns:
        Whether attempts are locked and the retry delay.
    """
    row = (
        await session.execute(
            _LOCKOUT_SQL,
            {
                "window_minutes": settings.identity_lockout_minutes,
                "auth_user_id": auth_user_id,
                "account_id": account_id,
            },
        )
    ).one()

    # A known account id can be locked by anyone who knows it, so the account bucket is
    # given more headroom than the per-login one.
    account_threshold = settings.identity_max_attempts * 3
    locked = (
        row.user_failures >= settings.identity_max_attempts
        or row.account_failures >= account_threshold
    )
    if not locked or row.last_failure_at is None:
        return LockoutState(locked=False, retry_after_seconds=0)

    unlock_at = row.last_failure_at + timedelta(minutes=settings.identity_lockout_minutes)
    remaining = max(0, int((unlock_at - datetime.now(UTC)).total_seconds()))
    return LockoutState(locked=remaining > 0, retry_after_seconds=remaining)


async def attempt_verification(
    session: AsyncSession,
    settings: Settings,
    *,
    auth_user_id: UUID,
    account_id: str,
    date_of_birth: date,
) -> VerificationResult:
    """Attempt to link a signed-in user to their clinical record.

    Both factors are matched in a single query so that "no such account" and "wrong date of
    birth" follow an identical code path — there is no branch whose extra work could be
    timed, and no place for a well-meaning change to start reporting which field was wrong.

    Args:
        session: Database session.
        settings: Supplies thresholds and the verification lifetime.
        auth_user_id: The signed-in caller.
        account_id: Submitted account identifier.
        date_of_birth: Submitted date of birth.

    Returns:
        The outcome, carrying the patient id only on success.
    """
    lockout = await check_lockout(session, settings, auth_user_id, account_id)
    if lockout.locked:
        await _record_attempt(session, auth_user_id, account_id, succeeded=False)
        await session.commit()
        logger.info("identity.locked_out", auth_user_uuid=str(auth_user_id))
        return VerificationResult(
            outcome=VerificationOutcome.LOCKED_OUT,
            retry_after_seconds=lockout.retry_after_seconds,
        )

    matched = await session.execute(
        select(Patient.id, Patient.auth_user_id).where(
            Patient.account_id == account_id, Patient.date_of_birth == date_of_birth
        )
    )
    row = matched.first()

    if row is None or (row.auth_user_id is not None and row.auth_user_id != auth_user_id):
        # A record already linked to a different login is a takeover signal, but it must be
        # indistinguishable from any other failure to the caller.
        await _record_attempt(session, auth_user_id, account_id, succeeded=False)
        await session.commit()
        logger.info(
            "identity.mismatch",
            auth_user_uuid=str(auth_user_id),
            already_linked=row is not None,
        )
        return VerificationResult(outcome=VerificationOutcome.MISMATCH)

    now = datetime.now(UTC)
    # Supersede any earlier live verification so one login can never hold two scopes.
    await session.execute(
        update(IdentityVerification)
        .where(
            IdentityVerification.auth_user_id == auth_user_id,
            IdentityVerification.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.execute(
        update(Patient).where(Patient.id == row.id).values(auth_user_id=auth_user_id)
    )
    session.add(
        IdentityVerification(
            auth_user_id=auth_user_id,
            patient_id=row.id,
            verified_at=now,
            expires_at=now + timedelta(minutes=settings.identity_verification_ttl_minutes),
        )
    )
    await _record_attempt(session, auth_user_id, account_id, succeeded=True)
    await session.commit()

    logger.info("identity.verified", auth_user_uuid=str(auth_user_id), patient_uuid=str(row.id))
    return VerificationResult(outcome=VerificationOutcome.VERIFIED, patient_id=row.id)


async def _record_attempt(
    session: AsyncSession, auth_user_id: UUID, account_id: str, *, succeeded: bool
) -> None:
    """Persist one attempt so lockout survives restarts and holds across API instances.

    Args:
        session: Database session.
        auth_user_id: The signed-in caller.
        account_id: The submitted account id.
        succeeded: Whether the attempt matched.
    """
    session.add(
        IdentityAttempt(
            auth_user_id=auth_user_id,
            submitted_account_id=account_id,
            succeeded=succeeded,
        )
    )


async def sleep_until_response_floor(started_at: float) -> None:
    """Pad handling out to a fixed minimum duration.

    Args:
        started_at: Loop time when handling began.
    """
    elapsed = asyncio.get_running_loop().time() - started_at
    if elapsed < RESPONSE_FLOOR_SECONDS:
        await asyncio.sleep(RESPONSE_FLOOR_SECONDS - elapsed)
