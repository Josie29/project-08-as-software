import os
from collections.abc import AsyncIterator

import pytest

# Settings are read at import time by app.main, so the test environment must be in
# place before the application package is imported.
os.environ.setdefault("APP_ENV", "ci")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://portal:portal@localhost:5433/portal_test"
)
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

import httpx
from asgi_lifespan import LifespanManager

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield an HTTP client wired directly to the ASGI app.

    Requests go through the real middleware and dependency stack without binding a
    port, so tests exercise the same code path as a deployed request.

    Yields:
        An `httpx.AsyncClient` targeting the application.
    """
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
