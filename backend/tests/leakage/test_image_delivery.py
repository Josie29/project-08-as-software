from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app.main import app
from app.services.storage import (
    ObjectStorage,
    StorageError,
    StorageObjectMissingError,
    get_object_storage,
)
from tests.leakage.conftest import verify_identity

JPEG = b"\xff\xd8\xff-stub-jpeg"


class _StubStorage:
    """Stands in for object storage so delivery can be tested without the network."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.requested: list[str] = []

    async def download(self, path: str) -> bytes:
        self.requested.append(path)
        if self._raises:
            raise self._raises
        return JPEG


@pytest.fixture
def storage() -> Any:
    """Install a stub storage client for the duration of a test.

    Yields:
        The stub, so a test can assert which path was requested.
    """
    stub = _StubStorage()
    app.dependency_overrides[get_object_storage] = lambda: stub
    yield stub
    app.dependency_overrides.pop(get_object_storage, None)


async def test_an_owned_image_is_served_with_its_bytes(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """The end of the Priority 1 path: a verified patient actually receives their scan."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller)
    )

    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"


async def test_phi_responses_forbid_caching(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """A shared cache holding one patient's scan would leak it to the next requester, and
    no amount of server-side authorization could undo that."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller)
    )

    assert "no-store" in response.headers["cache-control"]
    assert "private" in response.headers["cache-control"]


async def test_the_thumbnail_variant_requests_the_smaller_object(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """Thumbnail-first loading only helps if the thumbnail endpoint actually fetches the
    thumbnail; serving the full image here would silently undo the optimisation."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    await api.get(f"/images/{seeded['demo_image_id']}/thumbnail", headers=auth_headers(caller))

    assert storage.requested
    assert storage.requested[0].endswith("_thumb.jpg")


async def test_a_vanished_object_reports_not_found(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The row exists and the caller owns it, but the object is gone. That is a 404, not a
    500 — the request was valid and the patient should see a clear answer."""
    stub = _StubStorage(raises=StorageObjectMissingError("gone"))
    app.dependency_overrides[get_object_storage] = lambda: stub
    try:
        caller = uuid4()
        await verify_identity(db, caller, seeded["demo_patient_id"])

        response = await api.get(
            f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller)
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_object_storage, None)


async def test_storage_being_down_is_reported_as_unavailable(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """An outage must not be reported as 'no such image'. Telling a patient their scan does
    not exist when storage is merely unreachable is worse than admitting the outage."""
    stub = _StubStorage(raises=StorageError("down"))
    app.dependency_overrides[get_object_storage] = lambda: stub
    try:
        caller = uuid4()
        await verify_identity(db, caller, seeded["demo_patient_id"])

        response = await api.get(
            f"/images/{seeded['demo_image_id']}/file", headers=auth_headers(caller)
        )

        assert response.status_code == 503
    finally:
        app.dependency_overrides.pop(get_object_storage, None)


async def test_a_foreign_image_is_refused_before_storage_is_touched(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """Authorization must come first. If a request reached storage before the ownership
    check, a bug downstream could serve the bytes anyway."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/images/{seeded['neighbour_image_id']}/file", headers=auth_headers(caller)
    )

    assert response.status_code == 404
    assert storage.requested == []


async def test_the_storage_dependency_builds_a_real_client() -> None:
    """The stub above would happily hide a broken factory, so the real dependency is
    exercised once."""
    from app.config import get_settings

    assert isinstance(get_object_storage(get_settings()), ObjectStorage)
