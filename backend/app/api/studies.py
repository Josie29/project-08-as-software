from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.dependencies import get_patient_scope
from app.repositories.phi import ImageSummary, PatientProfile, PatientScope, StudySummary
from app.services.storage import (
    ObjectStorage,
    StorageError,
    StorageObjectMissingError,
    get_object_storage,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["imaging"])

#: Identical body for a resource that does not exist and one belonging to another patient.
#: Distinguishing them would confirm that an id is real, which is precisely the oracle the
#: adversarial id-walking test is looking for.
NOT_FOUND_MESSAGE = "Not found."

#: PHI must never be stored by a shared cache, and never persisted by the browser.
NO_STORE = "private, no-store, max-age=0"


def not_found() -> HTTPException:
    """Build the single 404 used for both missing and foreign resources.

    Returns:
        The exception to raise.
    """
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_MESSAGE)


@router.get("/me", response_model=PatientProfile)
async def get_my_profile(
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> PatientProfile:
    """Return the caller's own identifying details for the portal header.

    Args:
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The patient's profile.

    Raises:
        HTTPException: 404 if the record no longer exists.
    """
    profile = await scope.get_profile()
    if profile is None:
        raise not_found()
    response.headers["Cache-Control"] = NO_STORE
    return profile


@router.get("/studies", response_model=list[StudySummary])
async def list_studies(
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> list[StudySummary]:
    """List the caller's completed studies.

    Args:
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The patient's completed studies, newest first.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_completed_studies()


@router.get("/studies/{study_id}/images", response_model=list[ImageSummary])
async def list_study_images(
    study_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> list[ImageSummary]:
    """List image metadata for one of the caller's completed studies.

    Args:
        study_id: The study to list.
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        Image metadata in capture order.

    Raises:
        HTTPException: 404 if the study is missing, not completed, or another patient's.
    """
    images = await scope.list_images(study_id)
    if images is None:
        raise not_found()
    response.headers["Cache-Control"] = NO_STORE
    return images


async def _serve_image(
    image_id: UUID, scope: PatientScope, storage: ObjectStorage, *, thumbnail: bool
) -> Response:
    """Authorise, audit, and return one image's bytes.

    Args:
        image_id: The image requested.
        scope: The verified patient's scope.
        storage: Object storage client.
        thumbnail: Whether to serve the thumbnail.

    Returns:
        The image bytes.

    Raises:
        HTTPException: 404 if not accessible, 503 if storage is unavailable.
    """
    access = await scope.open_image(image_id, thumbnail=thumbnail)
    if access is None:
        raise not_found()

    try:
        content = await storage.download(access.storage_path)
    except StorageObjectMissingError as exc:
        # The row exists and is owned by the caller, but the object is gone. Reported as
        # not found rather than as a server error, and logged for follow-up.
        logger.warning("imaging.object_missing", image_uuid=str(image_id))
        raise not_found() from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage is temporarily unavailable.",
        ) from exc

    return Response(
        content=content,
        media_type="image/jpeg",
        headers={"Cache-Control": NO_STORE},
    )


@router.get("/images/{image_id}/file")
async def get_image(
    image_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    """Serve one full-size image.

    Args:
        image_id: The image requested.
        scope: The verified patient's scope.
        storage: Object storage client.

    Returns:
        The image bytes.
    """
    return await _serve_image(image_id, scope, storage, thumbnail=False)


@router.get("/images/{image_id}/thumbnail")
async def get_image_thumbnail(
    image_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    """Serve one image's thumbnail.

    Args:
        image_id: The image requested.
        scope: The verified patient's scope.
        storage: Object storage client.

    Returns:
        The thumbnail bytes.
    """
    return await _serve_image(image_id, scope, storage, thumbnail=True)
