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
# mode → what the stored (on_expire, expires_at) pair means
#   expires   : on_expire=remove, deadline set — the rule drops out by itself
#   review    : on_expire=notify, deadline set — stays in force, the author is told once
#   permanent : on_expire=notify, no deadline — stays until removed
MODES = ("expires", "review", "permanent")
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
            notified_at TEXT,
            reason TEXT NOT NULL DEFAULT ''
        )"""
    )
    # Tables created before `reason` existed keep working; the column is added in place.
    if "reason" not in {r[1] for r in conn.execute("PRAGMA table_info(temp_rules)")}:
        conn.execute("ALTER TABLE temp_rules ADD COLUMN reason TEXT NOT NULL DEFAULT ''")


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


def _mode(row: dict) -> str:
    if not row["expires_at"]:
        return "permanent"
    return "review" if row["on_expire"] == "notify" else "expires"


def _view(row: dict) -> dict:
    return {**row, "targets": json.loads(row["targets"]), "mode": _mode(row)}


def _check_targets(targets: list[str]) -> list[str]:
    cleaned = [t.strip() for t in targets if isinstance(t, str) and t.strip()]
    if not cleaned:
        raise RuleError(422, "targets is required: all | orchestrators | workers | <role> | agent:<name>")
    return cleaned


def add_rule(
    actor: dict | None, text: str, reason: str, targets: list[str], mode: str,
    expires_at: str = "", *, project: str = "",
) -> dict:
    actor = _require_orchestrator(actor)
    text = (text or "").strip()
    if not text:
        raise RuleError(422, "rule text is required")
    if "</temporary-rules>" in text or "<temporary-rules>" in text:
        raise RuleError(422, "rule text must not contain the temporary-rules tag")
    reason = (reason or "").strip()
    if not reason:
        raise RuleError(422, "reason is required: why the rule exists and what caused it")
    if mode not in MODES:
        raise RuleError(422, f"mode must be {'|'.join(MODES)}")
    if mode == "permanent":
        if expires_at:
            raise RuleError(422, "a permanent rule has no expires_at")
        deadline = None
    else:
        if not expires_at:
            raise RuleError(422, f"expires_at is required for mode {mode}")
        deadline = _parse_utc(expires_at)
        if deadline <= _now():
            raise RuleError(422, "expires_at is already in the past")
    project = (project or actor.get("scope") or "").strip()
    _authorize_project(actor, project)
    rule = {
        "id": f"rule-{hashlib.sha1(f'{_now().isoformat()}{text}'.encode()).hexdigest()[:10]}",
        "text": text, "reason": reason, "project": project if project == GLOBAL else project.rstrip("/"),
        "targets": json.dumps(_check_targets(targets), ensure_ascii=False),
        "expires_at": deadline.isoformat() if deadline else None,
        "on_expire": "remove" if mode == "expires" else "notify",
        "author_session_id": actor["id"], "author_name": actor["name"],
        "created_at": _now().isoformat(), "removed_at": None, "notified_at": None,
    }
    with db._conn() as conn:
        _schema(conn)
        conn.execute(
            "INSERT INTO temp_rules(id,text,project,targets,expires_at,on_expire,author_session_id,"
            "author_name,created_at,removed_at,notified_at,reason) VALUES(:id,:text,:project,:targets,"
            ":expires_at,:on_expire,:author_session_id,:author_name,:created_at,:removed_at,"
            ":notified_at,:reason)", rule,
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
            mode = _mode(row)
            when = {"expires": f"expires {row['expires_at']}", "review": f"review due {row['expires_at']}",
                    "permanent": "permanent"}[mode]
            why = f" Reason: {row['reason']}." if row["reason"] else ""
            lines.append(
                f"- {row['text']}{why} [{when}; set by {row['author_name']} on {row['created_at'][:10]}]")
    if not lines:
        return ""
    return (
        "<temporary-rules>\nTemporary rules currently in force; a rule marked "
        "expires drops out of this prompt by itself; the others stay until their author changes them.\n" + "\n".join(lines) + "\n</temporary-rules>"
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


def _recipient(row: dict) -> tuple[dict | None, bool]:
    """The live author, else the live orchestrator of the rule's project (Orchestra's for "*")."""
    from app.notify import orchestrator_for_scope

    author = db.get_session(row["author_session_id"])
    if author and author.get("status") != "archived":
        return author, False
    scope = ORCHESTRA_SCOPE if row["project"] == GLOBAL else row["project"]
    return orchestrator_for_scope(scope), True


# Rules already warned about, so the 60 s sweep does not repeat the warning.
_warned_no_recipient: set[str] = set()


async def notify_due(session_manager) -> int:
    """Send each due notice once; the DB mark survives a restart. Returns notices sent.

    A notice nobody can receive is not marked as sent: it waits for the next sweep.
    """
    from app.events import MessageProvenance

    sent = 0
    for row in claim_due_notices():
        recipient, fallback = _recipient(row)
        if recipient is None:
            if row["id"] not in _warned_no_recipient:
                _warned_no_recipient.add(row["id"])
                logger.warning(
                    "temp rule %s: author %s is gone and project %s has no live orchestrator; "
                    "the review notice waits until one exists", row["id"], row["author_name"], row["project"])
            continue
        text = notice_text(row)
        if fallback:
            text = f"(Author {row['author_name']} is no longer active, so you receive this.) {text}"
        try:
            await session_manager.send(
                recipient["id"], text,
                provenance=MessageProvenance(
                    origin="platform", senders=("Orchestra",), subtype="temp_rule", ref=row["id"]),
            )
        except Exception as error:
            logger.warning("temp rule %s: notice failed, will retry: %s", row["id"], error)
            continue
        _warned_no_recipient.discard(row["id"])
        mark_notified(row["id"])
        sent += 1
    return sent
