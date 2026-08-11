from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from tests.leakage.conftest import verify_identity

#: Values seeded into the demo dataset that must never appear in an audit row.
_PHI_VALUES = ("Rowan", "Whitfield", "1991-06-24", "AS-100241", "Devon", "Marsh")


async def test_viewing_an_image_is_recorded_once(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Every PHI read must be attributable. Without a record, a clinic cannot answer the
    only question that matters after a suspected breach: who looked at this chart?
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    await api.get(f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller))

    rows = await db.fetch(
        "SELECT * FROM audit_log WHERE action = 'image_viewed' AND resource_id = $1",
        seeded["demo_image_id"],
    )
    assert len(rows) == 1
    assert rows[0]["actor_type"] == "patient"
    assert rows[0]["actor_id"] == seeded["demo_patient_id"]
    assert rows[0]["request_id"] is not None


async def test_a_rejected_attempt_is_also_recorded(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Core #6 requires that every rejected attempt is logged, not merely refused. The
    attempts worth investigating are precisely the ones that failed.
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    await api.get(f"/images/{seeded['neighbour_image_id']}/file", headers=auth_headers(caller))

    denials = await db.fetch(
        "SELECT * FROM audit_log WHERE action = 'image_access_denied' AND resource_id = $1",
        seeded["neighbour_image_id"],
    )
    assert len(denials) == 1
    # Attributed to the patient who tried, which is what makes it actionable.
    assert denials[0]["actor_id"] == seeded["demo_patient_id"]


async def test_the_audit_log_never_contains_phi(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The audit log is read routinely by operators during compliance review. Putting names,
    dates of birth, or account ids in it would move protected data into the one table most
    widely read by staff.
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    await api.get(f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller))
    await api.get(f"/studies/{seeded['neighbour_study_id']}/images", headers=auth_headers(caller))

    rows = await db.fetch("SELECT * FROM audit_log")
    assert rows, "expected audit activity"

    contents = " ".join(str(value) for row in rows for value in row.values())
    for phi in _PHI_VALUES:
        assert phi not in contents, f"audit log leaked {phi!r}"


async def test_a_denied_attempt_records_no_successful_view(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A denial that also logged a view would make the trail actively misleading during an
    investigation — it would look as though the data had been read."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    await api.get(f"/images/{seeded['neighbour_image_id']}/file", headers=auth_headers(caller))

    views = await db.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'image_viewed' AND resource_id = $1",
        seeded["neighbour_image_id"],
    )
    assert views == 0


async def test_audit_rows_survive_the_request_that_created_them(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Read back on a separate connection: an audit row still inside an uncommitted
    transaction would vanish whenever the request later failed, which is exactly when the
    trail matters most.
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    await api.get(f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller))

    from tests.conftest import asyncpg_dsn

    other = await asyncpg.connect(asyncpg_dsn())
    try:
        committed: UUID | None = await other.fetchval(
            "SELECT resource_id FROM audit_log WHERE action = 'image_viewed' LIMIT 1"
        )
    finally:
        await other.close()

    assert committed == seeded["demo_image_id"]
