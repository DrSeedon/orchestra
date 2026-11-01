"""Shared literal inventory and hub credential shapes; never edits local data.

Stdlib only, including when called from another project's git hooks. Secret variable
names and the minimum length live here; secret_mask and hub reuse them.
This module imports only stdlib: hooks need no runtime-history or application setup.
Plain Git text delegates provider shapes to scripts/secret_scan.py. Hub uploads
and decoded archive payloads share the shapes below; plain-text policy is unchanged.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_MIN_LEN = 12
_SECRET_WORDS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "APIKEY",
    "COOKIE", "CREDENTIAL", "PRIVATE_KEY", "PASSPHRASE", "DATABASE_URL",
    "CONNECTION_STRING", "DSN", "AUTH_TOKEN", "API_HASH", "YANDEX_DIRECT_LOGIN",
)

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
HUB_SECRET_SHAPES = (
    ("private key", re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[ \t]*\r?\n"
        r"(?:[A-Za-z0-9+/=][\r\n]*){40,}"
    )),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}")),
    ("provider API key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{24,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
)
_SECRET_NAME = re.compile(
    r"(?:^|[_\-.])(?:" + "|".join(w.replace("_", "[_-]?") for w in _SECRET_WORDS)
    + r")(?:$|[_\-.])", re.I,
)
_ENV_ASSIGNMENT = re.compile(
    r'''^[ \t]*(?:export[ \t]+)?(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)[ \t]*=[ \t]*(?:"(?P<dq>(?:\\.|[^"\\])*)"|'(?P<sq>[^']*)'|(?P<bare>[^\r\n]*))''',
    re.M,
)


def secret_name(name: str) -> bool:
    # TOKEN_FILE/SECRET_PATH point at storage, not credential values.
    return (_SECRET_NAME.search(name) is not None
            and re.search(r"(?:^|[_-])(?:PATH|FILE|DIR)$", name, re.I) is None)


def credential_value(value: str) -> bool:
    """Exclude path/config values and explicit templates, not unshaped credentials."""
    value = value.strip()
    if len(value) < _MIN_LEN:
        return False
    if value.startswith(("/", "~/", "./", "../")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return False
    lower = value.lower()
    if re.fullmatch(r"\$?\{[^}]+\}|<[^>]+>|\[[^]]+\]", value):
        return False
    if lower.startswith(("your_", "your-", "replace_", "replace-", "example_", "example-",
                         "changeme", "change-me-", "change_me_", "placeholder")):
        return False
    return lower not in {"changeme", "change-me", "change_me", "placeholder", "not-a-real-secret"}


def main_checkout(repo: str | Path) -> Path:
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True, text=True,
    )
    if done.returncode:
        raise RuntimeError("publish guard: cannot resolve project's git common directory")
    return Path(done.stdout.strip()).parent


def _env_values(path: Path) -> list[tuple[str, str]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return []
    values = []
    context = dict(os.environ)
    for match in _ENV_ASSIGNMENT.finditer(text):
        key = match["key"]
        if match["dq"] is not None:
            value = re.sub(r'\\([nrt"\\])', lambda m: {
                "n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\",
            }[m[1]], match["dq"])
        elif match["sq"] is not None:
            value = match["sq"]
        else:
            value = re.split(r"\s+#", match["bare"], maxsplit=1)[0].strip()
        value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}",
                       lambda m: context.get(m[1], m[2] if m[2] is not None else m[0]), value)
        context[key] = value
        if secret_name(key) and credential_value(value):
            values.append((key, value))
    return values


def literal_rules(
    repo: str | Path | None = None, *, data_dir: Path | None = None,
) -> list[tuple[str, str]]:
    """Refresh per operation: process env, target + main .env, platform .env and secrets.

    Missing sources are normal; unreadable sources fail closed. Environment names
    must look secret. Files explicitly stored under data/secrets are credentials
    regardless of basename (including legacy names such as `tok`).
    """
    root = PLATFORM_ROOT
    env_files = {root / ".env"}
    if repo is not None:
        env_files.update({Path(repo) / ".env", main_checkout(repo) / ".env"})
    rules = [(f"env {key}", value.strip()) for key, value in os.environ.items()
             if secret_name(key) and credential_value(value)]
    for path in sorted(env_files):
        rules.extend((f".env {key}", value) for key, value in _env_values(path))
    directory = (data_dir if data_dir is not None else root / "data") / "secrets"
    if directory.exists():
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path.name == "forbidden-strings.txt":
                continue  # This is a rule list, parsed line by line by forbidden_strings.
            # These files are local credentials, not source artifacts. Never truncate
            # silently: a truncated inventory would allow the full value to escape.
            text = path.read_text(encoding="utf-8").strip()
            if credential_value(text):
                rules.append((f"secret file {path.name}", text))
    return list(dict.fromkeys(rules))


def safe_text(text: str, rules: list[tuple[str, str]]) -> str:
    """Diagnostic labels and paths can themselves contain secrets."""
    for _, value in sorted(rules, key=lambda item: len(item[1]), reverse=True):
        text = text.replace(value, "[redacted]")
    return text


def findings(text: str, origin: str, rules: list[tuple[str, str]]) -> list[str]:
    names = [name for name, value in rules if value in text]
    return [safe_text(f"{origin}: {name}", rules) for name in names]


def content_findings(text: str, path: str, rules: list[tuple[str, str]], first_line: int = 1) -> list[str]:
    matches = [(name, text.find(value)) for name, value in rules if value in text]
    return [safe_text(f"{path}:{first_line + text.count(chr(10), 0, offset)}: {name}", rules)
            for name, offset in matches]


def archive_safe_text(text: str, rules: list[tuple[str, str]]) -> str:
    """Archive member names, too, can contain credential literals or shapes."""
    text = safe_text(text, rules)
    for _, pattern in HUB_SECRET_SHAPES:
        text = pattern.sub("[redacted]", text)
    return text


def archive_findings(text: str, path: str, rules: list[tuple[str, str]]) -> list[str]:
    """Archive payloads bypass the canonical scanner's plain-text diff."""
    found = content_findings(text, path, rules)
    for name, pattern in HUB_SECRET_SHAPES:
        if match := pattern.search(text):
            line = 1 + text.count("\n", 0, match.start())
            found.append(f"{path}:{line}: {name}")
    return [archive_safe_text(row, rules) for row in found]
