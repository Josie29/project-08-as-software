import asyncio
from typing import Any
from uuid import uuid4

import asyncpg
import httpx

from app.config import get_settings
from app.services.identity import RESPONSE_FLOOR_SECONDS


async def _verify(
    api: httpx.AsyncClient, headers: dict[str, str], account_id: str, dob: str
) -> httpx.Response:
    """Submit one verification attempt.

    Args:
        api: API client.
        headers: Authorization headers.
        account_id: Submitted account id.
        dob: Submitted date of birth.

    Returns:
        The response.
    """
    return await api.post(
        "/identity/verify",
        json={"account_id": account_id, "date_of_birth": dob},
        headers=headers,
    )


async def test_correct_details_unlock_the_patients_own_studies(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The whole point of Core #2: matching the paperwork links a login to a clinical record
    and opens that record only."""
    headers = auth_headers(uuid4())

    verified = await _verify(
        api, headers, seeded["demo_account_id"], seeded["demo_dob"].isoformat()
    )
    studies = await api.get("/studies", headers=headers)

    assert verified.status_code == 200
    assert studies.status_code == 200
    assert len(studies.json()) > 0


async def test_a_wrong_account_and_a_wrong_date_are_indistinguishable(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """The brief requires one generic error that never reveals which field was wrong.
    Different messages would let an attacker confirm that an account id is real and then
    concentrate on guessing only the date of birth.
    """
    unknown_account = await _verify(
        api, auth_headers(uuid4()), "AS-000000", seeded["demo_dob"].isoformat()
    )
    wrong_dob = await _verify(api, auth_headers(uuid4()), seeded["demo_account_id"], "1900-01-01")

    assert unknown_account.status_code == wrong_dob.status_code == 403
    assert unknown_account.json() == wrong_dob.json()


async def test_a_record_already_linked_to_someone_else_fails_identically(
    api: httpx.AsyncClient, db: asyncpg.Connection, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """An account-takeover attempt must look exactly like a typo. Revealing that the record
    is already claimed would confirm both factors were correct.
    """
    await db.execute(
        "UPDATE patients SET auth_user_id = $1 WHERE id = $2", uuid4(), seeded["demo_patient_id"]
    )

    attacker = await _verify(
        api, auth_headers(uuid4()), seeded["demo_account_id"], seeded["demo_dob"].isoformat()
    )
    typo = await _verify(api, auth_headers(uuid4()), "AS-000000", "1900-01-01")

    assert attacker.status_code == typo.status_code == 403
    assert attacker.json() == typo.json()


async def test_repeated_failures_lock_the_caller_out(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Without lockout, the date of birth is a guessable secret — roughly thirty thousand
    plausible values for a known account id, trivially brute-forced online.
    """
    headers = auth_headers(uuid4())
    limit = get_settings().identity_max_attempts

    for _ in range(limit):
        await _verify(api, headers, seeded["demo_account_id"], "1900-01-01")
    locked = await _verify(api, headers, seeded["demo_account_id"], "1900-01-01")

    assert locked.status_code == 429
    assert "Retry-After" in locked.headers


async def test_lockout_is_not_bypassed_by_using_a_fresh_login(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """Signup is unlimited, so a per-login counter alone protects nothing: an attacker just
    registers again. Attempts are therefore also counted against the submitted account id.
    """
    account = seeded["demo_account_id"]
    account_limit = get_settings().identity_max_attempts * 3

    for _ in range(account_limit):
        await _verify(api, auth_headers(uuid4()), account, "1900-01-01")

    # A caller who has never made an attempt of their own is still barred.
    fresh_login = await _verify(api, auth_headers(uuid4()), account, "1900-01-01")

    assert fresh_login.status_code == 429


async def test_every_outcome_takes_at_least_the_response_floor(
    api: httpx.AsyncClient, seeded: dict[str, Any], auth_headers: Any
) -> None:
    """A fast rejection and a slow one are themselves an oracle: response time would reveal
    whether the account id exists, undoing the identical error message.
    """
    loop = asyncio.get_running_loop()

    for account, dob in [
        (seeded["demo_account_id"], seeded["demo_dob"].isoformat()),
        (seeded["demo_account_id"], "1900-01-01"),
        ("AS-000000", "1900-01-01"),
    ]:
        started = loop.time()
        await _verify(api, auth_headers(uuid4()), account, dob)
        elapsed = loop.time() - started

        assert elapsed >= RESPONSE_FLOOR_SECONDS * 0.95, f"{account} answered in {elapsed:.3f}s"


async def test_a_submitted_date_of_birth_is_never_echoed_back(
    api: httpx.AsyncClient, auth_headers: Any
) -> None:
    """FastAPI's default validation handler returns the offending input. On this endpoint
    that would put a real patient's date of birth into the response body and the logs.
    """
    response = await api.post(
        "/identity/verify",
        json={"account_id": "AS-100241", "date_of_birth": "not-a-date"},
        headers=auth_headers(uuid4()),
    )

    assert response.status_code == 422
    assert "not-a-date" not in response.text
