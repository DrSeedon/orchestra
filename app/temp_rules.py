"""Временные правила агентам: живут в БД, входят в системный промпт, пока действуют.

Правило — изменяемое состояние, а не продуктовый текст пайплайна, поэтому оно лежит в
SQLite (таблица создаётся лениво, как quota_policy_history: схема БД версионирована и
требует офлайн-миграции), а не в git. Промпт собирается из актуальных строк при каждом
вызове, поэтому истёкшее правило пропадает само, без рестарта и уборки.

Что делать по сроку выбирает автор: `remove` — правило перестаёт действовать; `notify` —
правило остаётся в промпте, а автору один раз приходит сообщение, и он решает
(продлить, снять или оставить навсегда). Метка `notified_at` в БД даёт «один раз» и
переживает рестарт.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone

from app import db
from app.prompting import is_orchestrator_role

logger = logging.getLogger(__name__)

# Project that may set rules for every project at once.
ORCHESTRA_SCOPE = str(db._REPO_ROOT)
ORCHESTRA_ORCHESTRATOR = "Orchestra-orchestrator"
GLOBAL = "*"
GROUP_TARGETS = frozenset({"all", "orchestrators", "workers"})
ON_EXPIRE = frozenset({"remove", "notify"})
_BLOCK = re.compile(r"\n*(<temporary-rules>.*?</temporary-rules>)", re.DOTALL)


class RuleError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise RuleError(422, "expires_at must be an ISO UTC timestamp, e.g. 2026-10-20T07:00Z")
    if moment.tzinfo is None:
        raise RuleError(422, "expires_at must carry a timezone (use Z for UTC)")
    return moment.astimezone(timezone.utc)


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS temp_rules (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            project TEXT NOT NULL,
            targets TEXT NOT NULL,
            expires_at TEXT,
            on_expire TEXT NOT NULL,
            author_session_id TEXT NOT NULL,
            author_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            removed_at TEXT,
            notified_at TEXT
        )"""
    )


def _is_orchestra_orchestrator(actor: dict) -> bool:
    return (
        actor.get("name") == ORCHESTRA_ORCHESTRATOR
        and (actor.get("scope") or "").rstrip("/") == ORCHESTRA_SCOPE.rstrip("/")
    )


def _require_orchestrator(actor: dict | None) -> dict:
    if not actor or not (
        actor.get("is_orchestrator") or is_orchestrator_role(actor.get("role") or "")
    ):
        raise RuleError(403, "temporary rules can be managed by orchestrators only")
    return actor


def _authorize_project(actor: dict, project: str) -> None:
    """Own project always; every project only for the Orchestra orchestrator."""
    if project == GLOBAL:
        if not _is_orchestra_orchestrator(actor):
            raise RuleError(403, "rules for all projects can be set only by the Orchestra project orchestrator")
        return
    if project.rstrip("/") != (actor.get("scope") or "").rstrip("/") and not _is_orchestra_orchestrator(actor):
        raise RuleError(403, "an orchestrator can manage rules of its own project only")


def _row(conn: sqlite3.Connection, rule_id: str) -> dict:
    found = conn.execute("SELECT * FROM temp_rules WHERE id=?", (rule_id,)).fetchone()
    if found is None or found["removed_at"]:
        raise RuleError(404, f"no such rule: {rule_id}")
    return dict(found)


def _view(row: dict) -> dict:
    return {**row, "targets": json.loads(row["targets"])}


def _check_targets(targets: list[str]) -> list[str]:
    cleaned = [t.strip() for t in targets if isinstance(t, str) and t.strip()]
    if not cleaned:
        raise RuleError(422, "targets is required: all | orchestrators | workers | <role> | agent:<name>")
    return cleaned


def add_rule(
    actor: dict | None, text: str, targets: list[str], expires_at: str,
    *, project: str = "", on_expire: str = "remove",
) -> dict:
    actor = _require_orchestrator(actor)
    text = (text or "").strip()
    if not text:
        raise RuleError(422, "rule text is required")
    if "</temporary-rules>" in text or "<temporary-rules>" in text:
        raise RuleError(422, "rule text must not contain the temporary-rules tag")
    if on_expire not in ON_EXPIRE:
        raise RuleError(422, f"on_expire must be {'|'.join(sorted(ON_EXPIRE))}")
    deadline = _parse_utc(expires_at)
    if deadline <= _now():
        raise RuleError(422, "expires_at is already in the past")
    project = (project or actor.get("scope") or "").strip()
    _authorize_project(actor, project)
    rule = {
        "id": f"rule-{hashlib.sha1(f'{_now().isoformat()}{text}'.encode()).hexdigest()[:10]}",
        "text": text, "project": project if project == GLOBAL else project.rstrip("/"),
        "targets": json.dumps(_check_targets(targets), ensure_ascii=False),
        "expires_at": deadline.isoformat(), "on_expire": on_expire,
        "author_session_id": actor["id"], "author_name": actor["name"],
        "created_at": _now().isoformat(), "removed_at": None, "notified_at": None,
    }
    with db._conn() as conn:
        _schema(conn)
        conn.execute(
            "INSERT INTO temp_rules VALUES(:id,:text,:project,:targets,:expires_at,:on_expire,"
            ":author_session_id,:author_name,:created_at,:removed_at,:notified_at)", rule,
        )
    return _view(rule)


def _is_active(row: dict, now: datetime) -> bool:
    if row["removed_at"]:
        return False
    if row["on_expire"] == "notify" or not row["expires_at"]:
        return True
    return datetime.fromisoformat(row["expires_at"]) > now


def list_rules(actor: dict | None, *, include_inactive: bool = False) -> list[dict]:
    actor = _require_orchestrator(actor)
    scope = (actor.get("scope") or "").rstrip("/")
    with db._conn() as conn:
        _schema(conn)
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM temp_rules WHERE removed_at IS NULL ORDER BY created_at, id")]
    now = _now()
    return [
        {**_view(r), "active": _is_active(r, now)} for r in rows
        if (_is_orchestra_orchestrator(actor) or r["project"] in (scope, GLOBAL))
        and (include_inactive or _is_active(r, now))
    ]


def remove_rule(actor: dict | None, rule_id: str) -> dict:
    actor = _require_orchestrator(actor)
    with db._conn() as conn:
        _schema(conn)
        row = _row(conn, rule_id)
        _authorize_project(actor, row["project"])
        conn.execute("UPDATE temp_rules SET removed_at=? WHERE id=?", (_now().isoformat(), rule_id))
    return {"ok": True, "id": rule_id}


def update_rule(
    actor: dict | None, rule_id: str, *, expires_at: str = "", keep: bool = False,
) -> dict:
    """Extend the deadline (re-arms the one-time notice) or keep the rule with no deadline."""
    actor = _require_orchestrator(actor)
    if bool(expires_at) == bool(keep):
        raise RuleError(422, "pass either expires_at (extend) or keep=true")
    with db._conn() as conn:
        _schema(conn)
        row = _row(conn, rule_id)
        _authorize_project(actor, row["project"])
        if keep:
            conn.execute("UPDATE temp_rules SET expires_at=NULL, on_expire='notify' WHERE id=?", (rule_id,))
        else:
            deadline = _parse_utc(expires_at)
            if deadline <= _now():
                raise RuleError(422, "expires_at is already in the past")
            conn.execute(
                "UPDATE temp_rules SET expires_at=?, notified_at=NULL WHERE id=?",
                (deadline.isoformat(), rule_id),
            )
        return _view(_row(conn, rule_id))


def _applies(row: dict, *, role: str, is_orch: bool, scope: str, name: str) -> bool:
    if row["project"] not in (GLOBAL, scope.rstrip("/")):
        return False
    for target in json.loads(row["targets"]):
        if (
            target == "all"
            or (target == "orchestrators" and is_orch)
            or (target == "workers" and not is_orch)
            or target == role
            or target == f"agent:{name}"
        ):
            return True
    return False


def active_block(*, role: str, is_orch: bool, scope: str, name: str) -> str:
    """Prompt block for one agent; empty when no active rule targets it."""
    try:
        with db._conn() as conn:
            _schema(conn)
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM temp_rules WHERE removed_at IS NULL ORDER BY created_at, id")]
    except sqlite3.Error as error:
        # Prompt assembly is on every turn's hot path; a storage hiccup must not stop turns.
        logger.warning("temporary rules unreadable, prompt built without them: %s", error)
        return ""
    now = _now()
    lines = []
    for row in rows:
        if _is_active(row, now) and _applies(row, role=role, is_orch=is_orch, scope=scope, name=name):
            until = f"until {row['expires_at']}" if row["expires_at"] else "no deadline"
            lines.append(f"- ({until}, set by {row['author_name']}) {row['text']}")
    if not lines:
        return ""
    return (
        "<temporary-rules>\nTemporary rules currently in force; they drop out of this prompt "
        "by themselves when they end.\n" + "\n".join(lines) + "\n</temporary-rules>"
    )


def strip_block(prompt: str) -> str:
    return _BLOCK.sub("", prompt)


def with_block(prompt: str, **agent) -> str:
    """Replace the temporary-rules block of an assembled prompt with the current one."""
    prompt = strip_block(prompt)
    block = active_block(**agent)
    return f"{prompt}\n\n{block}" if block else prompt


def fingerprint(**agent) -> str:
    return block_fingerprint(active_block(**agent))


def block_fingerprint(prompt: str) -> str:
    found = _BLOCK.search(prompt)
    return hashlib.md5(found.group(1).encode()).hexdigest()[:8] if found else ""


def claim_due_notices() -> list[dict]:
    """Notify-mode rules past their deadline whose author has not been told yet."""
    now = _now().isoformat()
    with db._conn() as conn:
        _schema(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM temp_rules WHERE removed_at IS NULL AND on_expire='notify' "
            "AND expires_at IS NOT NULL AND expires_at<=? AND notified_at IS NULL", (now,))]


def mark_notified(rule_id: str) -> bool:
    with db._conn() as conn:
        _schema(conn)
        cursor = conn.execute(
            "UPDATE temp_rules SET notified_at=? WHERE id=? AND notified_at IS NULL",
            (_now().isoformat(), rule_id),
        )
        return cursor.rowcount == 1


def notice_text(row: dict) -> str:
    return (
        f"Temporary rule {row['id']} reached its deadline ({row['expires_at']}) and is STILL IN FORCE "
        f"for project {row['project']}, targets {row['targets']}: «{row['text']}». "
        f"Decide: extend (temp_rule_update with expires_at), keep without a deadline "
        f"(temp_rule_update keep=true) or remove (temp_rule_remove). This notice is sent once."
    )


async def notify_due(session_manager) -> int:
    """Send each due notice once; the DB mark survives a restart. Returns notices sent."""
    from app.events import MessageProvenance

    sent = 0
    for row in claim_due_notices():
        author = db.get_session(row["author_session_id"])
        if author and author.get("status") != "archived":
            try:
                await session_manager.send(
                    author["id"], notice_text(row),
                    provenance=MessageProvenance(
                        origin="platform", senders=("Orchestra",), subtype="temp_rule", ref=row["id"]),
                )
            except Exception as error:
                logger.warning("temp rule %s: notice failed, will retry: %s", row["id"], error)
                continue
            sent += 1
        else:
            logger.warning("temp rule %s: author %s is gone, no one to notify", row["id"], row["author_name"])
        mark_notified(row["id"])
    return sent
