from datetime import date, time

import pytest

from app.services.scheduling import SlotRule, generate_slots

#: 2026 US daylight-saving transitions for America/New_York.
SPRING_FORWARD = date(2026, 3, 8)
FALL_BACK = date(2026, 11, 1)
EASTERN = "America/New_York"


def test_a_normal_working_day_yields_evenly_spaced_slots() -> None:
    """The baseline a patient sees: 9-5 in 30-minute slots is 16 bookable times."""
    rule = SlotRule(weekday=1, start_local=time(9), end_local=time(17), slot_minutes=30)

    slots = list(generate_slots(rule, date(2026, 3, 2), date(2026, 3, 2), EASTERN))

    assert len(slots) == 16
    assert slots[0].start_utc.hour == 14  # 09:00 EST is 14:00 UTC
    assert all(slot.end_utc > slot.start_utc for slot in slots)


def test_spring_forward_day_loses_exactly_the_skipped_hour() -> None:
    """A clinic working 00:00-06:00 on the spring-forward date works five real hours, not
    six. Incrementing wall-clock time instead would emit slots for an hour that does not
    exist, and every one of them would be unbookable in practice.
    """
    rule = SlotRule(weekday=7, start_local=time(0), end_local=time(6), slot_minutes=30)

    slots = list(generate_slots(rule, SPRING_FORWARD, SPRING_FORWARD, EASTERN))

    assert len(slots) == 10  # five real hours, not six


def test_fall_back_day_gains_exactly_the_repeated_hour() -> None:
    """The same window on the fall-back date is seven real hours. The repeated local hour
    is two genuinely different instants, so both are bookable and neither is a duplicate.
    """
    rule = SlotRule(weekday=7, start_local=time(0), end_local=time(6), slot_minutes=30)

    slots = list(generate_slots(rule, FALL_BACK, FALL_BACK, EASTERN))

    assert len(slots) == 14  # seven real hours


def test_generated_slots_are_always_distinct_and_ascending() -> None:
    """A duplicated instant would collide with the unique constraint on
    (provider_id, start_utc) and abort slot generation partway through.
    """
    rule = SlotRule(weekday=7, start_local=time(0), end_local=time(6), slot_minutes=30)

    for day in (SPRING_FORWARD, FALL_BACK):
        starts = [slot.start_utc for slot in generate_slots(rule, day, day, EASTERN)]

        assert len(starts) == len(set(starts)), f"duplicate slot instants on {day}"
        assert starts == sorted(starts)


def test_only_the_rules_weekday_produces_slots() -> None:
    """A Monday rule leaking into other days would offer patients times the provider
    never said they were available."""
    rule = SlotRule(weekday=1, start_local=time(9), end_local=time(11), slot_minutes=60)

    slots = list(generate_slots(rule, date(2026, 3, 2), date(2026, 3, 15), EASTERN))

    assert len(slots) == 4  # two Mondays, two slots each


def test_a_trailing_partial_slot_is_not_offered() -> None:
    """A 45-minute window with 30-minute slots must yield one slot, not two — the second
    would run past the provider's stated end time.
    """
    rule = SlotRule(weekday=1, start_local=time(9), end_local=time(9, 45), slot_minutes=30)

    slots = list(generate_slots(rule, date(2026, 3, 2), date(2026, 3, 2), EASTERN))

    assert len(slots) == 1


def test_an_inverted_date_range_is_rejected() -> None:
    """Silently returning nothing would look like a provider with no availability rather
    than a caller bug."""
    rule = SlotRule(weekday=1, start_local=time(9), end_local=time(17), slot_minutes=30)

    with pytest.raises(ValueError, match="must not precede"):
        list(generate_slots(rule, date(2026, 3, 10), date(2026, 3, 1), EASTERN))
