from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.models.enums import AppointmentStatus

#: Which status an appointment may move to from its current one (Core #14).
#:
#: Terminal states map to an empty set, so "cancelled cannot later be completed" is a
#: property of the table rather than a rule written out separately somewhere.
ALLOWED_TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    AppointmentStatus.REQUESTED: frozenset(
        {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED}
    ),
    AppointmentStatus.CONFIRMED: frozenset(
        {
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
            AppointmentStatus.NO_SHOW,
        }
    ),
    AppointmentStatus.COMPLETED: frozenset(),
    AppointmentStatus.CANCELLED: frozenset(),
    AppointmentStatus.NO_SHOW: frozenset(),
}

#: Statuses that only make sense once the appointment's start time has passed. Marking a
#: future visit as attended or missed is a data-entry slip, not a legitimate transition.
_REQUIRES_ELAPSED_START = frozenset({AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW})


class SlotWindow(BaseModel):
    """A single generated bookable slot, as an absolute instant."""

    start_utc: datetime
    end_utc: datetime


class TransitionRefusal(BaseModel):
    """Why a status change was refused, phrased for the caller."""

    message: str


def check_transition(
    current: AppointmentStatus,
    target: AppointmentStatus,
    slot_start_utc: datetime,
    now: datetime,
) -> TransitionRefusal | None:
    """Validate a proposed appointment status change.

    Args:
        current: The appointment's present status.
        target: The status being requested.
        slot_start_utc: When the booked slot starts.
        now: Current time, injected so the rule is testable.

    Returns:
        A refusal explaining the problem, or None if the transition is allowed.
    """
    if target == current:
        return TransitionRefusal(message=f"This appointment is already {current.value}.")

    if target not in ALLOWED_TRANSITIONS[current]:
        if not ALLOWED_TRANSITIONS[current]:
            return TransitionRefusal(
                message=f"A {current.value} appointment is final and cannot be changed."
            )
        return TransitionRefusal(
            message=f"An appointment cannot go from {current.value} to {target.value}."
        )

    if target in _REQUIRES_ELAPSED_START and slot_start_utc > now:
        return TransitionRefusal(
            message=f"This appointment cannot be marked {target.value} before it starts."
        )

    return None


def notice_shortfall(slot_start_utc: datetime, now: datetime, min_notice_hours: int) -> bool:
    """Report whether a patient-initiated change falls inside the minimum-notice window.

    Args:
        slot_start_utc: When the booked slot starts.
        now: Current time, injected so the rule is testable.
        min_notice_hours: Hours of notice the clinic requires.

    Returns:
        True if the change is too late to be allowed.
    """
    return slot_start_utc - now < timedelta(hours=min_notice_hours)


class SlotRule(BaseModel):
    """Recurring working hours for one weekday, in a provider's local wall-clock time."""

    weekday: int = Field(ge=1, le=7, description="ISO weekday, 1 = Monday")
    start_local: time
    end_local: time
    slot_minutes: int = Field(ge=5, le=240)


def _local_instant(day: date, wall_clock: time, zone: ZoneInfo) -> datetime:
    """Resolve a local wall-clock time on a date to an absolute instant.

    Args:
        day: The local calendar date.
        wall_clock: The local time of day.
        zone: The provider's timezone.

    Returns:
        The corresponding timezone-aware instant.
    """
    return datetime.combine(day, wall_clock, tzinfo=zone)


def generate_slots(rule: SlotRule, start: date, end: date, timezone: str) -> Iterator[SlotWindow]:
    """Generate bookable slots for a rule across a date range.

    Slot boundaries advance in absolute time between the rule's local start and end
    instants, rather than by incrementing wall-clock time. That is what makes daylight
    saving correct: on a spring-forward day the working window is genuinely an hour
    shorter and yields fewer slots, and on a fall-back day an hour longer and yields more,
    with every slot a distinct real instant. Incrementing local time instead would produce
    a duplicated or skipped hour.

    Args:
        rule: The working-hours rule to expand.
        start: First local date to consider, inclusive.
        end: Last local date to consider, inclusive.
        timezone: IANA timezone name the rule's times are expressed in.

    Yields:
        Slots in ascending order, with UTC boundaries.

    Raises:
        ValueError: If `end` precedes `start`.
    """
    if end < start:
        raise ValueError("end date must not precede start date")

    zone = ZoneInfo(timezone)
    duration = timedelta(minutes=rule.slot_minutes)

    day = start
    while day <= end:
        if day.isoweekday() == rule.weekday:
            window_start = _local_instant(day, rule.start_local, zone).astimezone(UTC)
            window_end = _local_instant(day, rule.end_local, zone).astimezone(UTC)

            cursor = window_start
            while cursor + duration <= window_end:
                yield SlotWindow(start_utc=cursor, end_utc=cursor + duration)
                cursor += duration
        day += timedelta(days=1)
