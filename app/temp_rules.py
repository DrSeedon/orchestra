"""Временные правила агентам: файл в git проекта, блок в системном промпте, пока действуют.

Правило — это решение, которое должно гулять по git вместе с проектом (решение владельца
2026-10-17: «Всё в гите»), поэтому текст и метаданные лежат в `.orchestra/temp-rules.yaml`
основного checkout проекта; правила на все проекты — в таком же файле репозитория Orchestra.
Инструменты `temp_rule_*` меняют файл и коммитят ровно его. Промпт собирается из файла при
каждом вызове: ручная правка или `git pull` вступают в силу со следующего хода, истёкшее
правило пропадает само. В БД остаётся только изменяемое состояние напоминаний.

Режимы: `expires` — снимается само в срок; `review` — остаётся в силе, автору один раз
приходит «пора пересмотреть»; `permanent` — без даты.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app import db
from app.prompting import is_orchestrator_role

logger = logging.getLogger(__name__)

# Project that may set rules for every project at once.
ORCHESTRA_SCOPE = str(db._REPO_ROOT)
ORCHESTRA_ORCHESTRATOR = "Orchestra-orchestrator"
GLOBAL = "*"
THIS = "this"  # stored in the file instead of a machine-specific path
MODES = ("expires", "review", "permanent")
RULES_FILE = Path(".orchestra") / "temp-rules.yaml"
_BLOCK = re.compile(r"\n*(<temporary-rules>.*?</temporary-rules>)", re.DOTALL)
_FILE_HEADER = (
    "# Temporary agent rules, managed by the temp_rule_* tools; hand edits and git pulls are honoured.\n"
    "# An entry without a reason, or without a date in mode expires/review, is skipped with a warning.\n"
)
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_warned: set[tuple[str, str]] = set()


class RuleError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(value) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise RuleError(422, "expires_at must be an ISO UTC timestamp, e.g. 2026-10-20T07:00Z")
    if moment.tzinfo is None:
        raise RuleError(422, "expires_at must carry a timezone (use Z for UTC)")
    return moment.astimezone(timezone.utc)


def _norm(scope: str) -> str:
    return (scope or "").rstrip("/")


def _warn_once(path: Path, key: str, message: str) -> None:
    if (str(path), key) not in _warned:
        _warned.add((str(path), key))
        logger.warning("temporary rules %s: %s", path, message)


# ── file storage ──

def _path(scope: str) -> Path:
    return Path(scope) / RULES_FILE


def _validate(entry) -> str:
    """'' when the entry is usable, else why it is skipped."""
    if not isinstance(entry, dict):
        return "entry is not a mapping"
    for key in ("id", "text", "reason", "author"):
        if not str(entry.get(key) or "").strip():
            return f"missing {key}"
    targets = entry.get("targets")
    if not isinstance(targets, list) or not targets or not all(isinstance(t, str) and t.strip() for t in targets):
        return "targets must be a non-empty list"
    if entry.get("mode") not in MODES:
        return f"mode must be {'|'.join(MODES)}"
    if entry.get("project", THIS) not in (THIS, GLOBAL):
        return f"project must be {THIS} or {GLOBAL}"
    if entry["mode"] != "permanent":
        try:
            _parse_utc(entry.get("expires_at"))
        except RuleError as error:
            return f"mode {entry['mode']} needs a valid date: {error.detail}"
    return ""


def _read(scope: str, *, strict: bool = False) -> list[dict]:
    """Valid entries of the scope's file; broken ones are skipped with one warning each."""
    path = _path(scope)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return []
    except OSError as error:
        _warn_once(path, "unreadable", f"unreadable, ignored: {error}")
        return []
    try:
        data = yaml.safe_load(raw) or {}
        entries = data.get("rules") or []
        if not isinstance(entries, list):
            raise ValueError("`rules` must be a list")
    except (yaml.YAMLError, ValueError, AttributeError) as error:
        if strict:
            raise RuleError(409, f"{path} is not valid YAML with a rules list: {error}")
        _warn_once(path, "parse", f"not valid, all its rules ignored: {error}")
        return []
    good = []
    for entry in entries:
        problem = _validate(entry)
        if problem:
            name = entry.get("id", "?") if isinstance(entry, dict) else "?"
            _warn_once(path, f"{name}:{problem}", f"entry {name} skipped: {problem}")
            continue
        good.append({**entry, "project": entry.get("project", THIS), "id": str(entry["id"])})
    return good


def _dump(entries: list[dict]) -> str:
    plain = []
    for e in entries:
        item = {k: e[k] for k in ("id", "project", "mode", "expires_at", "targets", "author", "created_at", "text", "reason")
                if e.get(k) not in (None, "")}
        for key in ("expires_at", "created_at"):
            if isinstance(item.get(key), datetime):
                item[key] = item[key].isoformat()
        plain.append(item)
    return _FILE_HEADER + yaml.safe_dump(
        {"rules": plain}, sort_keys=False, allow_unicode=True, default_flow_style=False, width=100)


def _git(root: str, *args: str):
    from app.rules_link import _git as run

    return run(Path(root), *args)


def _is_repo(root: str) -> bool:
    return _git(root, "rev-parse", "--show-toplevel").returncode == 0


def _git_blocker(root: str) -> str:
    """Why a commit here is unsafe; '' = go ahead. A non-repository is not a blocker (file only)."""
    from app.rules_link import _IN_PROGRESS
    from app.workspace import resolve_base_branch

    if not _is_repo(root):
        return ""
    if _git(root, "rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return "repository has no commits"
    branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if not branch:
        return "HEAD is detached"
    try:
        mainline = resolve_base_branch(root)
    except ValueError as error:
        return f"mainline unknown: {error}"
    if branch != mainline:
        return f"checked-out branch is {branch}, not mainline {mainline}"
    for name in _IN_PROGRESS:
        marker = _git(root, "rev-parse", "--git-path", name).stdout.strip()
        if marker and (Path(root) / marker if not os.path.isabs(marker) else Path(marker)).exists():
            return f"a git operation is in progress ({name})"
    return ""


def _lock_for(scope: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(_norm(scope), threading.Lock())


def _write_and_commit(scope: str, entries: list[dict], message: str, *, strict: bool = True) -> None:
    """Replace the file and commit exactly it; on failure restore the original bytes.

    `strict=False` (migration only) keeps the written file when git refuses, so a rule that
    is already in force is never dropped just because a commit was impossible.
    """
    if not (Path(scope) / ".orchestra" / "layout.json").is_file():
        # Creating `.orchestra/` in a project without a layout would make its prompt assembly fail.
        raise RuleError(409, f"{scope} has no .orchestra/layout.json; temporary rules need an Orchestra project")
    blocker = _git_blocker(scope)
    if blocker:
        if strict:
            raise RuleError(409, f"cannot record the rule in git: {blocker}")
        logger.warning("temporary rules %s written without a commit: %s", scope, blocker)
    path = _path(scope)
    original = path.read_bytes() if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(entries))
    if blocker or not _is_repo(scope):
        return

    def rollback() -> None:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)
        _git(scope, "reset", "-q", "--", str(RULES_FILE))

    added = _git(scope, "add", "--", str(RULES_FILE))
    if added.returncode == 0:
        done = _git(scope, "commit", "-m", message, "--only", "--", str(RULES_FILE))
    if added.returncode != 0 or done.returncode != 0:
        detail = (added.stderr if added.returncode else done.stderr or done.stdout).strip()
        if not strict:
            logger.warning("temporary rules %s written without a commit: %s", scope, detail)
            return
        rollback()
        raise RuleError(409, f"git could not commit the rules file: {detail}")


def _mutate(scope: str, change, message_of) -> dict:
    """Read-modify-write-commit under one lock; `change(entries)` returns the touched entry."""
    scope = _norm(scope)
    with _lock_for(scope):
        entries = _read(scope, strict=True)
        touched = change(entries)
        _write_and_commit(scope, entries, message_of(touched))
    return touched


# ── authorization ──

def _is_orchestra_orchestrator(actor: dict) -> bool:
    return (
        actor.get("name") == ORCHESTRA_ORCHESTRATOR
        and _norm(actor.get("scope")) == _norm(ORCHESTRA_SCOPE)
    )


def _require_orchestrator(actor: dict | None) -> dict:
    if not actor or not (
        actor.get("is_orchestrator") or is_orchestrator_role(actor.get("role") or "")
    ):
        raise RuleError(403, "temporary rules can be managed by orchestrators only")
    return actor


def _authorize(actor: dict, entry_project: str, file_scope: str) -> None:
    """Own project only; every project (`*`) only for the Orchestra project orchestrator."""
    if entry_project == GLOBAL:
        if not _is_orchestra_orchestrator(actor):
            raise RuleError(403, "rules for all projects can be set only by the Orchestra project orchestrator")
    elif _norm(file_scope) != _norm(actor.get("scope")):
        raise RuleError(403, "an orchestrator can manage rules of its own project only")


def _mode(row: dict) -> str:
    return row["mode"]


def _view(row: dict, scope: str) -> dict:
    return {**row, "targets": list(row["targets"]), "expires_at": _iso(row.get("expires_at")),
            "created_at": _iso(row.get("created_at")), "author_name": row["author"],
            "project": GLOBAL if row["project"] == GLOBAL else _norm(scope)}


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _check_targets(targets: list[str]) -> list[str]:
    cleaned = [t.strip() for t in targets if isinstance(t, str) and t.strip()]
    if not cleaned:
        raise RuleError(422, "targets is required: all | orchestrators | workers | <role> | agent:<name>")
    return cleaned


def _check_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise RuleError(422, "rule text is required")
    if "</temporary-rules>" in text or "<temporary-rules>" in text:
        raise RuleError(422, "rule text must not contain the temporary-rules tag")
    return text


def _check_reason(reason: str) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise RuleError(422, "reason is required: why the rule exists and what caused it")
    return reason


def _check_deadline(mode: str, expires_at, *, future: bool = True) -> str | None:
    if mode not in MODES:
        raise RuleError(422, f"mode must be {'|'.join(MODES)}")
    if mode == "permanent":
        if expires_at:
            raise RuleError(422, "a permanent rule has no expires_at")
        return None
    else:
        if not expires_at:
            raise RuleError(422, f"expires_at is required for mode {mode}")
        deadline = _parse_utc(expires_at)
        if future and deadline <= _now():
            raise RuleError(422, "expires_at is already in the past")
        return deadline.isoformat()


def add_rule(
    actor: dict | None, text: str, reason: str, targets: list[str], mode: str,
    expires_at: str = "", *, project: str = "",
) -> dict:
    actor = _require_orchestrator(actor)
    text = _check_text(text)
    reason = _check_reason(reason)
    deadline = _check_deadline(mode, expires_at)
    project = (project or actor.get("scope") or "").strip()
    stored_project = GLOBAL if project == GLOBAL else THIS
    if project != GLOBAL and _norm(project) != _norm(actor.get("scope")):
        raise RuleError(403, "an orchestrator can manage rules of its own project only")
    _authorize(actor, stored_project, actor["scope"])
    file_scope = ORCHESTRA_SCOPE if project == GLOBAL else actor["scope"]
    created = _now()
    entry = {
        "id": f"rule-{hashlib.sha1(f'{created.isoformat()}{text}'.encode()).hexdigest()[:10]}",
        "project": stored_project, "mode": mode,
        "expires_at": deadline,
        "targets": _check_targets(targets), "author": actor["name"],
        "created_at": created.isoformat(), "text": text, "reason": reason,
    }
    _mutate(
        file_scope, lambda entries: entries.append(entry) or entry,
        lambda e: f"temp-rules: set {e['id']} ({mode}, {', '.join(e['targets'])}) — {reason[:100]}",
    )
    return _view(entry, file_scope)


def _is_active(row: dict, now: datetime) -> bool:
    return row["mode"] != "expires" or _parse_utc(row["expires_at"]) > now


def _file_scopes(scope: str) -> list[str]:
    scopes = [_norm(scope)]
    if _norm(ORCHESTRA_SCOPE) not in scopes:
        scopes.append(_norm(ORCHESTRA_SCOPE))
    return scopes


def _visible(scope: str) -> list[tuple[str, dict]]:
    """(file scope, entry) pairs that apply to a project, ordered by creation time then id."""
    pairs = []
    for file_scope in _file_scopes(scope):
        for entry in _read(file_scope):
            if (entry["project"] == THIS and file_scope == _norm(scope)) or (
                entry["project"] == GLOBAL and file_scope == _norm(ORCHESTRA_SCOPE)
            ):
                pairs.append((file_scope, entry))
            elif entry["project"] == GLOBAL:
                _warn_once(_path(file_scope), f"{entry['id']}:foreign-global",
                           f"entry {entry['id']} is for all projects but this is not the Orchestra repository; ignored")
    return sorted(pairs, key=lambda p: (str(_iso(p[1].get("created_at"))), p[1]["id"]))


def list_rules(actor: dict | None, *, include_inactive: bool = False) -> list[dict]:
    actor = _require_orchestrator(actor)
    now = _now()
    return [
        {**_view(e, fs), "active": _is_active(e, now)} for fs, e in _visible(actor["scope"])
        if include_inactive or _is_active(e, now)
    ]


def _locate(actor: dict, rule_id: str) -> tuple[str, dict]:
    for file_scope, entry in _visible(actor["scope"]):
        if entry["id"] == rule_id:
            return file_scope, entry
    raise RuleError(404, f"no such rule: {rule_id}")


def remove_rule(actor: dict | None, rule_id: str) -> dict:
    actor = _require_orchestrator(actor)
    file_scope, found = _locate(actor, rule_id)
    _authorize(actor, found["project"], file_scope)

    def change(entries):
        for i, e in enumerate(entries):
            if str(e.get("id")) == rule_id:
                return entries.pop(i)
        raise RuleError(404, f"no such rule: {rule_id}")

    _mutate(file_scope, change, lambda e: f"temp-rules: remove {rule_id}")
    return {"ok": True, "id": rule_id}


def update_rule(
    actor: dict | None, rule_id: str, *, expires_at: str = "", keep: bool = False,
    text: str | None = None, reason: str | None = None,
    targets: list[str] | None = None, mode: str | None = None,
) -> dict:
    """Edit supplied fields in place; a new date re-arms the one-time notice."""
    actor = _require_orchestrator(actor)
    if not (expires_at or keep or any(v is not None for v in (text, reason, targets, mode))):
        raise RuleError(422, "pass a field to update, expires_at (extend), or keep=true")
    if keep and mode not in (None, "permanent"):
        raise RuleError(422, "keep=true requires mode permanent")
    file_scope, found = _locate(actor, rule_id)
    _authorize(actor, found["project"], file_scope)

    def change(entries):
        for e in entries:
            if str(e.get("id")) == rule_id:
                _authorize(actor, e["project"], file_scope)
                new_mode = "permanent" if keep else mode if mode is not None else e["mode"]
                # An explicit transition to permanent clears the inherited date,
                # but a caller-supplied date is always forbidden in that mode.
                date = expires_at or (e.get("expires_at") if new_mode != "permanent" else None)
                updated = {
                    "text": _check_text(e["text"] if text is None else text),
                    "reason": _check_reason(e["reason"] if reason is None else reason),
                    "targets": _check_targets(e["targets"] if targets is None else targets),
                    "mode": new_mode,
                }
                deadline = _check_deadline(new_mode, date, future=bool(expires_at) or mode is not None)
                e.update(updated)
                if deadline is None:
                    e.pop("expires_at", None)
                else:
                    e["expires_at"] = deadline
                return e
        raise RuleError(404, f"no such rule: {rule_id}")

    entry = _mutate(
        file_scope, change,
        lambda e: f"V-1037: temp-rules: update {rule_id} ({e['mode']})",
    )
    return _view(entry, file_scope)


def _applies(row: dict, *, role: str, is_orch: bool, name: str) -> bool:
    for target in row["targets"]:
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
        ensure_migrated()
        visible = _visible(scope)
    except Exception as error:
        # Prompt assembly is on every turn's hot path; a broken rules store must not stop turns.
        logger.warning("temporary rules unreadable, prompt built without them: %s", error)
        return ""
    now = _now()
    lines = []
    for _, row in visible:
        if _is_active(row, now) and _applies(row, role=role, is_orch=is_orch, name=name):
            when = {"expires": "expires", "review": "review due", "permanent": "permanent"}[row["mode"]]
            if row["mode"] != "permanent":
                when += f" {_iso(row['expires_at'])}"
            lines.append(
                f"- {row['text'].strip()} Reason: {row['reason'].strip()}. "
                f"[{when}; set by {row['author']} on {str(_iso(row['created_at']))[:10]}]")
    if not lines:
        return ""
    return (
        "<temporary-rules>\nTemporary rules currently in force; a rule marked "
        "expires drops out of this prompt by itself; the others stay until their author changes them.\n"
        + "\n".join(lines) + "\n</temporary-rules>"
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


def fingerprint(**agent) -> str:
    return block_fingerprint(active_block(**agent))


def block_fingerprint(prompt: str) -> str:
    found = _BLOCK.search(prompt)
    return hashlib.md5(found.group(1).encode()).hexdigest()[:8] if found else ""


# ── reminder state (the only thing kept in the database) ──

def _state_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS temp_rule_notices (
            scope TEXT NOT NULL, rule_id TEXT NOT NULL, due_at TEXT NOT NULL, notified_at TEXT NOT NULL,
            PRIMARY KEY (scope, rule_id, due_at))"""
    )


def _project_scopes() -> list[str]:
    scopes = {_norm(r.get("scope")) for r in db.get_all_sessions()} | {_norm(ORCHESTRA_SCOPE)}
    return sorted(s for s in scopes if s)


def claim_due_notices() -> list[dict]:
    """Review rules past their date whose current date has not been announced yet."""
    now = _now()
    due = []
    with db._conn() as conn:
        _state_schema(conn)
        for scope in _project_scopes():
            for entry in _read(scope):
                owned = (entry["project"] == THIS) or scope == _norm(ORCHESTRA_SCOPE)
                if entry["mode"] != "review" or not owned or _parse_utc(entry["expires_at"]) > now:
                    continue
                due_at = _parse_utc(entry["expires_at"]).isoformat()
                seen = conn.execute(
                    "SELECT 1 FROM temp_rule_notices WHERE scope=? AND rule_id=? AND due_at=?",
                    (scope, entry["id"], due_at)).fetchone()
                if not seen:
                    due.append({**_view(entry, scope), "scope": scope, "due_at": due_at})
    return due


def mark_notified(scope: str, rule_id: str, due_at: str) -> bool:
    with db._conn() as conn:
        _state_schema(conn)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO temp_rule_notices VALUES(?,?,?,?)",
            (_norm(scope), rule_id, due_at, _now().isoformat()))
        return cursor.rowcount == 1


def notice_text(row: dict) -> str:
    return (
        f"Temporary rule {row['id']} reached its review date ({row['expires_at']}) and is STILL IN FORCE "
        f"for project {row['project']}, targets {row['targets']}: «{row['text']}». "
        f"Decide: extend (temp_rule_update with expires_at), keep without a deadline "
        f"(temp_rule_update keep=true) or remove (temp_rule_remove). This notice is sent once."
    )


def _recipient(row: dict) -> tuple[dict | None, bool]:
    """The live author, else the live orchestrator of the rule's project (Orchestra's for "*")."""
    from app.notify import orchestrator_for_scope

    for session in db.get_all_sessions():
        if (session.get("name") == row["author"] and _norm(session.get("scope")) == row["scope"]
                and session.get("status") != "archived"):
            return session, False
    return orchestrator_for_scope(row["scope"]), True


# Rules already warned about, so the 60 s sweep does not repeat the warning.
_warned_no_recipient: set[tuple[str, str]] = set()


async def notify_due(session_manager) -> int:
    """Send each due notice once; the DB mark survives a restart. Returns notices sent.

    A notice nobody can receive is not marked as sent: it waits for the next sweep.
    """
    from app.events import MessageProvenance

    sent = 0
    for row in claim_due_notices():
        key = (row["scope"], row["id"])
        recipient, fallback = _recipient(row)
        if recipient is None:
            if key not in _warned_no_recipient:
                _warned_no_recipient.add(key)
                logger.warning(
                    "temp rule %s: author %s is gone and project %s has no live orchestrator; "
                    "the review notice waits until one exists", row["id"], row["author"], row["scope"])
            continue
        text = notice_text(row)
        if fallback:
            text = f"(Author {row['author']} is no longer active, so you receive this.) {text}"
        try:
            await session_manager.send(
                recipient["id"], text,
                provenance=MessageProvenance(
                    origin="platform", senders=("Orchestra",), subtype="temp_rule", ref=row["id"]),
            )
        except Exception as error:
            logger.warning("temp rule %s: notice failed, will retry: %s", row["id"], error)
            continue
        _warned_no_recipient.discard(key)
        mark_notified(row["scope"], row["id"], row["due_at"])
        sent += 1
    return sent


# ── one-time move of the former database table into the files ──

_migration_lock = threading.Lock()
_migrated = False


def ensure_migrated() -> None:
    """Move rules from the legacy `temp_rules` table into the files, once per process.

    Runs from the first prompt assembly, so a rule in force keeps acting without a gap: the
    file is written before the table is renamed, and the same call then reads the file.
    """
    global _migrated
    if _migrated:
        return
    with _migration_lock:
        if _migrated:
            return
        try:
            _migrate_table()
        except Exception as error:
            logger.error("temporary rules: migration from the database table failed: %s", error)
        _migrated = True


def _migrate_table() -> None:
    with db._conn() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='temp_rules'").fetchone():
            return
        rows = [dict(r) for r in conn.execute("SELECT * FROM temp_rules WHERE removed_at IS NULL")]
    now = _now()
    by_scope: dict[str, list[dict]] = {}
    seen_notices = []
    for row in rows:
        mode = ("permanent" if not row["expires_at"]
                else "review" if row["on_expire"] == "notify" else "expires")
        if mode == "expires" and _parse_utc(row["expires_at"]) <= now:
            continue
        if row["project"] == GLOBAL:
            scope, project = _norm(ORCHESTRA_SCOPE), GLOBAL
        elif Path(row["project"]).is_dir():
            scope, project = _norm(row["project"]), THIS
        else:
            logger.warning("temporary rules: rule %s of missing project %s not migrated", row["id"], row["project"])
            continue
        by_scope.setdefault(scope, []).append({
            "id": row["id"], "project": project, "mode": mode,
            "expires_at": _parse_utc(row["expires_at"]).isoformat() if row["expires_at"] else None,
            "targets": json.loads(row["targets"]), "author": row["author_name"],
            "created_at": row["created_at"], "text": row["text"], "reason": row["reason"] or "(migrated; no reason recorded)",
        })
        if mode == "review" and row["notified_at"]:
            seen_notices.append((scope, row["id"], _parse_utc(row["expires_at"]).isoformat(), row["notified_at"]))
    for scope, fresh in by_scope.items():
        with _lock_for(scope):
            entries = _read(scope)
            known = {e["id"] for e in entries}
            added = [e for e in fresh if e["id"] not in known]
            if added:
                _write_and_commit(
                    scope, entries + added,
                    "temp-rules: move rules from the database into git (" + ", ".join(e["id"] for e in added) + ")",
                    strict=False)
    with db._conn() as conn:
        _state_schema(conn)
        conn.executemany("INSERT OR IGNORE INTO temp_rule_notices VALUES(?,?,?,?)", seen_notices)
        conn.execute("ALTER TABLE temp_rules RENAME TO temp_rules_moved_to_git")
