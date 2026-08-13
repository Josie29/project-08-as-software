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

#: Reminders go to the patient's own address, not to a third party, so the appointment
#: time is the patient's own information reaching them. It is included because a reminder
#: without a time cannot reduce a no-show, which is the entire point of Core #15. Anything
#: that would still be exposed to Resend needlessly is left out: no patient name, no
#: clinician name, no reason for the visit, no account identifier.
REMINDER_SUBJECT = "Reminder: your upcoming appointment"

REMINDER_BODY_TEMPLATE = """This is a reminder of your upcoming appointment.

When: {when}

Details, rescheduling and cancellation are in your portal:
{link}

If you no longer need this appointment, please cancel it so the time can be offered to
someone else.
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
        return await self._send(recipient, SHARE_SUBJECT, SHARE_BODY_TEMPLATE.format(link=link))

    async def send_appointment_reminder(self, recipient: str, when: str, link: str) -> str | None:
        """Send an appointment reminder to the patient.

        Args:
            recipient: The patient's own address.
            when: The appointment time, already rendered in the clinic's timezone.
            link: URL of the patient's portal.

        Returns:
            The provider's message id, or None if sending is not configured.

        Raises:
            EmailError: If the provider rejects the message or is unreachable.
        """
        return await self._send(
            recipient, REMINDER_SUBJECT, REMINDER_BODY_TEMPLATE.format(when=when, link=link)
        )

    async def _send(self, recipient: str, subject: str, body: str) -> str | None:
        """Hand one message to Resend.

        Args:
            recipient: Address to deliver to.
            subject: Message subject.
            body: Plain-text body.

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
            "subject": subject,
            "text": body,
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
