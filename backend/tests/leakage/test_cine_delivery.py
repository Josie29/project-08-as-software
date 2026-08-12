from typing import Any
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app.main import app
from app.services.storage import get_object_storage
from tests.leakage.conftest import verify_identity

JPEG = b"\xff\xd8\xff-stub-frame"


class _StubStorage:
    """Stands in for object storage so frame delivery can be tested without the network."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    async def download(self, path: str) -> bytes:
        self.requested.append(path)
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


async def test_the_manifest_lists_every_declared_frame_in_order(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Playback order comes from the manifest. If it arrived unsorted or short, the clip
    would play scrambled or stop early with no error to explain why."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['demo_clip_id']}/manifest", headers=auth_headers(caller)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["frame_count"] == seeded["demo_clip_frame_count"]
    assert [frame["sequence"] for frame in body["frames"]] == list(range(body["frame_count"]))
    assert all(frame["available"] for frame in body["frames"])


async def test_a_damaged_clip_reports_its_gaps_rather_than_hiding_them(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Edge case #2. Omitting the missing frames would make the clip look whole and play
    short; the viewer can only show a gap indicator if the manifest admits the gap."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['damaged_clip_id']}/manifest", headers=auth_headers(caller)
    )

    body = response.json()
    unavailable = {frame["sequence"] for frame in body["frames"] if not frame["available"]}
    assert unavailable == set(seeded["damaged_clip_missing"])
    assert len(body["frames"]) == body["frame_count"]


async def test_an_owned_frame_is_served_with_its_bytes(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """The manifest is useless if the frames behind it cannot be fetched."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['demo_clip_id']}/frames/0", headers=auth_headers(caller)
    )

    assert response.status_code == 200
    assert response.content == JPEG
    assert "no-store" in response.headers["cache-control"]


async def test_a_frame_marked_missing_is_never_fetched_from_storage(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """The object was never uploaded. Asking storage for it turns a known gap into a
    storage error, and the patient would see an outage instead of a missing frame."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['damaged_clip_id']}/frames/{seeded['damaged_clip_missing'][0]}",
        headers=auth_headers(caller),
    )

    assert response.status_code == 404
    assert storage.requested == []


async def test_a_foreign_clip_manifest_is_refused(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Core #6. The manifest names every frame path in the clip — leaking it would hand
    over a map of another patient's study even before any bytes moved."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['neighbour_clip_id']}/manifest", headers=auth_headers(caller)
    )

    assert response.status_code == 404


async def test_a_foreign_frame_is_refused_before_storage_is_touched(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """Skipping the manifest and going straight for the frames must not work — the frame
    route re-checks ownership rather than trusting that the manifest call happened."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['neighbour_clip_id']}/frames/0", headers=auth_headers(caller)
    )

    assert response.status_code == 404
    assert storage.requested == []


async def test_a_foreign_clip_and_an_invented_one_are_indistinguishable(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Any difference here is an oracle: an attacker walking ids could confirm which clips
    exist without ever reading one."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    foreign = await api.get(
        f"/cine/{seeded['neighbour_clip_id']}/manifest", headers=auth_headers(caller)
    )
    invented = await api.get(f"/cine/{uuid4()}/manifest", headers=auth_headers(caller))

    assert foreign.status_code == invented.status_code
    assert foreign.json() == invented.json()


async def test_an_out_of_range_frame_is_refused(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """A negative or oversized sequence must not reach the query layer as a valid lookup."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    for sequence in (-1, 100, 4096):
        response = await api.get(
            f"/cine/{seeded['demo_clip_id']}/frames/{sequence}", headers=auth_headers(caller)
        )
        assert response.status_code == 404, sequence
    assert storage.requested == []


async def test_clips_are_listed_for_an_owned_study_and_refused_for_a_foreign_one(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The gallery discovers clips through this route; if it leaked, it would leak the
    existence and shape of another patient's clips."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    mine = await api.get(f"/studies/{seeded['demo_study_id']}/cine", headers=auth_headers(caller))
    theirs = await api.get(
        f"/studies/{seeded['neighbour_study_id']}/cine", headers=auth_headers(caller)
    )

    assert mine.status_code == 200
    assert [clip["id"] for clip in mine.json()] == [str(seeded["demo_clip_id"])]
    assert mine.json()[0]["available_frame_count"] == seeded["demo_clip_frame_count"]
    assert theirs.status_code == 404


async def test_an_unverified_session_cannot_reach_cine(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A valid token is not enough. Cine must sit behind the same identity gate as stills,
    or it becomes the way around Core #2."""
    headers = auth_headers(uuid4())

    manifest = await api.get(f"/cine/{seeded['demo_clip_id']}/manifest", headers=headers)
    frame = await api.get(f"/cine/{seeded['demo_clip_id']}/frames/0", headers=headers)

    assert manifest.status_code == 403
    assert frame.status_code == 403


async def test_opening_a_clip_writes_one_audit_entry_and_frames_write_none(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """The clip is the access event. One row per frame would put a hundred entries in the
    log for a single view and drown the entries that matter."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])
    headers = auth_headers(caller)

    await api.get(f"/cine/{seeded['demo_clip_id']}/manifest", headers=headers)
    for sequence in range(5):
        await api.get(f"/cine/{seeded['demo_clip_id']}/frames/{sequence}", headers=headers)

    viewed = await db.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'cine_viewed' AND resource_id = $1",
        seeded["demo_clip_id"],
    )
    assert viewed == 1


async def test_a_refused_clip_is_recorded(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Core #6 requires rejected attempts to be logged, not merely refused — a silent
    refusal leaves no trace that someone went looking."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    await api.get(f"/cine/{seeded['neighbour_clip_id']}/manifest", headers=auth_headers(caller))

    denied = await db.fetchval(
        "SELECT count(*) FROM audit_log WHERE action = 'cine_access_denied' AND resource_id = $1",
        seeded["neighbour_clip_id"],
    )
    assert denied == 1


def _unpack(payload: bytes) -> dict[int, bytes]:
    """Decode a frame bundle into sequence-keyed bytes.

    Written independently of the packer rather than importing it: a test that reuses the
    encoder proves the two agree, not that the format is what the client expects.

    Args:
        payload: The bundle body.

    Returns:
        Frame bytes by sequence number.
    """
    count = int.from_bytes(payload[:4], "little")
    entries: list[tuple[int, int]] = []
    offset = 4
    for _ in range(count):
        sequence = int.from_bytes(payload[offset : offset + 2], "little")
        length = int.from_bytes(payload[offset + 2 : offset + 6], "little")
        entries.append((sequence, length))
        offset += 6

    frames: dict[int, bytes] = {}
    for sequence, length in entries:
        frames[sequence] = payload[offset : offset + length]
        offset += length
    return frames


async def test_the_bundle_carries_every_intact_frame_in_one_response(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """The bundle exists to collapse a hundred round trips into one. If it came back short,
    the player would silently treat the absent frames as gaps in an undamaged study."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(f"/cine/{seeded['demo_clip_id']}/frames", headers=auth_headers(caller))

    assert response.status_code == 200
    frames = _unpack(response.content)
    assert sorted(frames) == list(range(seeded["demo_clip_frame_count"]))
    assert all(payload == JPEG for payload in frames.values())


async def test_the_bundle_omits_frames_the_study_is_missing(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """Edge case #2 through the bulk path. Storage is never asked for an object that was
    never uploaded, and the gap stays a gap rather than becoming a failed clip."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['damaged_clip_id']}/frames", headers=auth_headers(caller)
    )

    frames = _unpack(response.content)
    assert set(seeded["damaged_clip_missing"]).isdisjoint(frames)
    assert len(storage.requested) == len(frames)


async def test_a_foreign_bundle_is_refused_before_storage_is_touched(
    api: httpx.AsyncClient,
    db: asyncpg.Connection,
    seeded: dict[str, Any],
    auth_headers: Any,
    storage: _StubStorage,
) -> None:
    """The bundle is the fastest way to exfiltrate a whole clip, so it needs the same
    ownership check as the per-frame route rather than inheriting one."""
    caller = uuid4()
    await verify_identity(db, caller, seeded["demo_patient_id"])

    response = await api.get(
        f"/cine/{seeded['neighbour_clip_id']}/frames", headers=auth_headers(caller)
    )

    assert response.status_code == 404
    assert storage.requested == []


async def test_an_unverified_session_cannot_reach_the_bundle(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A valid token is not enough for the bulk path either."""
    response = await api.get(
        f"/cine/{seeded['demo_clip_id']}/frames", headers=auth_headers(uuid4())
    )

    assert response.status_code == 403
