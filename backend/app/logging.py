import logging
import sys

import structlog

from app.config import AppEnv, get_settings

# Keys that must never appear in a log event. PHI belongs in the audit log (which is
# access-controlled and append-only), never in application logs — see brief,
# "No PHI in logs". Log identifiers and references instead.
PHI_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "first_name",
        "last_name",
        "full_name",
        "dob",
        "date_of_birth",
        "email",
        "phone",
        "address",
        "ssn",
        "mrn",
        "patient_id_number",
        "account_id",
        "report_body",
        "findings",
        "impression",
        "password",
        "token",
        "share_token",
        "authorization",
    }
)

_REDACTED = "[redacted]"


def redact_phi(
    _logger: object, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Structlog processor that replaces any PHI-bearing key with a redaction marker.

    This is a backstop, not a licence to log PHI: call sites should pass identifiers
    (`patient_uuid`, `study_uuid`) rather than values that need redacting.

    Args:
        _logger: Unused; required by the structlog processor signature.
        _method: Unused; required by the structlog processor signature.
        event_dict: The event being logged.

    Returns:
        The event dict with PHI-bearing values replaced.
    """
    for key in list(event_dict):
        if key.lower() in PHI_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging() -> None:
    """Configure structlog for structured, PHI-free output.

    Emits key=value console output locally and JSON in every other environment so
    hosted logs stay machine-parseable.
    """
    settings = get_settings()
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.log_level.upper())

    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer()
        if settings.app_env is AppEnv.LOCAL
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_phi,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level.upper()]
        ),
        cache_logger_on_first_use=True,
    )
