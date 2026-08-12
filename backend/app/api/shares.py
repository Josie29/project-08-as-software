from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.studies import NO_STORE, not_found
from app.auth.dependencies import get_patient_scope
from app.config import Settings, get_settings
from app.db import get_db_session
from app.models.enums import ShareResourceType
from app.repositories.phi import PatientScope, ShareRecord
from app.services.email import EmailError, get_email_sender
from app.services.share_resolution import ShareOutcome, resolve_share
from app.services.storage import (
    ObjectStorage,
    StorageError,
    StorageObjectMissingError,
    get_object_storage,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["sharing"])

#: Windows the portal offers. Bounded so a link cannot be minted to last indefinitely.
ALLOWED_TTL_HOURS = (24, 48, 72)

#: The single message for a link that will not open, whatever the reason. A recipient does
#: not need to know whether it expired, was switched off, or never existed — and telling
#: them would confirm which tokens are real.
GONE_MESSAGE = "This link is no longer available."


class CreateShareRequest(BaseModel):
    """A request to share one image or report."""

    resource_type: ShareResourceType
    resource_id: UUID
    recipient_email: EmailStr
    ttl_hours: int = Field(default=48)


class CreateShareResponse(BaseModel):
    """The new link. The token appears here once and is never retrievable again."""

    share: ShareRecord
    link: str
    email_sent: bool
    email_error: str | None = None


@router.post("/shares", response_model=CreateShareResponse, status_code=status.HTTP_201_CREATED)
async def create_share(
    payload: CreateShareRequest,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    settings: Annotated[Settings, Depends(get_settings)],
    response: Response,
) -> CreateShareResponse:
    """Mint a share link for one of the patient's own resources and email it.

    Args:
        payload: What to share, with whom, and for how long.
        scope: The verified patient's scope.
        settings: Application settings.
        response: Used to set cache headers.

    Returns:
        The link, plus whether the email reached the provider.

    Raises:
        HTTPException: 422 for a window we do not offer, 404 if the resource is not theirs.
    """
    if payload.ttl_hours not in ALLOWED_TTL_HOURS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Choose one of {ALLOWED_TTL_HOURS} hours.",
        )

    minted = await scope.create_share(
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        recipient_email=str(payload.recipient_email),
        ttl_hours=payload.ttl_hours,
    )
    if minted is None:
        raise not_found()

    link = f"{settings.frontend_base_url}/s/{minted.token}"

    # A failed send must not lose the link. The patient can copy it from the portal and
    # send it themselves rather than being told the share failed outright (edge case #12).
    email_sent = False
    email_error: str | None = None
    try:
        await get_email_sender(settings).send_share_link(str(payload.recipient_email), link)
        email_sent = True
    except EmailError:
        email_error = "We could not send the email. The link below still works."

    response.headers["Cache-Control"] = NO_STORE
    return CreateShareResponse(
        share=minted.record, link=link, email_sent=email_sent, email_error=email_error
    )


@router.get("/shares", response_model=list[ShareRecord])
async def list_shares(
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> list[ShareRecord]:
    """List the links this patient has created.

    Args:
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        Their links, newest first.
    """
    response.headers["Cache-Control"] = NO_STORE
    return await scope.list_shares()


@router.post("/shares/{share_id}/revoke", response_model=ShareRecord)
async def revoke_share(
    share_id: UUID,
    scope: Annotated[PatientScope, Depends(get_patient_scope)],
    response: Response,
) -> ShareRecord:
    """Switch off one of the patient's links.

    Args:
        share_id: The link to revoke.
        scope: The verified patient's scope.
        response: Used to set cache headers.

    Returns:
        The updated link.

    Raises:
        HTTPException: 404 if the link is missing, already revoked, or not theirs.
    """
    if not await scope.revoke_share(share_id):
        raise not_found()
    response.headers["Cache-Control"] = NO_STORE
    remaining = [record for record in await scope.list_shares() if record.id == share_id]
    return remaining[0]


@router.get("/s/{token}")
async def open_share(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[ObjectStorage, Depends(get_object_storage)],
) -> Response:
    """Serve a shared resource to whoever holds the link.

    Unauthenticated by design — the token is the credential. Every refusal answers with the
    same message and status so a probe cannot learn whether a token was real, expired, or
    switched off.

    Args:
        token: The raw token from the URL.
        request: Used to correlate the audit entry.
        session: Database session.
        storage: Object storage client.

    Returns:
        The image bytes or the report payload.

    Raises:
        HTTPException: 410 when the link will not open, 503 if storage is unavailable.
    """
    request_id = getattr(request.state, "request_id", None)
    resolved = await resolve_share(session, token, request_id=request_id)

    if resolved.outcome is not ShareOutcome.OK:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=GONE_MESSAGE)

    if resolved.resource_type is ShareResourceType.REPORT:
        return Response(
            content=f"{resolved.report_title}\n\n{resolved.report_body}",
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": NO_STORE},
        )

    try:
        content = await storage.download(resolved.storage_path or "")
    except StorageObjectMissingError as exc:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=GONE_MESSAGE) from exc
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage is temporarily unavailable.",
        ) from exc

    return Response(content=content, media_type="image/jpeg", headers={"Cache-Control": NO_STORE})
