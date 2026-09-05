"""Snapshot identity and policy reference for merge review coverage (#462)."""

from __future__ import annotations

import hashlib
import json
import re
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
# Аттестация продолжает ревью, которое автор ПРИНЯЛ. `disputed` означает «я с находками не
# согласен» — дельта после такого исхода не может быть «починкой принятых находок» и уходит
# на новый раунд, а не на подпись автора.
ATTESTABLE_AUTHOR_OUTCOMES = frozenset({"accepted", "partial"})
ATTESTATION_FILENAME = "review-attestation.json"
# Conventional Comments из `codex-debate.md`: `<prefix>: file:line — проблема`. Ревьюер часто
# обрамляет якорь бэктиками и ставит диапазон строк, поэтому и то и другое разрешено явно.
FINDING_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?[`*_]*\s*"
    r"(?:blocking|suggestion|question|thought|nit)\s*:\s*"
    r"([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+):(\d+(?:-\d+)?)",
    re.IGNORECASE | re.MULTILINE,
)
FINDING_HEADING_RE = re.compile(
    r"^\s*###\s*(?:blocking|suggestion|question|thought|nit)\s*:",
    re.IGNORECASE,
)
FINDING_LOCATION_RE = re.compile(
    r"(?P<path>(?:/[A-Za-z0-9_.-]+)+/[A-Za-z0-9_.-]+|[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)"
    r":(?P<line>\d+(?:-\d+)?)"
)
FINDING_LINK_RE = re.compile(r"\]\((?P<target>[^)\s]+)\)")
FINDING_CONTINUATION_RE = re.compile(
    r"\band\s+`?:(?P<line>\d+(?:-\d+)?)`?(?=\s*(?:\||$))"
)
# Путь находки принимается только в точном репозиторном написании: без обратных слэшей, без
# ведущей точки, без `.`/`..` в сегментах. Всё остальное — не путь, а способ его подделать.
FINDING_PATH_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
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


def _raw_path_heads(raw: bytes) -> dict[str, str]:
    """Post-image `mode:object-id` per production path, from the same `--raw -z` bytes.

    The mode is part of the identity, not decoration: `chmod +x` over a reviewed file gives
    `:100644 100755 4e5de3a4… 4e5de3a4… M`, and replacing a file with a symlink to the same
    bytes gives `:100644 120000 <sha> <sha> T` — both keep the blob and change what the file
    IS. A map of bare object ids admitted them (Luna, раунд 1 #509).

    The whole-diff digests answer «дельта не менялась»; they cannot answer «этот файл
    кончился тем же», which is what survives a target that absorbed part of the work.
    Anything this parser does not understand is simply absent from the map, and an absent
    path refuses the subset branch — the unparsed case fails closed (#509).
    """
    fields = raw.decode("utf-8", "surrogateescape").split("\0")
    heads: dict[str, str] = {}
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if not record.startswith(":"):
            continue
        parts = record[1:].split(" ")
        if len(parts) < 5:
            continue
        # A rename/copy record carries two names and the destination is the second one.
        names = 2 if parts[4][:1] in {"R", "C"} else 1
        if index + names > len(fields):
            break
        normalized = production_paths([fields[index + names - 1]])
        index += names
        if normalized:
            heads[normalized[0]] = f"{parts[1]}:{parts[3]}"
    return heads


def reviewed_delta_covers(
    paths: list[str], current_heads: dict[str, str], reviewed_heads: dict[str, str],
) -> bool:
    """Is every currently changed production file byte-identical to the reviewed one?

    True means the delta shrank into what the reviewer already read: no path he never saw,
    and every surviving path ends at the same blob. It deliberately does NOT claim the
    previous state matched — the target may have absorbed part of the work, which is the
    whole point.

    `paths` is the authoritative current list and comes from `changed_paths`, which counts
    untracked files; `current_heads` comes from `git diff`, which does not see them at all.
    Iterating over `paths` is what makes an untracked `app/new.py` refuse: it has no head on
    either side, and a missing head is never equal to a reviewed one (#474 via #509).
    """
    if not paths or not reviewed_heads:
        return False
    return all(
        current_heads.get(path) is not None
        and reviewed_heads.get(path) == current_heads.get(path)
        for path in paths
    )


def production_snapshot(
    worktree: str, *, target_sha: str, worker_head: str,
) -> dict[str, object]:
    raw = _git_bytes(
        worktree,
        # `--no-abbrev` обязателен: `--full-index` разворачивает object id только в ПАТЧЕ, а в
        # `--raw` оставляет 7 символов (проверено `git 2.53.0`). На укороченном id личность
        # предмета держится на 28 битах, то есть подбирается перебором (Sol, раунд 2).
        "diff", "--raw", "--full-index", "--no-abbrev", "-z",
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
    path_heads = _raw_path_heads(raw)
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
        "production_path_heads": path_heads,
        "production_path_heads_json": json.dumps(
            path_heads, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ) if path_heads else "",
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


def attestation_path(worktree: str, task_id: str) -> Path:
    """Аттестация живёт в каталоге задачи автора и уезжает в main вместе с его работой."""
    return Path(worktree) / ".orchestra" / "tasks" / str(task_id) / ATTESTATION_FILENAME


def review_findings(artifact_text: str, *, worktree: str | None = None) -> list[str]:
    """Якоря `file:line` из ПОСЛЕДНЕГО раунда — ровно то, на что ревьюер смотрел последним."""
    last_round = re.split(r"(?im)^##\s+Round\b", artifact_text)[-1]
    anchors = set()

    def add(path: str, line: str) -> None:
        relative = _review_finding_path(path, worktree=worktree)
        if relative is not None:
            anchors.add(f"{relative}:{line}")

    for match in FINDING_RE.finditer(last_round):
        # Keep the legacy raw anchor here: `_finding_paths` rejects malformed spellings
        # literally, and the attestation then reports the delta as outside the finding.
        anchors.add(f"{match.group(1)}:{match.group(2)}")

    finding_heading = False
    for line in last_round.splitlines():
        if FINDING_HEADING_RE.match(line):
            finding_heading = True
            continue
        if re.match(r"^\s*#{2,3}\s+", line):
            finding_heading = False
            continue
        if not finding_heading or not re.match(r"^\s*\*\*File:\*\*", line):
            continue
        links = list(FINDING_LINK_RE.finditer(line))
        locations = []
        if links:
            for link in links:
                location = FINDING_LOCATION_RE.fullmatch(link.group("target"))
                if location is not None:
                    locations.append(location)
        else:
            locations = list(FINDING_LOCATION_RE.finditer(line))
        for location in locations:
            add(location.group("path"), location.group("line"))
        if locations:
            path = locations[-1].group("path")
            tail_start = links[-1].end() if links else locations[-1].end()
            for continuation in FINDING_CONTINUATION_RE.finditer(line[tail_start:]):
                add(path, continuation.group("line"))
    return sorted(anchors)


def _review_finding_path(path: str, *, worktree: str | None = None) -> str | None:
    """Reduce a review link to a strict repo-relative production path."""
    if "\\" in path:
        return None
    segments = path.split("/")
    if {".", ".."} & set(segments):
        return None
    if path.startswith("/"):
        if worktree is not None:
            try:
                relative = Path(path).relative_to(Path(worktree).resolve()).as_posix()
            except ValueError:
                return None
        else:
            path_segments = path.split("/")
            try:
                worktrees_index = path_segments.index("worktrees")
            except ValueError:
                return None
            relative = next(
                (
                    "/".join(path_segments[index:])
                    for index, segment in enumerate(path_segments)
                    if index > worktrees_index + 1
                    and f"{segment}/" in PRODUCTION_PREFIXES
                ),
                "",
            )
    else:
        relative = path
    if not FINDING_PATH_RE.fullmatch(relative) or not relative.startswith(PRODUCTION_PREFIXES):
        return None
    return relative


def _finding_paths(anchors) -> set[str]:
    """Продовые пути из якорей находок — БЕЗ нормализации, только точное написание.

    `production_paths()` нормализует (`\\`→`/`, срезание ведущих `./`), и на путях ИЗ GIT это
    правильно. Здесь источник другой — текст ревьюера, а его содержимое автор выбирает
    формулировкой запроса; нормализация превращала бы `../app/admin.py` и `.app/admin.py` в
    настоящий продовый путь, которого ревьюер не называл (Sol, раунд 1). Поэтому нечистое
    написание отбрасывается, а не чинится.
    """
    paths = set()
    for anchor in anchors:
        path = str(anchor).rsplit(":", 1)[0]
        segments = path.split("/")
        if not FINDING_PATH_RE.match(path) or {".", ".."} & set(segments):
            continue
        if path.startswith(PRODUCTION_PREFIXES):
            paths.add(path)
    return paths


def _production_diff_entries(worktree: str, target_sha: str, head: str) -> dict[str, str]:
    """Продовый дифф снимка как `путь → запись --raw` (статус, режимы, blob-SHA обеих сторон)."""
    raw = _git_bytes(
        worktree, "diff", "--raw", "--full-index", "--no-abbrev", "-z",
        f"{target_sha}...{head}", "--", "app", "scripts",
    ).decode("utf-8", "surrogateescape")
    fields = raw.split("\0")
    entries: dict[str, str] = {}
    index = 0
    while index < len(fields):
        meta = fields[index]
        if not meta.startswith(":"):
            index += 1
            continue
        status = meta.rsplit(" ", 1)[-1]
        # Переименование и копирование несут ДВА пути: изменились оба конца.
        count = 2 if status[:1] in {"R", "C"} else 1
        paths = [item for item in fields[index + 1:index + 1 + count] if item]
        record = "\0".join([meta, *paths])
        for path in paths:
            entries[path] = record
        index += 1 + count
    return entries


def _reviewed_receipt(receipt: dict) -> bool:
    return (
        str(receipt.get("coverage_outcome") or "") == "reviewed"
        and receipt.get("subject_kind") == "implementation"
        and receipt.get("status") == "completed"
        and receipt.get("return_code") == 0
        and receipt.get("artifact_exists") == 1
        and int(receipt.get("artifact_bytes") or 0) > 0
        and receipt.get("jsonl_response_present") == 1
        # Вердикт вычитан из артефакта сервером при закрытии квитанции. Гейт проверяет его сам
        # и не опирается на то, что финализатор всегда требовал секцию `## Verdict`: пересказ
        # автора вердиктом не является, а «ревью прошло без вердикта» — не ревью.
        and receipt.get("verdict_present") == 1
    )


def _attestation_failure(reason: str, detail: str = "") -> dict[str, object]:
    return {
        "ok": False, "reason": reason, "detail": detail,
        "closed_findings": [], "delta_paths": [],
    }


def verify_delta_attestation(
    *, worktree: str, task_id: str, receipt: dict, target_sha: str, worker_head: str,
    production_diff_sha256: str,
) -> dict[str, object]:
    """Машинно сверить авторскую аттестацию постревьюной дельты. Fail-closed на всём.

    Потолок раундов заставляет остановиться, поэтому починку находок ПОСЛЕДНЕГО раунда
    ревьюер не видит по построению. Подписывает её автор — но подпись ничего не стоит, пока
    её содержимое не сверено с артефактом и с git: дельта обязана лежать внутри файлов,
    названных находками того раунда, а сам артефакт — совпадать по хешу с квитанцией.
    """
    fail = _attestation_failure
    path = attestation_path(worktree, task_id)
    # «Файла нет» и «файл есть, но испорчен» чинятся РАЗНЫМ, поэтому и называются по-разному:
    # первое означает, что автор подписи не заявлял (причина остаётся прежней, «ревью на этот
    # снимок нет»), второе — что заявленную подпись нельзя прочитать, и чинить надо её, а не
    # запускать ревью заново (Sol, раунд 2).
    try:
        attestation = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail("attestation_missing", str(path))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return fail("attestation_invalid", f"{path}: {type(error).__name__}")
    if not isinstance(attestation, dict):
        return fail("attestation_invalid", f"{path}: not a JSON object")
    if str(attestation.get("receipt_id") or "") != str(receipt.get("receipt_id") or ""):
        return fail("attestation_receipt_mismatch", str(attestation.get("receipt_id") or ""))
    reviewed_head = str(attestation.get("reviewed_worker_head") or "")
    if reviewed_head != str(receipt.get("worker_head") or ""):
        return fail("attestation_head_mismatch", reviewed_head)
    if str(receipt.get("author_outcome") or "unknown") not in ATTESTABLE_AUTHOR_OUTCOMES:
        return fail(
            "attestation_outcome_not_attestable",
            str(receipt.get("author_outcome") or "unknown"),
        )
    # Аттестация подписывает ОДНУ дельту. Без привязки к её диффу подпись, выданная на первую
    # правку, молча покрывала бы каждую следующую.
    if str(attestation.get("production_diff_sha256") or "") != production_diff_sha256:
        return fail(
            "attestation_diff_mismatch",
            str(attestation.get("production_diff_sha256") or ""),
        )
    artifact = Path(str(receipt.get("artifact_path") or ""))
    try:
        artifact_bytes = artifact.read_bytes()
    except OSError as error:
        return fail("attestation_artifact_unreadable", f"{artifact}: {type(error).__name__}")
    artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
    # Байты артефакта здесь ВХОДЯТ в решение (из них берутся находки), поэтому именно здесь
    # они и пиннятся хешем. На обычном пути ревью артефакт в решение не входит, и пиннить его
    # там значило бы ломать мерж за законную дописку журнала в тот же файл.
    if artifact_sha256 != str(receipt.get("artifact_sha256") or ""):
        return fail("attestation_artifact_modified", artifact_sha256)
    if artifact_sha256 != str(attestation.get("artifact_sha256") or ""):
        return fail("attestation_artifact_unread", str(attestation.get("artifact_sha256") or ""))
    findings = review_findings(artifact_bytes.decode("utf-8", "replace"), worktree=worktree)
    closed = attestation.get("closed_findings")
    if not isinstance(closed, list) or not closed:
        return fail("attestation_findings_empty")
    unknown = sorted({str(item) for item in closed} - set(findings))
    if unknown:
        return fail("attestation_findings_unknown", ", ".join(unknown))
    # Дельта считается сравнением ДВУХ снимков ревью, а не диффом двух рабочих деревьев.
    # `reviewed_head..worker_head` видит только то, что автор переписал у себя, и слеп к
    # изменению ПРЕДМЕТА через движение цели: смерджив свежий main и разрешив чужой продовый
    # файл обратно в старое содержимое, автор возвращал в продовый дифф правку, которой
    # ревьюер не видел, а двухточечный дифф этого не показывал вовсе (Sol, раунд 1).
    try:
        reviewed_entries = _production_diff_entries(
            worktree, str(receipt.get("target_sha") or ""), reviewed_head,
        )
        current_entries = _production_diff_entries(worktree, target_sha, worker_head)
    except (ValueError, OSError) as error:
        return fail("attestation_delta_unresolved", str(error))
    delta_paths = sorted(
        path
        for path in set(reviewed_entries) | set(current_entries)
        if reviewed_entries.get(path) != current_entries.get(path)
    )
    # Разрешают только ЗАКРЫТЫЕ находки: иначе одна настоящая закрытая находка открывала бы
    # правку в каждом файле, упомянутом за раунд.
    allowed = _finding_paths(str(item) for item in closed)
    outside = sorted(set(delta_paths) - allowed)
    if outside:
        return fail("attestation_delta_outside_findings", ", ".join(outside))
    return {
        "ok": True, "reason": "", "detail": "",
        "closed_findings": [str(item) for item in closed],
        "delta_paths": delta_paths,
    }


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
    production_path_heads: dict[str, str] | None = None,
    before: str | None = None,
    worktree: str = "",
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
        "verdict_value": "",
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
    # Третья ветка. Обе дайджест-ветки выше отвечают на «дельта не менялась», и обе честно
    # отказывают, когда цель ПОГЛОТИЛА часть работы: дельта после этого другая, хотя ревьюер
    # читал ровно то же конечное содержимое (#507, сквош `b71e6310` схлопнул три пути в один
    # при пустом `git diff` между проверенным и текущим). Здесь сравниваются не дельты, а
    # конечные блобы по путям, поэтому равенство `production_paths_json` заменено на
    # подмножество и живёт только тут — старые две ветки не ослаблены.
    candidates = [(dict(row), "") for row in rows]
    if production_path_heads:
        seen = {str(receipt["receipt_id"]) for receipt, _ in candidates}
        with _conn() as connection:
            subset_rows = connection.execute(
                """SELECT * FROM review_receipts
                     WHERE scope=? AND session_id=? AND task_id=?
                       AND production_path_heads_json<>''
                       AND requested_at<=? AND completed_at IS NOT NULL AND completed_at<=?
                     ORDER BY completed_at DESC, requested_at DESC""",
                (scope, session_id, task_id, boundary, boundary),
            ).fetchall()
        for row in subset_rows:
            receipt = dict(row)
            if str(receipt["receipt_id"]) in seen:
                continue
            try:
                reviewed_heads = json.loads(receipt["production_path_heads_json"])
            except (TypeError, ValueError):
                continue
            if not isinstance(reviewed_heads, dict):
                continue
            if not reviewed_delta_covers(
                list(production_paths), production_path_heads, reviewed_heads,
            ):
                continue
            dropped = len(reviewed_heads) - len(production_paths)
            candidates.append((
                receipt,
                f"subset_of_reviewed_delta: {dropped} reviewed path(s) already in target",
            ))
    policy_ref = current_policy_ref()
    for receipt, subset_note in candidates:
        outcome = str(receipt.get("coverage_outcome") or "unknown")
        reviewed = _reviewed_receipt(receipt)
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
        verdict_value = str(receipt.get("verdict_value") or "")
        # Ревью без вердикта в артефакте отбивается ИМЕНЕМ, а не молча проваливается в общее
        # «квитанции нет»: причина разная и чинится разным — там ревью не запускали, здесь оно
        # прошло и не сказало ничего.
        if outcome == "reviewed" and not reviewed and receipt.get("verdict_present") != 1:
            return {
                **base,
                "status": "blocked",
                "reason": "review_verdict_missing",
                "receipt_id": str(receipt["receipt_id"]),
                "coverage_outcome": outcome,
                "author_outcome": author_outcome,
                "outcome_evidence_ref": outcome_evidence_ref,
            }
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
                "verdict_value": verdict_value,
            }
        if reviewed or skipped or unavailable:
            return {
                **base,
                "status": "satisfied",
                # Допуск подмножеством виден в журнале операции, а не только в чьей-то памяти:
                # ревьюер мог одобрить правку вместе с её страховкой, страховку потом откатили,
                # и приедет половина пакета. Риск принят владельцем осознанно (#509).
                "reason": subset_note,
                "receipt_id": str(receipt["receipt_id"]),
                "coverage_outcome": outcome,
                "author_outcome": author_outcome,
                "outcome_evidence_ref": outcome_evidence_ref,
                "verdict_value": verdict_value,
            }
    return _attested_decision(
        base=base, scope=scope, session_id=session_id, task_id=task_id,
        target_sha=target_sha, worker_head=worker_head,
        production_diff_sha256=production_diff_sha256,
        worktree=worktree, boundary=boundary,
    )


def _attested_decision(
    *, base: dict[str, object], scope: str, session_id: str, task_id: str,
    target_sha: str, worker_head: str, production_diff_sha256: str,
    worktree: str, boundary: str,
) -> dict[str, object]:
    """Постревьюная дельта: подпись автора, сверенная с артефактом ревью и с git.

    Отвергнутая альтернатива — «ещё один fix-only раунд, не тратящий потолок»: раунд по
    починке сам порождает находки, их починка даёт новую неподписанную дельту, и вопрос
    просто съезжает на раунд вперёд; а «не тратит потолок» решает тот же автор, чьё слово мы
    и перестали принимать на веру (#493, .orchestra/tasks/493/report.md).
    """
    if not worktree or not task_id:
        return base
    from app.db import _conn

    with _conn() as connection:
        rows = connection.execute(
            """SELECT * FROM review_receipts
                 WHERE scope=? AND session_id=? AND task_id=?
                   AND subject_kind='implementation' AND coverage_outcome='reviewed'
                   AND completed_at IS NOT NULL AND completed_at<=?
                 ORDER BY requested_at DESC, completed_at DESC, receipt_id DESC
                 LIMIT 20""",
            (scope, session_id, task_id, boundary),
        ).fetchall()
    # Подписать дельту может только ПОСЛЕДНЕЕ состоявшееся ревью. Перебор кандидатов позволял
    # автору держать две квитанции и, получив спорный или неразрешённый второй раунд,
    # аттестоваться против первого: второй отвечал `attestation_receipt_mismatch`, а перебор
    # шёл дальше и находил разрешающий (Sol, раунд 2).
    #
    # «Последнее» считается по `requested_at`, а НЕ по `completed_at`: предмет ревью пиннится
    # в момент ЗАКАЗА (`resolve_implementation_subject`), поэтому позже заказанное ревью
    # видело состояние не старше. По времени завершения порядок инвертируется — медленный
    # первый раунд финиширует после быстрого второго и снова становится «последним»
    # (Sol, раунд 3). Номер раунда для этого не годится: он уникален в пределах одного
    # `artifact_path`, а здесь кандидаты могут быть из разных веток ревью.
    latest = next((dict(raw) for raw in rows if _reviewed_receipt(dict(raw))), None)
    if latest is None:
        return base
    checked = verify_delta_attestation(
        worktree=worktree, task_id=task_id, receipt=latest,
        target_sha=target_sha, worker_head=worker_head,
        production_diff_sha256=production_diff_sha256,
    )
    if checked["ok"]:
        return {
            **base,
            "status": "satisfied",
            "reason": "",
            "receipt_id": str(latest["receipt_id"]),
            "coverage_outcome": "attested",
            "author_outcome": str(latest.get("author_outcome") or "unknown"),
            "outcome_evidence_ref": str(latest.get("outcome_evidence_ref") or ""),
            "verdict_value": str(latest.get("verdict_value") or ""),
            "attestation": {
                "receipt_id": str(latest["receipt_id"]),
                "reviewed_worker_head": str(latest.get("worker_head") or ""),
                "closed_findings": checked["closed_findings"],
                "delta_paths": checked["delta_paths"],
            },
        }
    # Отсутствие файла аттестации — НЕ отказ по аттестации, а прежнее состояние «на этот снимок
    # ревью нет»: автор её и не заявлял. Именем отбивается только заявленная и не прошедшая
    # проверку подпись, иначе отказ называл бы причиной механизм, которым никто не пользовался.
    if checked["reason"] == "attestation_missing":
        return base
    return {
        **base,
        "reason": str(checked["reason"]),
        "reason_detail": str(checked["detail"]),
        "receipt_id": str(latest["receipt_id"]),
    }
