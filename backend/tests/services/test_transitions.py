from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import AppointmentStatus
from app.services.scheduling import check_transition, notice_shortfall

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(days=2)
PAST = NOW - timedelta(hours=2)


def test_a_cancelled_appointment_can_never_be_completed() -> None:
    """A cancelled visit later marked completed would bill a patient for care they never
    received and corrupt the clinic's attendance record (edge case #11)."""
    refusal = check_transition(AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, PAST, NOW)

    assert refusal is not None
    assert "final" in refusal.message


@pytest.mark.parametrize(
    "current",
    [AppointmentStatus.REQUESTED, AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED],
)
def test_no_show_applies_only_to_a_confirmed_appointment(current: AppointmentStatus) -> None:
    """No-show is a statement about a visit the clinic committed to. Allowing it from any
    other state lets a never-confirmed request count against a patient (edge case #11)."""
    assert check_transition(current, AppointmentStatus.NO_SHOW, PAST, NOW) is not None


def test_a_future_appointment_cannot_be_marked_no_show() -> None:
    """Marking a visit missed before it starts is a data-entry slip that would wrongly
    penalise the patient."""
    refusal = check_transition(AppointmentStatus.CONFIRMED, AppointmentStatus.NO_SHOW, FUTURE, NOW)

    assert refusal is not None
    assert "before it starts" in refusal.message


def test_a_confirmed_appointment_that_has_started_can_be_completed() -> None:
    """The ordinary happy path still has to pass, or the lifecycle is unusable."""
    assert (
        check_transition(AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED, PAST, NOW)
        is None
    )


def test_repeating_the_current_status_is_refused() -> None:
    """A double-clicked "confirm" should report plainly rather than appear to succeed
    twice and write a second audit entry."""
    refusal = check_transition(
        AppointmentStatus.CONFIRMED, AppointmentStatus.CONFIRMED, FUTURE, NOW
    )

    assert refusal is not None
    assert "already" in refusal.message


def test_notice_window_is_measured_against_the_start_time() -> None:
    """Catches an off-by-one that would let a patient cancel inside the notice window, or
    block them well outside it (Core #13)."""
    assert notice_shortfall(NOW + timedelta(hours=23), NOW, 24) is True
    assert notice_shortfall(NOW + timedelta(hours=25), NOW, 24) is False
    # A policy of zero notice must not accidentally block a still-future appointment.
    assert notice_shortfall(NOW + timedelta(minutes=1), NOW, 0) is False
