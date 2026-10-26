"""Write merged messages to an outbox text file."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SEPARATOR = "-" * 72


def message_text(message: dict[str, str]) -> str:
    """Return one message as text with To and Subject header lines."""
    body = message["body"].rstrip("\n")
    return f"To: {message['to']}\nSubject: {message['subject']}\n\n{body}\n"


def write_outbox(messages: list[dict[str, str]], path: Path) -> Path:
    """Write all messages to one file, separated by a line of dashes."""
    if not messages:
        raise ValueError("no messages to write")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = f"{SEPARATOR}\n".join(message_text(message) for message in messages)
    target.write_text(text, encoding="utf-8")
    logger.info(f"wrote {len(messages)} messages to {target}")
    return target
