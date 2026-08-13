import uuid
from collections.abc import Callable
from typing import Any

import httpx

from tests.scheduling.conftest import Clinic


async def _open_slot_ids(
    api: httpx.AsyncClient, headers: dict[str, str], provider_id: uuid.UUID
) -> list[str]:
    """Return the ids currently offered as open for a provider.

    Args:
        api: API client.
        headers: Caller's auth headers.
        provider_id: The provider to query.

    Returns:
        Slot ids in the order the API offers them.
    """
    response = await api.get(f"/providers/{provider_id}/slots", headers=headers)
    assert response.status_code == 200
    return [slot["id"] for slot in response.json()]


async def test_booking_a_slot_removes_it_from_the_open_list(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A slot still offered after someone books it sends two patients to the same
    appointment time (Core #11)."""
    slot_id = await make_slot(clinic.provider_id)
    patient = headers(clinic.patient_auth_id)

    assert str(slot_id) in await _open_slot_ids(api, patient, clinic.provider_id)

    booked = await api.post("/appointments", json={"slot_id": str(slot_id)}, headers=patient)
    assert booked.status_code == 201
    assert booked.json()["status"] == "requested"

    assert str(slot_id) not in await _open_slot_ids(api, patient, clinic.provider_id)


async def test_a_second_patient_booking_a_taken_slot_is_refused(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """The loser of a booking race must get a clear conflict, not a 500 and not a silent
    second appointment (Core #12)."""
    slot_id = await make_slot(clinic.provider_id)

    first = await api.post(
        "/appointments", json={"slot_id": str(slot_id)}, headers=headers(clinic.patient_auth_id)
    )
    assert first.status_code == 201

    second = await api.post(
        "/appointments", json={"slot_id": str(slot_id)}, headers=headers(clinic.neighbour_auth_id)
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] in {"slot_taken", "slot_unavailable"}


async def test_replaying_a_submission_key_returns_the_same_appointment(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A double-clicked book button must not create two appointments. Deduplicated
    server-side, so a retried request is safe too (edge case #10)."""
    slot_id = await make_slot(clinic.provider_id)
    patient = headers(clinic.patient_auth_id)
    payload = {"slot_id": str(slot_id), "idempotency_key": "submit-once"}

    first = await api.post("/appointments", json=payload, headers=patient)
    second = await api.post("/appointments", json=payload, headers=patient)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = await api.get("/appointments", headers=patient)
    assert len(listed.json()) == 1


async def test_cancelling_returns_the_slot_to_the_open_list(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A cancelled appointment that leaves its slot unbookable quietly loses the clinic
    revenue and the next patient an opening (Core #13)."""
    slot_id = await make_slot(clinic.provider_id)
    patient = headers(clinic.patient_auth_id)

    booked = await api.post("/appointments", json={"slot_id": str(slot_id)}, headers=patient)
    appointment_id = booked.json()["id"]

    cancelled = await api.post(
        f"/appointments/{appointment_id}/cancel", json={"reason": "conflict"}, headers=patient
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None

    assert str(slot_id) in await _open_slot_ids(api, patient, clinic.provider_id)


async def test_cancelling_inside_the_notice_window_is_refused(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """The minimum-notice rule has to hold server-side; hiding the button is not
    enforcement, and a direct request would otherwise slip through (Core #13)."""
    slot_id = await make_slot(clinic.provider_id, hours_ahead=2)
    patient = headers(clinic.patient_auth_id)

    booked = await api.post("/appointments", json={"slot_id": str(slot_id)}, headers=patient)
    appointment_id = booked.json()["id"]

    refused = await api.post(f"/appointments/{appointment_id}/cancel", json={}, headers=patient)
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "too_late"


async def test_rescheduling_frees_the_original_slot(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Moving an appointment without releasing the old slot silently burns clinic capacity
    every time a patient reschedules (Core #13)."""
    original = await make_slot(clinic.provider_id, hours_ahead=72)
    target = await make_slot(clinic.provider_id, hours_ahead=96)
    patient = headers(clinic.patient_auth_id)

    booked = await api.post("/appointments", json={"slot_id": str(original)}, headers=patient)
    appointment_id = booked.json()["id"]

    moved = await api.post(
        f"/appointments/{appointment_id}/reschedule",
        json={"slot_id": str(target)},
        headers=patient,
    )
    assert moved.status_code == 200
    assert moved.json()["slot_id"] == str(target)

    offered = await _open_slot_ids(api, patient, clinic.provider_id)
    assert str(original) in offered
    assert str(target) not in offered


async def test_rescheduling_into_a_taken_slot_is_refused(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """The move is one UPDATE, so a collision surfaces as a constraint violation rather
    than a check. It has to answer 409 and leave the original booking intact — not 500,
    and not a patient holding neither slot."""
    original = await make_slot(clinic.provider_id, hours_ahead=72)
    contested = await make_slot(clinic.provider_id, hours_ahead=96)
    patient = headers(clinic.patient_auth_id)

    booked = await api.post("/appointments", json={"slot_id": str(original)}, headers=patient)
    appointment_id = booked.json()["id"]
    await api.post(
        "/appointments",
        json={"slot_id": str(contested)},
        headers=headers(clinic.neighbour_auth_id),
    )

    refused = await api.post(
        f"/appointments/{appointment_id}/reschedule",
        json={"slot_id": str(contested)},
        headers=patient,
    )
    assert refused.status_code == 409

    # The original appointment is untouched: a failed move must not strand the patient.
    still_held = await api.get("/appointments", headers=patient)
    assert still_held.json()[0]["slot_id"] == str(original)
    assert still_held.json()[0]["status"] == "requested"


async def test_a_patient_cannot_cancel_another_patients_appointment(
    api: httpx.AsyncClient,
    clinic: Clinic,
    make_slot: Callable[..., Any],
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """Appointments are PHI. Acting on someone else's must answer exactly as it does for an
    id that does not exist, so probing cannot confirm a real appointment."""
    slot_id = await make_slot(clinic.provider_id)
    booked = await api.post(
        "/appointments", json={"slot_id": str(slot_id)}, headers=headers(clinic.patient_auth_id)
    )
    appointment_id = booked.json()["id"]

    intruder = headers(clinic.neighbour_auth_id)
    hijacked = await api.post(f"/appointments/{appointment_id}/cancel", json={}, headers=intruder)
    invented = await api.post(f"/appointments/{uuid.uuid4()}/cancel", json={}, headers=intruder)

    assert hijacked.status_code == 404
    assert hijacked.json() == invented.json()


async def test_appointments_are_gated_behind_identity_verification(
    api: httpx.AsyncClient,
    clinic: Clinic,
    headers: Callable[[uuid.UUID], dict[str, str]],
) -> None:
    """A valid login alone must not reach scheduling: an appointment names a provider and a
    time, which is health information about the patient (Core #2)."""
    unverified = await api.get("/appointments", headers=headers(uuid.uuid4()))

    assert unverified.status_code == 403
    assert unverified.json()["detail"]["code"] == "identity_verification_required"


async def test_scheduling_requires_authentication(api: httpx.AsyncClient) -> None:
    """An unauthenticated request to any patient resource is rejected (Core #1)."""
    assert (await api.get("/appointments")).status_code == 401
