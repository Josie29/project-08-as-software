import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

# Settings are read at import time by app.main, so the test environment must be in
# place before the application package is imported.
os.environ.setdefault("APP_ENV", "ci")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://portal:portal@localhost:5433/portal_test"
)
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

import asyncpg
import httpx
from asgi_lifespan import LifespanManager

from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: Must survive truncation or the migration state is lost mid-run.
_ALEMBIC_VERSION_TABLE = "alembic_version"


def asyncpg_dsn() -> str:
    """Return the test database URL as a libpq URI.

    SQLAlchemy's `postgresql+asyncpg://` scheme is not valid libpq, so the suffix comes off.

    Returns:
        A libpq-style connection URI.
    """
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Apply migrations to the throwaway test database for the whole session.

    Run via subprocess because `alembic/env.py` calls `asyncio.run`, which cannot nest
    inside a running loop. Tests hit the real migration, not `metadata.create_all`, so a
    constraint missing from the migration fails here rather than in production.

    Yields:
        The database URL the migrations were applied to.

    Raises:
        subprocess.CalledProcessError: If the migration fails to apply.
    """
    subprocess.run(
        ["alembic", "upgrade", "head"], cwd=BACKEND_ROOT, check=True, capture_output=True
    )
    yield os.environ["DATABASE_URL"]
    subprocess.run(
        ["alembic", "downgrade", "base"], cwd=BACKEND_ROOT, check=False, capture_output=True
    )


@pytest.fixture
async def db(migrated_database: str) -> AsyncIterator[asyncpg.Connection]:
    """Yield a raw asyncpg connection to the migrated test database.

    Raw rather than an ORM session: the concurrency test needs independent transactions.

    Yields:
        An open `asyncpg.Connection`, truncated clean on teardown.
    """
    conn = await asyncpg.connect(asyncpg_dsn())
    try:
        yield conn
    finally:
        # Reflected rather than hardcoded so a new table cannot be forgotten here.
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> $1",
            _ALEMBIC_VERSION_TABLE,
        )
        if rows:
            names = ", ".join(row["tablename"] for row in rows)
            await conn.execute(f"TRUNCATE {names} CASCADE")
        await conn.close()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield an HTTP client wired directly to the ASGI app.

    Goes through the real middleware and dependency stack without binding a port.

    Yields:
        An `httpx.AsyncClient` targeting the application.
    """
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
