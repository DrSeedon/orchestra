"""Snapshot identity and policy reference for merge review coverage (#462)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.db import REVIEW_AUTHOR_OUTCOMES


SNAPSHOT_VERSION = b"review-coverage-v1\0"
# Дайджест ПРЕДМЕТА ревью: только сырой продовый дифф, без хеша цели. `--raw --full-index`
# несёт статус, режим, путь и blob-SHA обеих сторон, поэтому байт-в-байт равные `raw`
# означают тождественный продовый дифф — а хеш цели в `SNAPSHOT_VERSION`-дайджесте делал
# состоявшееся ревью недействительным от ЛЮБОГО постороннего коммита в main (04.09, #474:
# `2268e0fe...2735fcf1` и `525684a4...598a5848` дали одинаковые 167 байт и разные дайджесты).
# Своя версия-префикс: два дайджеста считаются от одного `raw` и не должны совпадать.
DIFF_VERSION = b"review-coverage-diff-v1\0"
ACTIVATION_MARKER = "review-coverage-v1"
PRODUCTION_PREFIXES = ("app/", "scripts/")
MACHINE_UNAVAILABLE_CODES = frozenset({"weekly_quota_blocked", "codex_binary_missing"})
POLICY_PATH = (
    Path(__file__).resolve().parent.parent
    / ".orchestra/pipelines/default/prompts/skills/codex-debate.md"
)


def _git_bytes(worktree: str, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args], cwd=worktree, capture_output=True, check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip()
        raise ValueError(detail or f"git {' '.join(args)} exited {proc.returncode}")
    return proc.stdout


def _git_text(worktree: str, *args: str) -> str:
    return _git_bytes(worktree, *args).decode("utf-8", "replace").strip()


def production_paths(changed_paths: list[str]) -> list[str]:
    return sorted({
        path.replace("\\", "/").lstrip("./")
        for path in changed_paths
        if path.replace("\\", "/").lstrip("./").startswith(PRODUCTION_PREFIXES)
    })


def production_snapshot(
    worktree: str, *, target_sha: str, worker_head: str,
) -> dict[str, object]:
    raw = _git_bytes(
        worktree,
        "diff", "--raw", "--full-index", "-z",
        f"{target_sha}...{worker_head}", "--", "app", "scripts",
    )
    named = _git_bytes(
        worktree,
        "diff", "--name-only", "-z",
        f"{target_sha}...{worker_head}", "--", "app", "scripts",
    )
    # Нормализация путей — ОДИН владелец, `production_paths`. Раньше она была только на стороне
    # допуска (`\\`→`/`, срезание `./`), а снимок писал имя от git как есть; после привязки к
    # `production_paths_json` расхождение стало бы ложным БЛОКОМ мержа на пути с обратным слэшем
    # в имени (#474, раунд 2). Фильтр по префиксу здесь холостой: git уже ограничен `app scripts`.
    paths = production_paths(
        [path for path in named.decode("utf-8", "surrogateescape").split("\0") if path]
    )
    digest = hashlib.sha256(
        SNAPSHOT_VERSION + target_sha.encode() + b"\0" + raw
    ).hexdigest()
    return {
        "target_sha": target_sha,
        "worker_head": worker_head,
        "production_snapshot_sha256": digest,
        # Пустой `raw` — это «продового диффа нет вовсе», и привязывать к нему нечего:
        # дайджест был бы одной и той же константой для любой пары ссылок. Такое состояние
        # получает пустую строку и уходит на привязку к цели, а не на общий дайджест.
        "production_diff_sha256": (
            hashlib.sha256(DIFF_VERSION + raw).hexdigest() if raw else ""
        ),
        "production_paths": paths,
        "production_paths_json": json.dumps(paths, ensure_ascii=False, separators=(",", ":")),
    }


def resolve_implementation_subject(worktree: str, target_ref: str) -> dict[str, object]:
    dirty = _git_text(worktree, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError("implementation review requires a clean committed worktree")
    target_sha = _git_text(worktree, "rev-parse", "--verify", f"{target_ref}^{{commit}}")
    worker_head = _git_text(worktree, "rev-parse", "--verify", "HEAD^{commit}")
    return production_snapshot(
        worktree, target_sha=target_sha, worker_head=worker_head,
    )


def current_policy_ref() -> str:
    return "codex-debate@sha256:" + hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def policy_active() -> bool:
    try:
        return ACTIVATION_MARKER in POLICY_PATH.read_text(encoding="utf-8")
    except OSError:
        return False


def coverage_decision(
    *, scope: str, session_id: str, task_id: str, target_sha: str,
    worker_head: str, production_paths: list[str],
    production_snapshot_sha256: str, active: bool,
    production_diff_sha256: str = "",
    before: str | None = None,
) -> dict[str, object]:
    base = {
        "required": bool(production_paths),
        "status": "not_required" if not production_paths else "blocked",
        "reason": "" if not production_paths else "review_receipt_missing",
        "production_paths": list(production_paths),
        "target_sha": target_sha,
        "worker_head": worker_head,
        "production_snapshot_sha256": production_snapshot_sha256,
        "production_diff_sha256": production_diff_sha256,
        "receipt_id": "",
        "coverage_outcome": "unknown",
    }
    if not production_paths:
        return base
    if not active:
        return {**base, "required": False, "status": "not_active", "reason": "policy_not_active"}
    boundary = before or datetime.now(timezone.utc).isoformat()
    from app.db import _conn

    # Список продовых путей — ОТДЕЛЬНОЕ условие поверх обеих дайджест-веток, а не деталь одной
    # из них. Оба дайджеста считаются от `git diff`, который untracked-файлов не видит вовсе, а
    # `changed_paths` их считает, — значит добавленный после ревью untracked `app/new.py`
    # оставляет ОБА дайджеста прежними и проходил бы по target-привязанной ветке (нашла Luna,
    # раунд 1, #474). Сравнение путей закрывает это и на старых квитанциях, ничего в них не
    # переписывая: `production_paths_json` там уже лежит с #462.
    paths_json = json.dumps(
        list(production_paths), ensure_ascii=False, separators=(",", ":"),
    )
    # Две дайджест-ветки предъявляют ОДНУ И ТУ ЖЕ гарантию — «продовый дифф не менялся» — но
    # берут её из разных полей. Вторая (по `production_diff_sha256`) снимает зависимость от хеша
    # цели, первая остаётся ради квитанций, выписанных до этой колонки: их не переписывают
    # задним числом, и без неё они разом перестали бы засчитываться. Пустой
    # `production_diff_sha256` в старой квитанции НИЧЕГО не покрывает и отсекается явным `<>''`.
    with _conn() as connection:
        rows = connection.execute(
            """SELECT * FROM review_receipts
                 WHERE scope=? AND session_id=? AND task_id=?
                   AND production_paths_json=?
                   AND (
                     (target_sha=? AND production_snapshot_sha256=?)
                     OR (production_diff_sha256<>'' AND production_diff_sha256=?)
                   )
                   AND requested_at<=? AND completed_at IS NOT NULL AND completed_at<=?
                 ORDER BY completed_at DESC, requested_at DESC""",
            (
                scope, session_id, task_id, paths_json, target_sha,
                production_snapshot_sha256, production_diff_sha256,
                boundary, boundary,
            ),
        ).fetchall()
    policy_ref = current_policy_ref()
    for raw in rows:
        receipt = dict(raw)
        outcome = str(receipt.get("coverage_outcome") or "unknown")
        reviewed = (
            outcome == "reviewed"
            and receipt.get("subject_kind") == "implementation"
            and receipt.get("status") == "completed"
            and receipt.get("return_code") == 0
            and receipt.get("artifact_exists") == 1
            and int(receipt.get("artifact_bytes") or 0) > 0
            and receipt.get("jsonl_response_present") == 1
        )
        skipped = (
            outcome == "skipped"
            and receipt.get("subject_kind") == "implementation"
            and receipt.get("status") == "completed"
            and receipt.get("policy_ref") == policy_ref
        )
        unavailable = (
            outcome == "unavailable"
            and receipt.get("subject_kind") == "implementation"
            and receipt.get("status") == "failed"
            and receipt.get("return_code") is None
            and receipt.get("failure_code") in MACHINE_UNAVAILABLE_CODES
            and receipt.get("policy_ref") == policy_ref
        )
        author_outcome = str(receipt.get("author_outcome") or "unknown")
        outcome_evidence_ref = str(receipt.get("outcome_evidence_ref") or "")
        if reviewed and author_outcome not in REVIEW_AUTHOR_OUTCOMES:
            return {
                **base,
                "status": "blocked",
                "reason": (
                    "author_outcome_missing"
                    if author_outcome == "unknown"
                    else "author_outcome_invalid"
                ),
                "receipt_id": str(receipt["receipt_id"]),
                "coverage_outcome": outcome,
                "author_outcome": author_outcome,
                "outcome_evidence_ref": outcome_evidence_ref,
            }
        if reviewed or skipped or unavailable:
            return {
                **base,
                "status": "satisfied",
                "reason": "",
                "receipt_id": str(receipt["receipt_id"]),
                "coverage_outcome": outcome,
                "author_outcome": author_outcome,
                "outcome_evidence_ref": outcome_evidence_ref,
            }
    return base
