"""Claude Max monthly API-credit fallback state and usage estimate."""

from __future__ import annotations

import os
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from app import db

logger = logging.getLogger("orchestra.claude_api_credits")


API_KEY_ENV = "ORCHESTRA_CLAUDE_CREDIT_API_KEY"
FALLBACK_FLAG_ENV = "CLAUDE_API_CREDIT_FALLBACK_ENABLED"
EXHAUSTED_KV_KEY = "claude_api_credit_fallback_exhausted_until"
UNRESOLVED_KV_KEY = "claude_api_credit_usage_unresolved_until"

# Console showed $199.72 after the owner's $0.288 probe. The following isolated
# Agent SDK probes reported $0.045096 before V-774 usage tracking was installed.
BALANCE_BASELINE_USD = 199.674904
BALANCE_BASELINE_AT = "2026-10-08T09:23:30+00:00"
CREDITS_EXPIRE_AT = "2026-11-04T00:00:00+00:00"
_DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_STARTUP_FLAG_VALUE = os.environ.get(FALLBACK_FLAG_ENV)
try:
    _STARTUP_FILE_FLAG_VALUE = dotenv_values(_DOTENV_PATH).get(FALLBACK_FLAG_ENV)
except OSError:
    _STARTUP_FILE_FLAG_VALUE = None
_DOTENV_OWNS_FLAG = (
    _STARTUP_FLAG_VALUE is not None
    and _STARTUP_FLAG_VALUE == _STARTUP_FILE_FLAG_VALUE
)


def _tracking_snapshot() -> tuple[float | None, bool]:
    baseline = datetime.fromisoformat(BALANCE_BASELINE_AT)
    with db._conn() as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(turn_usage)").fetchall()
        }
        if not {"billing_mode", "cost_usd", "cost_unaccounted", "ts"} <= columns:
            return None, False
        row = connection.execute(
            """SELECT COALESCE(SUM(CASE
                       WHEN cost_unaccounted=0 AND cost_usd IS NOT NULL THEN cost_usd
                       ELSE 0 END), 0) AS spent,
                      COALESCE(SUM(CASE
                       WHEN cost_unaccounted=1 OR cost_usd IS NULL THEN 1
                       ELSE 0 END), 0) AS unknown
               FROM turn_usage
               WHERE billing_mode='api_credit' AND ts >= ?""",
            (baseline.isoformat(),),
        ).fetchone()
    if int(row["unknown"] or 0):
        return None, False
    return max(0.0, BALANCE_BASELINE_USD - float(row["spent"] or 0)), True


def _fallback_enabled() -> bool:
    try:
        file_values = dotenv_values(_DOTENV_PATH)
    except OSError:
        file_values = {}
    file_value = file_values.get(FALLBACK_FLAG_ENV)
    if _DOTENV_OWNS_FLAG:
        raw = file_value
    else:
        raw = os.environ.get(FALLBACK_FLAG_ENV, file_value)
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def credit_status(*, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    expires_at = datetime.fromisoformat(CREDITS_EXPIRE_AT).astimezone(timezone.utc)
    enabled = _fallback_enabled()
    key_present = bool(os.environ.get(API_KEY_ENV, "").strip())
    try:
        remaining, tracking_complete = _tracking_snapshot()
        exhausted_until = db.kv_get(EXHAUSTED_KV_KEY)
        unresolved_until = db.kv_get(UNRESOLVED_KV_KEY)
    except sqlite3.Error as error:
        logger.warning("Claude API-credit ledger unavailable: %s", type(error).__name__)
        remaining, tracking_complete, exhausted_until, unresolved_until = None, False, "", ""
    if unresolved_until == CREDITS_EXPIRE_AT:
        tracking_complete = False
    provider_exhausted = exhausted_until == CREDITS_EXPIRE_AT
    if provider_exhausted or now >= expires_at:
        remaining = 0.0
    if not enabled:
        reason = "disabled"
    elif not key_present:
        reason = "missing_key"
    elif now >= expires_at:
        reason = "expired"
    elif provider_exhausted:
        reason = "exhausted"
    elif not tracking_complete:
        reason = "unknown_usage"
    elif remaining is None or remaining <= 0:
        reason = "exhausted"
    else:
        reason = "available"
    return {
        "enabled": enabled,
        "available": reason == "available",
        "reason": reason,
        "remaining_usd": remaining,
        "tracked_spend_usd": (
            None
            if provider_exhausted or not tracking_complete or remaining is None
            else max(0.0, BALANCE_BASELINE_USD - remaining)
        ),
        "baseline_at": BALANCE_BASELINE_AT,
        "expires_at": CREDITS_EXPIRE_AT,
        "tracking_complete": tracking_complete,
        "balance_basis": "console_baseline_minus_turn_usage_api_credit",
    }


def mark_credits_exhausted() -> None:
    db.kv_set(EXHAUSTED_KV_KEY, CREDITS_EXPIRE_AT)


def mark_credit_usage_unresolved() -> None:
    db.kv_set(UNRESOLVED_KV_KEY, CREDITS_EXPIRE_AT)


def is_credit_exhaustion_error(*values: object) -> bool:
    for value in values:
        text = str(value or "").lower()
        if (
            "your credit balance is too low to access the anthropic api" in text
            or "credit balance too low · add funds" in text
        ):
            return True
    return False
