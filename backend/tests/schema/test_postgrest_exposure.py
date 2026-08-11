import asyncpg

#: Holds a revision hash, no PHI, and is not created by our migration.
_EXCLUDED_TABLES = {"alembic_version"}


async def test_every_table_has_row_level_security_enabled(db: asyncpg.Connection) -> None:
    """A table without RLS is readable through Supabase's PostgREST endpoint by anyone
    holding the browser's publishable key, bypassing this API entirely. Guards against a
    later migration silently reopening that hole. See docs/schema.md.
    """
    rows = await db.fetch(
        """
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
        """
    )

    unprotected = sorted(row["table_name"] for row in rows)
    unprotected = [name for name in unprotected if name not in _EXCLUDED_TABLES]
    assert not unprotected, (
        "these tables are exposed to the anon key via PostgREST: "
        f"{unprotected}. Add them to _APPLICATION_TABLES in the migration."
    )


async def test_row_level_security_does_not_lock_out_the_api(db: asyncpg.Connection) -> None:
    """FORCE would apply RLS to the table owner too, locking the API out of its own data."""
    rows = await db.fetch(
        """
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity
        """
    )

    forced = sorted(row["table_name"] for row in rows)
    assert not forced, f"FORCE ROW LEVEL SECURITY would lock the API out of: {forced}"

    # The API's own connection must still read freely.
    assert await db.fetchval("SELECT count(*) FROM patients") is not None
