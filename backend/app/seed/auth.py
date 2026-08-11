import httpx
import structlog

from app.config import Settings
from app.seed.plan import SeedPlan

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 20.0


async def _create_user(
    client: httpx.AsyncClient, settings: Settings, email: str, password: str
) -> bool:
    """Create one confirmed Supabase Auth user.

    Args:
        client: HTTP client carrying the service-role credentials.
        settings: Application settings.
        email: Login address.
        password: Login password.

    Returns:
        True if a user was created, False if one already existed.

    Raises:
        httpx.HTTPStatusError: On any failure other than the address already existing.
    """
    response = await client.post(
        f"{settings.supabase_url}/auth/v1/admin/users",
        json={"email": email, "password": password, "email_confirm": True},
    )
    if response.status_code in (409, 422):
        return False
    response.raise_for_status()
    return True


async def create_logins(plan: SeedPlan, settings: Settings) -> None:
    """Create Supabase Auth accounts for every seeded login.

    Patient accounts are created without linking `patients.auth_user_id`. The link is made
    only by passing the Core #2 identity check, so a reviewer still sees that flow rather
    than arriving already verified.

    Args:
        plan: The seeded dataset.
        settings: Application settings.
    """
    accounts = [
        (patient.email, patient.login_password)
        for patient in plan.patients
        if patient.login_password
    ] + [(member.email, member.login_password) for member in plan.staff if member.login_password]

    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    created = 0
    existing = 0
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, headers=headers) as client:
        for email, password in accounts:
            if await _create_user(client, settings, email, password):
                created += 1
            else:
                existing += 1

    logger.info("seed.logins", created=created, already_present=existing)
