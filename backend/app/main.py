import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import appointments, availability, cine, health, identity, reports, shares, studies
from app.config import get_settings
from app.db import dispose_engine
from app.logging import configure_logging
from app.reminders import run_forever

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Configure logging, start the reminder job, and release resources on shutdown.

    The reminder job runs in this process rather than as a separate service. It is safe to
    run in every replica: each appointment is claimed through a unique constraint before
    any mail is sent, so duplicate schedulers cannot produce duplicate reminders.

    Args:
        _app: The FastAPI application; unused.

    Yields:
        Control back to the server for the lifetime of the application.
    """
    configure_logging()
    settings = get_settings()
    logger.info("app.startup", env=settings.app_env)

    # One task awaiting one coroutine, rather than a scheduler library: passes cannot
    # overlap because the loop awaits each before sleeping again, which is the only
    # scheduling property this job needs.
    reminders: asyncio.Task[None] | None = None
    if settings.reminder_scheduler_enabled:
        reminders = asyncio.create_task(
            run_forever(settings.reminder_poll_minutes * 60), name="reminder-loop"
        )
        logger.info("reminder.loop_started", poll_minutes=settings.reminder_poll_minutes)

    yield

    if reminders is not None:
        reminders.cancel()
        # Awaited rather than abandoned so a pass mid-flight finishes unwinding before the
        # engine goes away underneath it.
        with suppress(asyncio.CancelledError):
            await reminders
    await dispose_engine()
    logger.info("app.shutdown")


app = FastAPI(
    title="Patient Imaging, Reports & Scheduling Portal API",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(identity.router)
app.include_router(studies.router)
app.include_router(cine.router)
app.include_router(reports.router)
app.include_router(shares.router)
app.include_router(appointments.router)
app.include_router(availability.router)


@app.middleware("http")
async def attach_request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    """Give every request an id shared by the application log and the audit log.

    Correlating the two is what lets an access recorded in `audit_log` be traced back to the
    request that caused it, without putting PHI in either.

    Args:
        request: The incoming request.
        call_next: The rest of the middleware chain.

    Returns:
        The downstream response, carrying the request id.
    """
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.unbind_contextvars("request_id")
    response.headers["x-request-id"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return validation errors without echoing what was submitted.

    FastAPI's default handler includes the offending value in `detail[].input`. On the
    identity endpoint that would put a submitted date of birth straight into the response
    body and any log that captured it.

    Args:
        request: The incoming request.
        exc: The validation error.

    Returns:
        A field-level error report with all submitted values stripped.
    """
    logger.info("request.validation_failed", path=request.url.path)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                {
                    "loc": error.get("loc", []),
                    "msg": error.get("msg", "invalid"),
                    "type": error.get("type", ""),
                }
                for error in exc.errors()
            ]
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert any unhandled exception into a generic 500 with a structured log line.

    The response body is deliberately generic: it must never echo request contents,
    which on PHI routes could carry patient data.

    Args:
        request: The incoming request.
        exc: The unhandled exception.

    Returns:
        A generic JSON error response.
    """
    logger.error(
        "request.unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=type(exc).__name__,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An unexpected error occurred."},
    )
