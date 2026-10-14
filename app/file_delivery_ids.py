"""Canonical event identifiers for durable Telegram file delivery."""

from __future__ import annotations

import json
import uuid


def normalize_file_delivery_event_id(event_id: str, scope: str, sender: str) -> str:
    """Keep UUID identities stable and namespace caller keys by project and sender."""
    value = event_id.strip()
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            json.dumps(
                ["orchestra:file-delivery:v1", scope, sender, value],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ))
