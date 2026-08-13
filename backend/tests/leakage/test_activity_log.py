import uuid
from collections.abc import Callable
from typing import Any

import asyncpg
import httpx

from tests.leakage.conftest import verify_identity


async def test_a_patient_sees_their_own_accesses_and_not_a_neighbours(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    """The access log is the patient's own compliance record. If it carried anyone else's
    rows it would be a leak in the very screen built to prove there are none."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await verify_identity(db, mine, seeded["demo_patient_id"])
    await verify_identity(db, theirs, seeded["neighbour_patient_id"])

    # Each patient views one of their own images, writing an audit row apiece.
    await api.get(f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(mine))
    await api.get(f"/images/{seeded['neighbour_image_id']}/file", headers=auth_headers(theirs))

    response = await api.get("/activity", headers=auth_headers(mine))
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) > 0

    neighbour_resources = {
        str(seeded["neighbour_image_id"]),
        str(seeded["neighbour_study_id"]),
        str(seeded["neighbour_clip_id"]),
    }
    assert all(entry["resource_id"] not in neighbour_resources for entry in entries)


async def test_a_refused_attempt_is_recorded_as_denied(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    """A log that only showed successes would hide exactly the events a patient or a
    compliance reviewer most needs to see."""
    mine = uuid.uuid4()
    await verify_identity(db, mine, seeded["demo_patient_id"])

    # Reaching for the neighbour's image is refused, and that refusal is the caller's own
    # audit row — it belongs in their log.
    denied = await api.get(
        f"/images/{seeded['neighbour_image_id']}/file", headers=auth_headers(mine)
    )
    assert denied.status_code == 404

    entries = (await api.get("/activity", headers=auth_headers(mine))).json()
    assert any(entry["allowed"] is False for entry in entries)
    # The label is derived from the action name, so a refusal never reads as an access.
    assert all(
        entry["allowed"] is False
        for entry in entries
        if entry["action"].endswith(("_denied", "_failed"))
    )


async def test_the_activity_log_is_behind_the_identity_gate(
    api: httpx.AsyncClient,
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    """The log names which studies and reports were opened. A signed-in session that has
    not passed the identity check must not reach it (Core #2)."""
    response = await api.get("/activity", headers=auth_headers(uuid.uuid4()))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "identity_verification_required"


async def test_reading_the_log_does_not_grow_the_log(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Callable[..., dict[str, str]],
) -> None:
    """An audited read of the audit log would add a row every time the screen opened,
    burying the accesses a reviewer is looking for under the act of looking."""
    mine = uuid.uuid4()
    await verify_identity(db, mine, seeded["demo_patient_id"])
    await api.get(f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(mine))

    before = await db.fetchval("SELECT count(*) FROM audit_log")
    await api.get("/activity", headers=auth_headers(mine))
    await api.get("/activity", headers=auth_headers(mine))

    assert await db.fetchval("SELECT count(*) FROM audit_log") == before
