from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field


class SlotWindow(BaseModel):
    """A single generated bookable slot, as an absolute instant."""

    start_utc: datetime
    end_utc: datetime


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
