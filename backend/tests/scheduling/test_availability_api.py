import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx

from tests.scheduling.conftest import Clinic

#: Mon-Fri 09:00-17:00 in 30-minute slots, the brief's worked example.
WEEKDAY_RULES = [
    {
        "weekday": weekday,
        "start_local": "09:00:00",
        "end_local": "17:00:00",
        "slot_minutes": 30,
    }
    for weekday in range(1, 6)
]


async def test_setting_working_hours_materialises_bookable_slots(
    api: httpx.AsyncClient,
    clinic: Clinic,
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Without materialisation a provider's stated hours produce nothing to book, so the
    whole scheduling flow is dead on arrival (Core #10)."""
    saved = await api.put(
        "/provider/availability",
        json={"rules": WEEKDAY_RULES},
        headers=headers(clinic.staff_auth_id),
    )

    assert saved.status_code == 200
    body = saved.json()
    assert len(body["rules"]) == 5
    # 16 half-hour slots per working day, over a 60-day horizon of weekdays.
    assert body["slots_created"] > 0

    offered = await api.get(
        f"/providers/{clinic.provider_id}/slots?days=7", headers=headers(clinic.patient_auth_id)
    )
    assert offered.status_code == 200
    assert len(offered.json()) > 0


async def test_resaving_the_same_hours_creates_no_duplicate_slots(
    api: httpx.AsyncClient,
    clinic: Clinic,
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Re-materialising has to be idempotent, or every save of an unchanged schedule
    doubles the slots on offer."""
    staff = headers(clinic.staff_auth_id)
    first = await api.put("/provider/availability", json={"rules": WEEKDAY_RULES}, headers=staff)
    second = await api.put("/provider/availability", json={"rules": WEEKDAY_RULES}, headers=staff)

    assert first.json()["slots_created"] > 0
    assert second.json()["slots_created"] == 0
    assert second.json()["slots_removed"] == 0


async def test_shrinking_hours_cannot_delete_a_booked_appointment(
    api: httpx.AsyncClient,
    clinic: Clinic,
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A provider trimming their hours must never silently drop a patient who already has
    that time. The edit is refused with a message naming the clash (edge case #8)."""
    staff = headers(clinic.staff_auth_id)
    patient = headers(clinic.patient_auth_id)
    await api.put("/provider/availability", json={"rules": WEEKDAY_RULES}, headers=staff)

    offered = await api.get(f"/providers/{clinic.provider_id}/slots", headers=patient)
    # The last offered slot of the horizon is late in the day, so shrinking the afternoon
    # is guaranteed to collide with it.
    target = offered.json()[-1]
    booked = await api.post("/appointments", json={"slot_id": target["id"]}, headers=patient)
    assert booked.status_code == 201

    shrunk = [{**rule, "end_local": "10:00:00"} for rule in WEEKDAY_RULES]
    refused = await api.put("/provider/availability", json={"rules": shrunk}, headers=staff)

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "booked_slot_conflict"

    # The appointment and its slot both survive the refused edit.
    still_there = await api.get("/appointments", headers=patient)
    assert len(still_there.json()) == 1
    assert still_there.json()[0]["status"] == "requested"


async def test_blocking_a_range_withdraws_the_free_slots_inside_it(
    api: httpx.AsyncClient,
    clinic: Clinic,
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Blocked time that still appears bookable is how a provider gets booked while away
    (Core #10)."""
    staff = headers(clinic.staff_auth_id)
    patient = headers(clinic.patient_auth_id)
    await api.put("/provider/availability", json={"rules": WEEKDAY_RULES}, headers=staff)

    before = await api.get(f"/providers/{clinic.provider_id}/slots?days=14", headers=patient)
    start = datetime.now(UTC) + timedelta(hours=1)
    blocked = await api.post(
        "/provider/blocks",
        json={
            "start_utc": start.isoformat(),
            "end_utc": (start + timedelta(days=10)).isoformat(),
            "reason": "Conference",
        },
        headers=staff,
    )

    assert blocked.status_code == 201
    assert blocked.json()["slots_removed"] > 0

    after = await api.get(f"/providers/{clinic.provider_id}/slots?days=14", headers=patient)
    assert len(after.json()) < len(before.json())


async def test_an_appointment_moves_through_the_lifecycle(
    api: httpx.AsyncClient,
    clinic: Clinic,
    db: asyncpg.Connection,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Requested to confirmed to completed is the ordinary path; if it does not work the
    clinic cannot record that a visit happened (Core #14)."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=72)
    staff = headers(clinic.staff_auth_id)
    booked = await api.post(
        "/appointments", json={"slot_id": str(slot_id)}, headers=headers(clinic.patient_auth_id)
    )
    appointment_id = booked.json()["id"]

    confirmed = await api.post(
        f"/provider/appointments/{appointment_id}/status",
        json={"status": "confirmed"},
        headers=staff,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"

    # Completion is only legitimate once the visit has started, so the slot moves into the
    # past rather than the test waiting for it.
    await db.execute(
        "UPDATE appointment_slots SET start_utc = now() - interval '1 hour' WHERE id = $1",
        slot_id,
    )
    completed = await api.post(
        f"/provider/appointments/{appointment_id}/status",
        json={"status": "completed"},
        headers=staff,
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


async def test_an_invalid_transition_is_rejected_server_side(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Invalid transitions must be refused with a clear error rather than silently ignored,
    or the status field stops meaning anything (edge case #11)."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=72)
    staff = headers(clinic.staff_auth_id)
    patient = headers(clinic.patient_auth_id)

    booked = await api.post("/appointments", json={"slot_id": str(slot_id)}, headers=patient)
    appointment_id = booked.json()["id"]
    await api.post(f"/appointments/{appointment_id}/cancel", json={}, headers=patient)

    revived = await api.post(
        f"/provider/appointments/{appointment_id}/status",
        json={"status": "completed"},
        headers=staff,
    )

    assert revived.status_code == 409
    assert revived.json()["detail"]["code"] == "invalid_transition"


async def test_staff_cannot_touch_another_providers_appointment(
    api: httpx.AsyncClient,
    clinic: Clinic,
    db: asyncpg.Connection,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A clinician sees only their own schedule. The provider is read from the staff row, so
    a colleague's appointment is invisible however the request is shaped."""
    other_provider = await db.fetchval(
        "INSERT INTO providers (display_name) VALUES ($1) RETURNING id", "Dr Other"
    )
    other_staff_auth = uuid.uuid4()
    await db.execute(
        """
        INSERT INTO staff (auth_user_id, provider_id, role, email)
        VALUES ($1, $2, 'provider', $3)
        """,
        other_staff_auth,
        other_provider,
        "other@clinic.test",
    )

    slot_id = await make_slot(clinic.provider_id, hours_ahead=72)
    booked = await api.post(
        "/appointments", json={"slot_id": str(slot_id)}, headers=headers(clinic.patient_auth_id)
    )
    appointment_id = booked.json()["id"]

    trespass = await api.post(
        f"/provider/appointments/{appointment_id}/status",
        json={"status": "confirmed"},
        headers=headers(other_staff_auth),
    )
    assert trespass.status_code == 404

    listed = await api.get("/provider/appointments", headers=headers(other_staff_auth))
    assert listed.json() == []


async def test_a_patient_cannot_reach_the_provider_endpoints(
    api: httpx.AsyncClient,
    clinic: Clinic,
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Availability management is staff-only. A patient holding a valid token must not be
    able to rewrite a clinic's working hours."""
    forbidden = await api.put(
        "/provider/availability",
        json={"rules": WEEKDAY_RULES},
        headers=headers(clinic.patient_auth_id),
    )

    assert forbidden.status_code == 403
