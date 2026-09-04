"""Shared credential detection used by validation and archive redaction."""

import re


SECRET_KEY_PARTS = frozenset({"password", "passwd", "secret", "token", "credential"})
SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "access_key", "secret_key", "private_key",
    "authorization", "client_secret", "credential_material",
})
SECRET_VALUE_PATTERN = re.compile(
    r"(?:Bearer\s+\S{20,}|sk-(?:or-v1-)?[A-Za-z0-9_-]{8,}|"
    r"gh[pousr]_[A-Za-z0-9]{8,}|ya29\.[A-Za-z0-9_-]{8,}|"
    r"AIza[A-Za-z0-9_-]{12,}|(?:^|_)(?:SECRET|PASSWORD|CREDENTIAL)(?:_|$)|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret)="
    r"[^\s&]{4,})"
)


def key_looks_secret(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return normalized in SECRET_KEY_NAMES or bool(
        set(normalized.split("_")) & SECRET_KEY_PARTS
    )
