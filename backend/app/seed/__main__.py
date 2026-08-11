import argparse
import asyncio
import sys
from datetime import UTC, datetime

import asyncpg
import structlog

from app.config import get_settings
from app.logging import configure_logging
from app.seed import auth, rows
from app.seed.assets import upload_plan
from app.seed.profiles import DEMO_PASSWORD, Profile, build_plan

logger = structlog.get_logger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Argument list, defaulting to sys.argv.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(prog="python -m app.seed", description="Seed the portal.")
    parser.add_argument(
        "--profile",
        type=Profile,
        choices=list(Profile),
        default=Profile.DEMO,
        help="demo is a small hand-built dataset; full is the benchmark dataset.",
    )
    parser.add_argument(
        "--reset", action="store_true", help="Delete existing seeded data before inserting."
    )
    parser.add_argument("--skip-assets", action="store_true", help="Insert rows only, no uploads.")
    parser.add_argument("--skip-auth", action="store_true", help="Do not create login accounts.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and measure assets without uploading or writing rows.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    """Execute the seed.

    Args:
        args: Parsed arguments.

    Returns:
        Process exit code.
    """
    settings = get_settings()
    plan = build_plan(args.profile, datetime.now(UTC))

    logger.info(
        "seed.plan",
        profile=plan.name,
        providers=len(plan.providers),
        patients=len(plan.patients),
        studies=len(plan.studies),
        assets=plan.asset_count(),
    )

    if args.dry_run:
        summary = await upload_plan(plan, settings, dry_run=True)
        logger.info(
            "seed.dry_run_complete",
            assets=len(summary.sizes),
            megabytes=round(summary.total_bytes / 1024 / 1024, 1),
        )
        return 0

    dsn = str(settings.database_url).replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        if await rows.is_populated(conn):
            if not args.reset:
                logger.error("seed.refusing_to_overwrite")
                print(
                    "Database already contains seeded data. Re-run with --reset to replace it.",
                    file=sys.stderr,
                )
                return 1
            await rows.reset(conn)

        await rows.insert_plan(conn, plan)

        if not args.skip_assets:
            existing = await rows.storage_object_names(conn, settings.supabase_storage_bucket)
            summary = await upload_plan(plan, settings, existing=existing)
            await rows.update_asset_sizes(conn, summary.sizes)
    finally:
        await conn.close()

    if not args.skip_auth:
        await auth.create_logins(plan, settings)

    logger.info("seed.complete", profile=plan.name)
    _print_credentials(plan)
    return 0


def _print_credentials(plan: object) -> None:
    """Print the demo logins a reviewer needs.

    Args:
        plan: The seeded plan; unused beyond signalling completion.
    """
    print("\nDemo accounts (password for all: " + DEMO_PASSWORD + ")")
    print("  patient@demo.test     account AS-100241, DOB 1991-06-24")
    print("  neighbour@demo.test   account AS-100377, DOB 1985-02-09")
    print("  provider@demo.test    provider login")
    print("  admin@demo.test       front-desk login")


def main() -> int:
    """Entry point.

    Returns:
        Process exit code.
    """
    configure_logging()
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
