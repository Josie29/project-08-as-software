from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import SupabaseTokenVerifier, TokenError, get_token_verifier
from app.db import get_db_session
from app.models.identity import IdentityVerification, Patient
from app.repositories.phi import PatientScope

logger = structlog.get_logger(__name__)

#: Returned when the caller is signed in but has not passed the identity check, so the
#: frontend can route to the verification screen instead of showing a generic error.
IDENTITY_REQUIRED_CODE = "identity_verification_required"

_bearer = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    """A caller holding a valid Supabase token. Grants no access to PHI on its own."""

    auth_user_id: UUID
    email: str | None = None


class VerifiedPatient(BaseModel):
    """A caller who has additionally passed the identity check (Core #2)."""

    auth_user_id: UUID
    patient_id: UUID


async def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[SupabaseTokenVerifier, Depends(get_token_verifier)],
) -> AuthenticatedUser:
    """Resolve the caller from a bearer token.

    Args:
        credentials: Parsed Authorization header, if present.
        verifier: Token verifier.

    Returns:
        The authenticated caller.

    Raises:
        HTTPException: 401 if the token is absent or not trustworthy.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = await verifier.verify(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return AuthenticatedUser(auth_user_id=claims.subject, email=claims.email)


async def get_verified_patient(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VerifiedPatient:
    """Require a live identity verification for the caller.

    A valid token alone must never unlock PHI — that second factor is the whole point of
    Core #2.

    Args:
        user: The authenticated caller.
        session: Request-scoped database session.

    Returns:
        The verified patient scope holder.

    Raises:
        HTTPException: 403 with a machine-readable code if no live verification exists.
    """
    # Identity comes from patients.auth_user_id, which is UNIQUE, and the verification row
    # only proves that link is currently live. Reading the patient off the verification row
    # instead would be ambiguous: nothing stops two live verification rows existing for one
    # login, and the caller would then get whichever one sorted first.
    patient_id = await session.scalar(
        select(Patient.id)
        .join(IdentityVerification, IdentityVerification.patient_id == Patient.id)
        .where(
            Patient.auth_user_id == user.auth_user_id,
            IdentityVerification.auth_user_id == user.auth_user_id,
            IdentityVerification.revoked_at.is_(None),
            IdentityVerification.expires_at > datetime.now(UTC),
        )
        .limit(1)
    )
    if patient_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": IDENTITY_REQUIRED_CODE, "message": "Identity verification required."},
        )
    return VerifiedPatient(auth_user_id=user.auth_user_id, patient_id=patient_id)


async def get_patient_scope(
    patient: Annotated[VerifiedPatient, Depends(get_verified_patient)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> PatientScope:
    """Build the scoped PHI accessor for the verified caller.

    This is the only place a `PatientScope` is constructed, which is what makes the scope
    impossible to obtain without passing both checks above.

    Args:
        patient: The verified patient.
        session: Request-scoped database session.
        request: Used to correlate audit entries with the request log.

    Returns:
        A scope limited to this patient's data.
    """
    request_id = getattr(request.state, "request_id", None)
    return PatientScope(session, patient.patient_id, request_id=request_id)
