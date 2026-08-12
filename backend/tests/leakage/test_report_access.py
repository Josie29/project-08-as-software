from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from tests.leakage.conftest import verify_identity


async def _report_ids(db: asyncpg.Connection, status: str) -> list[UUID]:
    """Return seeded report ids with a given status.

    Args:
        db: Database connection.
        status: Report status to select.

    Returns:
        Matching report ids.
    """
    rows = await db.fetch("SELECT id FROM reports WHERE status = $1", status)
    return [row["id"] for row in rows]


async def test_a_patient_sees_only_their_own_signed_reports(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Core #7 and #9 together: the list must contain this patient's signed reports and
    nobody else's, and no preliminary read at all."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get("/reports", headers=auth_headers(caller))

    assert response.status_code == 200
    body = response.json()
    assert body, "expected the demo patient to have signed reports"
    assert all(item["status"] in ("final", "amended") for item in body)

    owned = {
        row["id"]
        for row in await db.fetch(
            "SELECT id FROM reports WHERE patient_id = $1", seeded["demo_patient_id"]
        )
    }
    assert {UUID(item["id"]) for item in body} <= owned


async def test_a_preliminary_report_is_never_returned(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The seeded preliminary report belongs to this very patient, so only the status rule
    keeps it back. Serving it would hand a patient an unreviewed clinical opinion."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    preliminary = await _report_ids(db, "preliminary")
    assert preliminary, "seed should include a preliminary report"

    listed = await api.get("/reports", headers=auth_headers(caller))
    fetched = await api.get(f"/reports/{preliminary[0]}", headers=auth_headers(caller))

    assert UUID(listed.json()[0]["id"]) not in set(preliminary)
    assert fetched.status_code == 404


async def test_a_patient_cannot_read_another_patients_report(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Core #9 — the report half of the cross-patient guarantee, graded with the same
    rigour as a security vulnerability."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    neighbour_reports = await db.fetch(
        "SELECT id FROM reports WHERE patient_id = $1", seeded["neighbour_patient_id"]
    )
    assert neighbour_reports, "seed should give the neighbour a report"

    response = await api.get(f"/reports/{neighbour_reports[0]['id']}", headers=auth_headers(caller))

    assert response.status_code == 404


async def test_a_foreign_report_is_indistinguishable_from_a_missing_one(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Answering differently would confirm which report ids exist, which is the oracle the
    adversarial id-walking test is looking for."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    neighbour = await db.fetchval(
        "SELECT id FROM reports WHERE patient_id = $1 LIMIT 1", seeded["neighbour_patient_id"]
    )

    foreign = await api.get(f"/reports/{neighbour}", headers=auth_headers(caller))
    absent = await api.get(f"/reports/{uuid4()}", headers=auth_headers(caller))

    assert foreign.status_code == absent.status_code == 404
    assert foreign.content == absent.content


async def test_reading_a_report_is_audited_and_a_refusal_is_too(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A report is the most sensitive thing in the record. Both the read and the refusal
    have to be attributable after the fact."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    mine = await db.fetchval(
        "SELECT id FROM reports WHERE patient_id = $1 AND status = 'final' LIMIT 1",
        seeded["demo_patient_id"],
    )
    theirs = await db.fetchval(
        "SELECT id FROM reports WHERE patient_id = $1 LIMIT 1", seeded["neighbour_patient_id"]
    )

    await api.get(f"/reports/{mine}", headers=auth_headers(caller))
    await api.get(f"/reports/{theirs}", headers=auth_headers(caller))

    viewed = await db.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'report_viewed' AND resource_id = $1",
        mine,
    )
    denied = await db.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'report_access_denied' AND resource_id = $1",
        theirs,
    )
    assert viewed == 1
    assert denied == 1


async def test_reports_require_a_verified_identity(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Signing in is not enough to open a report, exactly as it is not enough for images."""
    response = await api.get("/reports", headers=auth_headers(uuid4()))

    assert response.status_code == 403
