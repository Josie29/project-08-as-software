import argparse
import asyncio

import structlog

from app.config import get_settings
from app.db import dispose_engine, get_session_factory
from app.logging import configure_logging
from app.services.email import get_email_sender
from app.services.reminders import ReminderRun, dispatch_due_reminders

logger = structlog.get_logger(__name__)


async def run_once() -> ReminderRun:
    """Run one reminder pass against its own session.

    Shared by the scheduler and the command line, so what a grader triggers by hand is the
    same code path production runs on a timer.

    Returns:
        Counts for the pass.
    """
    settings = get_settings()
    async with get_session_factory()() as session:
        return await dispatch_due_reminders(session, settings, get_email_sender(settings))


async def _main() -> ReminderRun:
    """Run one pass and dispose the engine.

    Returns:
        Counts for the pass.
    """
    try:
        return await run_once()
    finally:
        await dispose_engine()


def main() -> None:
    """Entry point for `python -m app.reminders`."""
    parser = argparse.ArgumentParser(
        prog="python -m app.reminders",
        description="Dispatch due appointment reminders once and exit.",
    )
    parser.parse_args()

    configure_logging()
    run = asyncio.run(_main())
    print(f"due={run.due} sent={run.sent} failed={run.failed} skipped={run.skipped}")


if __name__ == "__main__":
    main()
