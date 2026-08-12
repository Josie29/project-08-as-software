from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app.main import app
from app.services.sharing import MAX_OPENS, hash_token
from app.services.storage import get_object_storage
from tests.leakage.conftest import verify_identity

JPEG = b"\xff\xd8\xff-stub"


class _StubStorage:
    async def download(self, path: str) -> bytes:
        return JPEG


@pytest.fixture(autouse=True)
def stub_storage() -> Any:
    """Serve stub bytes so share resolution can be tested without the network."""
    app.dependency_overrides[get_object_storage] = lambda: _StubStorage()
    yield
    app.dependency_overrides.pop(get_object_storage, None)


async def _share_image(
    api: httpx.AsyncClient, headers: dict[str, str], image_id: Any, hours: int = 48
) -> httpx.Response:
    """Create a share link for an image."""
    return await api.post(
        "/shares",
        headers=headers,
        json={
            "resource_type": "image",
            "resource_id": str(image_id),
            "recipient_email": "recipient@example.com",
            "ttl_hours": hours,
        },
    )


async def test_a_link_opens_the_shared_image_without_signing_in(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The point of Core #5: a specialist with the link sees the scan, with no account."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    # Deliberately no Authorization header.
    opened = await api.get(f"/s/{token}")

    assert created.status_code == 201
    assert opened.status_code == 200
    assert opened.content == JPEG


async def test_the_raw_token_is_never_stored(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """These URLs grant PHI access with no login. If the token sat in the database, a dump
    or a read-only leak would hand over working links to every share ever made."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    stored = await db.fetchval("SELECT token_hash FROM share_links LIMIT 1")

    assert stored == hash_token(token)
    assert token.encode() not in bytes(stored)


async def test_a_revoked_link_stops_working(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Revocation is the patient's only way to take something back once sent. If a revoked
    link still opened, the control would be decorative."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    headers = auth_headers(caller)
    created = await _share_image(api, headers, seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]
    share_id = created.json()["share"]["id"]

    assert (await api.get(f"/s/{token}")).status_code == 200
    await api.post(f"/shares/{share_id}/revoke", headers=headers)
    after = await api.get(f"/s/{token}")

    assert after.status_code == 410
    assert JPEG not in after.content


async def test_an_expired_link_stops_working(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Time-limiting is what stops a forwarded link becoming permanent access (edge case #5)."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    await db.execute("UPDATE share_links SET expires_at = now() - interval '1 minute'")
    response = await api.get(f"/s/{token}")

    assert response.status_code == 410
    assert JPEG not in response.content


async def test_a_guessed_or_tampered_token_is_refused(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The token is the entire credential, so a near-miss must be worth nothing."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    tampered = await api.get(f"/s/{token[:-1]}X")
    invented = await api.get(f"/s/{'a' * 43}")

    assert tampered.status_code == invented.status_code == 410
    assert tampered.content == invented.content


async def test_every_refusal_looks_identical(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Distinguishing 'expired' from 'never existed' would confirm which tokens are real
    and let someone probe for live links."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]
    await db.execute("UPDATE share_links SET expires_at = now() - interval '1 minute'")

    expired = await api.get(f"/s/{token}")
    unknown = await api.get(f"/s/{'b' * 43}")

    assert expired.status_code == unknown.status_code
    assert expired.content == unknown.content


async def test_a_patient_cannot_share_another_patients_resource(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A link minted for someone else's image would be a permanent, unauthenticated
    cross-patient capability — worse than a single unauthorised read, because it outlives
    the request and can be forwarded."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await _share_image(api, auth_headers(caller), seeded["neighbour_image_id"])

    assert response.status_code == 404
    assert await db.fetchval("SELECT count(*) FROM share_links") == 0


async def test_a_patient_cannot_revoke_someone_elses_link(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Revocation is a write on another patient's record if it is not scoped."""
    owner = uuid4()
    await verify_identity(db, owner, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(owner), seeded["demo_image_id"])
    share_id = created.json()["share"]["id"]

    stranger = uuid4()
    await verify_identity(db, stranger, seeded["neighbour_patient_id"])
    response = await api.post(f"/shares/{share_id}/revoke", headers=auth_headers(stranger))

    assert response.status_code == 404
    assert await db.fetchval("SELECT revoked_at FROM share_links WHERE id = $1", share_id) is None


async def test_a_patient_sees_only_their_own_links(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The list must not expose who else has shared what."""
    owner = uuid4()
    await verify_identity(db, owner, seeded["demo_patient_id"])
    await _share_image(api, auth_headers(owner), seeded["demo_image_id"])

    stranger = uuid4()
    await verify_identity(db, stranger, seeded["neighbour_patient_id"])
    response = await api.get("/shares", headers=auth_headers(stranger))

    assert response.status_code == 200
    assert response.json() == []


async def test_a_link_stops_working_after_too_many_opens(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A leaked link should not pay out indefinitely. Capping opens bounds the damage
    without breaking a recipient who reloads."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    await db.execute("UPDATE share_links SET access_count = $1", MAX_OPENS)
    response = await api.get(f"/s/{token}")

    assert response.status_code == 410


async def test_shared_responses_are_never_cached(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A cached share response would keep serving after revocation, straight past the
    control the patient just used (edge case #5)."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    response = await api.get(f"/s/{token}")

    assert "no-store" in response.headers["cache-control"]


async def test_issuance_use_and_refusal_are_all_audited(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A share link is unauthenticated PHI access. Without a trail there is no way to
    answer who opened a patient's scan, which is the question that matters after a leak."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    created = await _share_image(api, auth_headers(caller), seeded["demo_image_id"])
    token = created.json()["link"].rsplit("/", 1)[-1]

    await api.get(f"/s/{token}")
    await api.get(f"/s/{'c' * 43}")

    for action in ("share_link_created", "share_link_used", "share_link_denied"):
        count = await db.fetchval("SELECT count(*) FROM audit_log WHERE action = $1", action)
        assert count >= 1, f"missing audit entry for {action}"


async def test_the_share_email_carries_no_clinical_detail(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The brief requires PHI to stay out of anything a third party processes. The message
    body is built here, so this asserts what actually leaves the system."""
    from app.services.email import SHARE_BODY_TEMPLATE, SHARE_SUBJECT

    combined = f"{SHARE_SUBJECT} {SHARE_BODY_TEMPLATE}"

    for leak in ("diagnosis", "findings", "date of birth", "{patient", "{study", "{report"):
        assert leak not in combined.lower()
    # The link is the only variable the template interpolates.
    assert combined.count("{") == combined.count("{link}")
