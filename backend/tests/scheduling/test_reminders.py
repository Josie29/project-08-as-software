import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session_factory
from app.services.email import EmailError
from app.services.reminders import dispatch_due_reminders, render_when
from tests.scheduling.conftest import Clinic


class RecordingSender:
    """An email transport that records what it was asked to send."""

    def __init__(self, *, fail: bool = False) -> None:
        """Initialise the recorder.

        Args:
            fail: Whether every send should raise, standing in for a Resend outage.
        """
        self.sent: list[tuple[str, str, str]] = []
        self._fail = fail

    async def send_appointment_reminder(self, recipient: str, when: str, link: str) -> str | None:
        """Record a reminder instead of sending it.

        Args:
            recipient: The patient's address.
            when: Rendered appointment time.
            link: Portal URL.

        Returns:
            A stub provider message id.

        Raises:
            EmailError: If this sender was built to fail.
        """
        if self._fail:
            raise EmailError("provider unavailable")
        self.sent.append((recipient, when, link))
        return f"msg-{len(self.sent)}"


@pytest.fixture
async def session(db: asyncpg.Connection) -> Any:
    """Yield an ORM session against the same migrated test database.

    Args:
        db: Keeps the truncating fixture in scope for the test's lifetime.

    Yields:
        An `AsyncSession`.
    """
    async with get_session_factory()() as orm_session:
        yield orm_session


async def _book(api: Any, slot_id: uuid.UUID, headers: dict[str, str]) -> str:
    """Book a slot through the API and return the appointment id.

    Args:
        api: API client.
        slot_id: The slot to book.
        headers: Caller's auth headers.

    Returns:
        The new appointment's id.
    """
    response = await api.post("/appointments", json={"slot_id": str(slot_id)}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


async def test_a_reminder_is_sent_for_an_appointment_inside_the_lead_window(
    api: Any,
    session: AsyncSession,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Without this the whole no-show reduction the brief costs out never happens
    (Core #15)."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=12)
    await _book(api, slot_id, headers(clinic.patient_auth_id))
    sender = RecordingSender()

    run = await dispatch_due_reminders(session, get_settings(), sender)  # pyright: ignore[reportArgumentType]

    assert run.due == 1
    assert run.sent == 1
    assert len(sender.sent) == 1


async def test_an_appointment_outside_the_lead_window_is_not_reminded_yet(
    api: Any,
    session: AsyncSession,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Reminding a week early defeats the purpose and trains patients to ignore them."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=96)
    await _book(api, slot_id, headers(clinic.patient_auth_id))
    sender = RecordingSender()

    run = await dispatch_due_reminders(session, get_settings(), sender)  # pyright: ignore[reportArgumentType]

    assert run.due == 0
    assert sender.sent == []


async def test_running_the_job_repeatedly_sends_exactly_one_reminder(
    api: Any,
    session: AsyncSession,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """The job has to be safe to run on a timer that may fire while a previous pass is
    still going. A second reminder for the same visit is the failure the brief calls out
    by name (edge case #9)."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=12)
    await _book(api, slot_id, headers(clinic.patient_auth_id))
    sender = RecordingSender()

    first = await dispatch_due_reminders(session, get_settings(), sender)  # pyright: ignore[reportArgumentType]
    second = await dispatch_due_reminders(session, get_settings(), sender)  # pyright: ignore[reportArgumentType]
    third = await dispatch_due_reminders(session, get_settings(), sender)  # pyright: ignore[reportArgumentType]

    assert first.sent == 1
    assert second.sent == 0 and second.skipped == 1
    assert third.sent == 0 and third.skipped == 1
    assert len(sender.sent) == 1


async def test_overlapping_runs_cannot_both_send(
    api: Any,
    clinic: Clinic,
    db: asyncpg.Connection,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Two passes genuinely in flight at once — a slow run overlapping the next tick, or
    two API replicas — must still produce one reminder. Idempotency is a database
    constraint, not a scheduler setting, so this holds however many run (edge case #9)."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=12)
    await _book(api, slot_id, headers(clinic.patient_auth_id))
    sender = RecordingSender()
    settings = get_settings()

    async def _pass() -> Any:
        async with get_session_factory()() as own_session:
            return await dispatch_due_reminders(own_session, settings, sender)  # pyright: ignore[reportArgumentType]

    runs = await asyncio.gather(*(_pass() for _ in range(5)))

    assert sum(run.sent for run in runs) == 1
    assert len(sender.sent) == 1
    rows = await db.fetchval("SELECT count(*) FROM reminder_sends WHERE kind = 'pre_visit_24h'")
    assert rows == 1


async def test_a_failed_send_is_recorded_and_not_silently_retried(
    api: Any,
    session: AsyncSession,
    clinic: Clinic,
    db: asyncpg.Connection,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A provider outage must leave an auditable record rather than an unhandled error,
    and must not turn into a duplicate on the next tick — the claim is already taken."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=12)
    await _book(api, slot_id, headers(clinic.patient_auth_id))

    failing = await dispatch_due_reminders(session, get_settings(), RecordingSender(fail=True))  # pyright: ignore[reportArgumentType]
    assert failing.failed == 1

    row = await db.fetchrow("SELECT status, error_detail FROM reminder_sends")
    assert row is not None
    assert row["status"] == "failed"
    assert row["error_detail"]

    # The next pass does not retry it, which is what keeps duplicates at zero.
    recovered = await dispatch_due_reminders(session, get_settings(), RecordingSender())  # pyright: ignore[reportArgumentType]
    assert recovered.sent == 0
    assert recovered.skipped == 1


async def test_a_cancelled_appointment_is_not_reminded(
    api: Any,
    session: AsyncSession,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Reminding someone to attend a visit they cancelled is exactly the kind of mistake
    that erodes trust in the portal.

    Cancelled from the staff side deliberately: inside the reminder window the patient's
    own minimum-notice rule has already closed, so the front desk is the only route to a
    late cancellation — and that is precisely when a stray reminder would go out.
    """
    slot_id = await make_slot(clinic.provider_id, hours_ahead=12)
    appointment_id = await _book(api, slot_id, headers(clinic.patient_auth_id))

    cancelled = await api.post(
        f"/provider/appointments/{appointment_id}/status",
        json={"status": "cancelled"},
        headers=headers(clinic.staff_auth_id),
    )
    assert cancelled.status_code == 200

    run = await dispatch_due_reminders(session, get_settings(), RecordingSender())  # pyright: ignore[reportArgumentType]

    assert run.due == 0


def test_the_appointment_time_is_rendered_in_the_clinics_zone() -> None:
    """A patient told the wrong hour arrives at the wrong time. The clinic's zone is the
    one that matters — it is where they physically have to be (edge case #6)."""
    # 18:30 UTC in January is 13:30 in New York, and the label must say so.
    winter = datetime(2026, 1, 15, 18, 30, tzinfo=UTC)
    rendered = render_when(winter, "America/New_York")

    assert "1:30 PM" in rendered
    assert "EST" in rendered

    # The same wall-clock reading in July must shift with daylight saving, not stay put.
    summer = datetime(2026, 7, 15, 18, 30, tzinfo=UTC)
    assert "2:30 PM" in render_when(summer, "America/New_York")
    assert "EDT" in render_when(summer, "America/New_York")
