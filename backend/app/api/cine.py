import asyncio
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.studies import NO_STORE, not_found
from app.auth.dependencies import get_patient_scope
from app.models.imaging import MAX_CINE_FRAMES
from app.repositories.phi import CineClipSummary, CineManifest, FrameAccess, PatientScope
from app.services.cine_bundle import BUNDLE_FETCH_CONCURRENCY, BUNDLE_MEDIA_TYPE, pack_frames
from app.services.storage import (
    ObjectStorage,
    StorageError,
    StorageObjectMissingError,
    get_object_storage,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["cine"])


@router.get("/studies/{study_id}/cine", response_model=list[CineClipSummary])
async def list_study_clips(
    study_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> list[CineClipSummary]:
    """List cine clips for one of the caller's completed studies.

    Args:
        study_id: The study to list.
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The study's clips in capture order.

    Raises:
        HTTPException: 404 if the study is missing, not completed, or another patient's.
    """
    clips = await scope.list_clips(study_id)
    if clips is None:
        raise not_found()
    response.headers["Cache-Control"] = NO_STORE
    return clips


@router.get("/cine/{clip_id}/manifest", response_model=CineManifest)
async def get_clip_manifest(
    clip_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> CineManifest:
    """Return the ordered frame manifest for one clip.

    Args:
        clip_id: The clip requested.
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The manifest, with per-frame availability.

    Raises:
        HTTPException: 404 if the clip is missing, not completed, or another patient's.
    """
    manifest = await scope.open_clip(clip_id)
    if manifest is None:
        raise not_found()
    response.headers["Cache-Control"] = NO_STORE
    return manifest


@router.get("/cine/{clip_id}/frames")
async def get_clip_bundle(
    clip_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    """Serve every intact frame of a clip in one response.

    A hundred separate requests for a hundred small frames spends its whole budget on
    round trips: browser to the web tier, web tier to the API, API to object storage, once
    per frame. Fetching them here instead collapses that to a single client request and
    keeps the storage fan-out next to storage, where the latency is smallest.

    Frames whose bytes cannot be retrieved are simply absent from the bundle. The player
    already handles a missing frame as a gap, so a storage failure degrades the same way a
    damaged frame does instead of failing the whole clip.

    Args:
        clip_id: The clip requested.
        scope: The verified patient's scope.
        storage: Object storage client.

    Returns:
        The bundle, in the layout described by `pack_frames`.

    Raises:
        HTTPException: 404 if the clip is missing, not completed, or another patient's.
    """
    frames = await scope.open_all_frames(clip_id)
    if frames is None:
        raise not_found()
    await scope.release()

    limiter = asyncio.Semaphore(BUNDLE_FETCH_CONCURRENCY)

    async def fetch(access: FrameAccess) -> tuple[int, bytes] | None:
        async with limiter:
            try:
                return access.sequence, await storage.download(access.storage_path)
            except StorageError:
                logger.warning(
                    "cine.bundle_frame_missing", clip_uuid=str(clip_id), sequence=access.sequence
                )
                return None

    fetched = await asyncio.gather(*(fetch(access) for access in frames))
    return Response(
        content=pack_frames([entry for entry in fetched if entry is not None]),
        media_type=BUNDLE_MEDIA_TYPE,
        headers={"Cache-Control": NO_STORE},
    )


@router.get("/cine/{clip_id}/frames/{sequence}")
async def get_clip_frame(
    clip_id: UUID,
    sequence: int,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    """Serve one cine frame's bytes.

    Frame bytes are immutable, which would normally argue for a long browser cache. They
    are also PHI, and a cached frame is a copy of a patient's scan left on whatever machine
    played it. `no-store` wins: the player holds decoded frames in memory for the life of
    the viewer, so playback is smooth without anything reaching disk.

    Args:
        clip_id: The clip the frame belongs to.
        sequence: Zero-based frame position.
        scope: The verified patient's scope.
        storage: Object storage client.

    Returns:
        The frame bytes.

    Raises:
        HTTPException: 404 if the frame is not accessible, 503 if storage is unavailable.
    """
    if not 0 <= sequence < MAX_CINE_FRAMES:
        # Out of range before touching the database, so id-walking a sequence costs the
        # attacker a round trip and gains them nothing.
        raise not_found()

    access = await scope.open_frame(clip_id, sequence)
    if access is None:
        raise not_found()
    await scope.release()

    try:
        content = await storage.download(access.storage_path)
    except StorageObjectMissingError as exc:
        logger.warning("cine.object_missing", clip_uuid=str(clip_id), sequence=sequence)
        raise not_found() from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage is temporarily unavailable.",
        ) from exc

    return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": NO_STORE})
