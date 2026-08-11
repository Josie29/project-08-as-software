from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest

from tests.leakage.conftest import verify_identity


def _phi_paths(study_id: UUID, image_id: UUID) -> list[str]:
    """Return every PHI route addressed by a resource id.

    Args:
        study_id: A study identifier.
        image_id: An image identifier.

    Returns:
        Paths to attempt.
    """
    return [
        f"/studies/{study_id}/images",
        f"/images/{image_id}/file",
        f"/images/{image_id}/thumbnail",
    ]


async def test_a_patient_cannot_reach_another_patients_resources(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """This is the failure the brief grades as a security vulnerability rather than a bug:
    one patient reading another's images. Every PHI route is attempted with a fully valid,
    fully verified session against the neighbour's real resource ids.
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    headers = auth_headers(caller)

    for path in _phi_paths(seeded["neighbour_study_id"], seeded["neighbour_image_id"]):
        response = await api.get(path, headers=headers)

        assert response.status_code == 404, f"{path} leaked with {response.status_code}"


async def test_a_foreign_resource_is_indistinguishable_from_a_nonexistent_one(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """If a real-but-foreign id answered differently from a random one, an attacker could
    confirm which ids exist — turning the id-walking test into a working oracle even though
    no bytes are served.
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    headers = auth_headers(caller)

    foreign = await api.get(f"/images/{seeded['neighbour_image_id']}/file", headers=headers)
    absent = await api.get(f"/images/{uuid4()}/file", headers=headers)

    assert foreign.status_code == absent.status_code
    assert foreign.content == absent.content


async def test_images_from_a_cancelled_study_are_unreachable(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Core #3 limits the patient to completed visits. The image belongs to this very
    patient, so only the status filter stops it being served.
    """
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    headers = auth_headers(caller)

    listing = await api.get(f"/studies/{seeded['cancelled_study_id']}/images", headers=headers)
    bytes_response = await api.get(f"/images/{seeded['cancelled_image_id']}/file", headers=headers)

    assert listing.status_code == 404
    assert bytes_response.status_code == 404


async def test_the_study_list_contains_only_the_callers_completed_studies(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A list endpoint that forgot its ownership filter would return every patient's studies
    at once — the highest-volume version of the same leak."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get("/studies", headers=auth_headers(caller))

    assert response.status_code == 200
    returned = {UUID(study["id"]) for study in response.json()}
    assert seeded["demo_study_id"] in returned
    assert seeded["neighbour_study_id"] not in returned
    assert seeded["cancelled_study_id"] not in returned


@pytest.mark.parametrize("with_token", [False, True])
async def test_phi_requires_a_verified_identity_not_merely_a_login(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    with_token: bool,
) -> None:
    """Core #2 exists because a login alone is not enough. If a signed-in user who never
    passed the ID and date-of-birth check could read images, the second factor would be
    decorative.
    """
    headers: dict[str, str] = auth_headers(uuid4()) if with_token else {}
    expected = 403 if with_token else 401

    for path in ["/studies", *_phi_paths(seeded["demo_study_id"], seeded["demo_image_id"])]:
        response = await api.get(path, headers=headers)

        assert response.status_code == expected, f"{path} returned {response.status_code}"


async def test_an_expired_verification_stops_granting_access(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Verification is time-limited so an unattended session stops exposing images. If
    expiry were ignored, one check would unlock the account permanently."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"], minutes=-1)

    response = await api.get("/studies", headers=auth_headers(caller))

    assert response.status_code == 403


async def test_a_revoked_verification_stops_granting_access(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Revocation must take effect immediately; a session that survives it cannot be shut
    off during an incident."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    await db.execute("UPDATE identity_verifications SET revoked_at = now()")

    response = await api.get("/studies", headers=auth_headers(caller))

    assert response.status_code == 403
