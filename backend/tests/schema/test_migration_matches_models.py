import asyncpg

from app.models import Base


async def test_migration_creates_every_table_the_models_declare(db: asyncpg.Connection) -> None:
    """A model missing from a migration looks fine in the ORM, then fails at runtime
    against a freshly migrated database."""
    declared: set[str] = set(Base.metadata.tables)
    rows = await db.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    built: set[str] = {row["tablename"] for row in rows}

    assert declared <= built, f"declared but not migrated: {sorted(declared - built)}"


async def test_every_foreign_key_column_is_indexed(db: asyncpg.Connection) -> None:
    """Postgres does not index foreign keys automatically, and an unindexed FK turns joins
    and cascading deletes into full scans once the seeded dataset is large."""
    rows = await db.fetch(
        """
        SELECT c.conrelid::regclass::text AS table_name, a.attname AS column_name
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'f'
          AND NOT EXISTS (
              SELECT 1 FROM pg_index i
              WHERE i.indrelid = c.conrelid AND a.attnum = ANY (i.indkey)
          )
        """
    )

    unindexed = sorted(f"{row['table_name']}.{row['column_name']}" for row in rows)
    assert not unindexed, f"foreign keys without a supporting index: {unindexed}"
