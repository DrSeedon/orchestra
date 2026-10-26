"""Build one message per recipient from a subject line and a body template."""
import logging
from typing import Optional

from .template import render, template_fields

logger = logging.getLogger(__name__)


def missing_fields(text: str, columns: list[str],
                   defaults: Optional[dict[str, str]] = None) -> list[str]:
    """Return the template fields that neither the columns nor the defaults provide."""
    known = set(columns) | set(defaults or {})
    return [name for name in template_fields(text) if name not in known]


def build_message(subject: str, body: str, recipient: dict[str, str],
                  defaults: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Return the message (to, subject, body) for one recipient."""
    return {
        "to": recipient["email"],
        "subject": render(subject, recipient, defaults),
        "body": render(body, recipient, defaults),
    }


def build_messages(subject: str, body: str, recipients: list[dict[str, str]],
                   defaults: Optional[dict[str, str]] = None) -> list[dict[str, str]]:
    """Build the messages for all recipients. A recipient with a missing value is skipped."""
    messages = []
    for recipient in recipients:
        try:
            messages.append(build_message(subject, body, recipient, defaults))
        except ValueError as exc:
            logger.warning(f"{recipient['email']}: {exc}, recipient skipped")
    logger.info(f"built {len(messages)} of {len(recipients)} messages")
    return messages
