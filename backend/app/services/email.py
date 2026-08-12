import httpx
import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 10.0
_RESEND_ENDPOINT = "https://api.resend.com/emails"

#: The message body carries a link and nothing else.
#:
#: The brief requires PHI to be kept out of anything a third party processes, and Resend
#: is exactly that. No patient name, no study description, no findings, no date of birth —
#: a recipient learns only that something was shared with them, and everything clinical
#: sits behind the link.
SHARE_SUBJECT = "Someone has shared a medical file with you"

SHARE_BODY_TEMPLATE = """A patient has shared a file with you through their care provider's portal.

Open it here:
{link}

This link expires on its own and can be switched off by the person who sent it. If you
were not expecting this, you can ignore this message — no action is needed.
"""


class EmailError(Exception):
    """Raised when a message could not be handed to the email provider."""


class EmailSender:
    """Sends share notifications through Resend."""

    def __init__(self, settings: Settings) -> None:
        """Initialise the sender.

        Args:
            settings: Supplies the API key and from address.
        """
        self._api_key = settings.resend_api_key
        self._from = settings.resend_from_email

    async def send_share_link(self, recipient: str, link: str) -> str | None:
        """Send a share notification.

        Args:
            recipient: Address to notify.
            link: The share URL.

        Returns:
            The provider's message id, or None if sending is not configured.

        Raises:
            EmailError: If the provider rejects the message or is unreachable.
        """
        if not self._api_key:
            # Not configured: the caller still gets its link, and the absence is logged
            # rather than surfacing as a failed share.
            logger.warning("email.not_configured")
            return None

        payload = {
            "from": self._from,
            "to": [recipient],
            "subject": SHARE_SUBJECT,
            "text": SHARE_BODY_TEMPLATE.format(link=link),
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    _RESEND_ENDPOINT,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.HTTPError as exc:
            logger.warning("email.unreachable", error=type(exc).__name__)
            raise EmailError("email provider unreachable") from exc

        if response.status_code >= 400:
            # The recipient address is not logged: it is contact information for someone
            # connected to a patient's care.
            logger.warning("email.rejected", status_code=response.status_code)
            raise EmailError(f"email provider returned {response.status_code}")

        message_id: str | None = response.json().get("id")
        logger.info("email.sent", provider_message_id=message_id)
        return message_id


def get_email_sender(settings: Settings) -> EmailSender:
    """Build an email sender.

    Args:
        settings: Application settings.

    Returns:
        A configured sender.
    """
    return EmailSender(settings)
