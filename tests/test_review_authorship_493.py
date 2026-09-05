"""#493 — квитанцию ревью подписывает автор, а вердикт берётся из артефакта.

Требование юзера 04.09: «record_review_outcome почему ты пишешь, а не воркер или сам
ревьюер? ты-то откуда знаешь, что там и как — тебе напиздят, а ты поверишь». За один день
оркестратор выписал восемь квитанций покрытия, каждую — по ОТЧЁТУ воркера о ходе ревью.

Три шва, по одному на причину, по которой оркестратор оказывался в этой петле:
1. подпись автора (`record_review_outcome`) — только сессия, заказавшая ревью;
2. вердикт — только тот, что сервер вычитал из артефакта при закрытии квитанции;
3. постревьюная дельта — авторская аттестация, машинно сверенная с находками последнего
   раунда и с git; выход за их пределы обязан отбиваться.
"""
import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import pytest

ARTIFACT = """## Summary

Two findings.

## Findings

- `blocking: app/widget.py:1` — VALUE must be validated
- suggestion: app/helper.py:3 — extract the constant

## Verdict

**ACK — no blocking findings.**
"""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "author-493@test")
    _git(repo, "config", "user.name", "author 493")
    (repo / "README.md").write_text("base\n")
    admin = repo / "app" / "admin.py"
    admin.parent.mkdir(parents=True, exist_ok=True)
    admin.write_text("PERMISSION = 'read'\n")
    _git(repo, "add", "README.md", "app/admin.py")
    _git(repo, "commit", "-m", "base")
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-c", "task-493/author")
    widget = repo / "app" / "widget.py"
    widget.parent.mkdir(parents=True, exist_ok=True)
    widget.write_text("VALUE = 1\n")
    (repo / "app" / "helper.py").write_text("A = 1\nB = 2\nC = 3\n")
    _git(repo, "add", "app")
    _git(repo, "commit", "-m", "production change")
    return repo, target_sha, _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, relative: str, content: str) -> str:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", relative)
    _git(repo, "commit", "-m", f"#493: {relative}")
    return _git(repo, "rev-parse", "HEAD")


def _receipt(**overrides) -> dict:
    payload = {
        "receipt_id": f"review-receipt:{uuid.uuid4()}",
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "session-493",
        "worker_name": "author-493",
        "scope": "",
        "task_id": "493",
        "task_source": "session_lookup",
        "artifact_path": "",
        "mode": "implementation",
        "round": 1,
        "job_id": "bg-493",
        "usage_event_id": "usage-493",
        "requested_at": "2026-09-04T00:00:00+00:00",
        "completed_at": "2026-09-04T00:01:00+00:00",
        "status": "completed",
        "return_code": 0,
        "failure_code": "",
        "artifact_exists": 1,
        "artifact_bytes": len(ARTIFACT.encode()),
        "artifact_sha256": hashlib.sha256(ARTIFACT.encode()).hexdigest(),
        "verdict_present": 1,
        "verdict_value": "ACK — no blocking findings.",
        "jsonl_response_present": 1,
        "recovery_source": "",
        "author_outcome": "accepted",
        "outcome_source": "direct",
        "outcome_evidence_ref": ".orchestra/tasks/493/report.md#author-outcome",
        "notification_event_id": "",
        "subject_kind": "implementation",
        "target_sha": "",
        "worker_head": "",
        "production_snapshot_sha256": "",
        "production_diff_sha256": "",
        "production_paths_json": '["app/helper.py","app/widget.py"]',
        "coverage_outcome": "reviewed",
        "policy_ref": "",
        "decision_actor": "",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    """Состоявшееся ревью на снимок H1 плюс его артефакт на диске."""
    import app.acceptance as acceptance
    import app.db as db
    import app.merge_operations as operations
    from app.review_coverage import production_snapshot

    repo, target_sha, worker_head = _repo(tmp_path)
    artifact = repo / ".orchestra" / "tasks" / "493" / "codex-review-impl.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(ARTIFACT)
    _git(repo, "add", ".orchestra")
    _git(repo, "commit", "-m", "#493: review artifact")
    worker_head = _git(repo, "rev-parse", "HEAD")

    db_path = tmp_path / "authorship-493.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    monkeypatch.setattr(acceptance, "task_oracle_for_session", lambda _sid: {})
    monkeypatch.setattr(
        operations, "review_coverage_policy_active", lambda: True, raising=False,
    )
    snapshot = production_snapshot(
        str(repo), target_sha=target_sha, worker_head=worker_head,
    )
    receipt = _receipt(
        scope=str(repo),
        artifact_path=str(artifact),
        target_sha=target_sha,
        worker_head=worker_head,
        production_snapshot_sha256=str(snapshot["production_snapshot_sha256"]),
        production_diff_sha256=str(snapshot["production_diff_sha256"]),
    )
    db.review_receipt_create(receipt)
    return repo, target_sha, worker_head, receipt


def _decision(repo: Path) -> dict:
    import app.merge_operations as operations

    admission = operations._prepare_admission_snapshot(
        {
            "session_id": "session-493",
            "task_id": "493",
            "base_branch": "main",
            "worker_head": _git(repo, "rev-parse", "HEAD"),
            "worktree_path": str(repo),
        },
        operations.normalize_request(
            name="author-493", scope=str(repo), target="main",
        ),
    )
    return admission.get("review_coverage", {})


def _write_attestation(repo: Path, receipt: dict, closed: list[str], **overrides) -> Path:
    from app.review_coverage import attestation_path, production_snapshot

    subject = production_snapshot(
        str(repo),
        target_sha=_git(repo, "rev-parse", "main"),
        worker_head=_git(repo, "rev-parse", "HEAD"),
    )
    payload = {
        "receipt_id": receipt["receipt_id"],
        "reviewed_worker_head": receipt["worker_head"],
        "artifact_sha256": receipt["artifact_sha256"],
        "production_diff_sha256": str(subject["production_diff_sha256"]),
        "closed_findings": closed,
        "statement": "fixes for the accepted findings of the last round",
    }
    payload.update(overrides)
    path = attestation_path(str(repo), "493")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _git(repo, "add", str(path.relative_to(repo)))
    _git(repo, "commit", "-m", "#493: attestation")
    return path


# ── Шов 1: подпись автора ──

def _session_api(session_id: str, repo: Path):
    async def fake_api(method, path, **kwargs):
        assert path.startswith("/api/sessions/"), path
        return {
            "id": session_id,
            "worktree_path": str(repo),
            "task_id": "493",
            "base_branch": "main",
        }

    return fake_api


@pytest.mark.asyncio
async def test_only_the_review_author_records_its_outcome(reviewed, monkeypatch):
    """Плечо отказа: чужая сессия (оркестратор) подписать не может."""
    import app.db as db
    import app.mcp_stdio as mcp

    repo, _target, _head, receipt = reviewed
    db.review_receipt_finish(receipt["receipt_id"], {})
    with db._conn() as connection:
        connection.execute(
            "UPDATE review_receipts SET author_outcome='unknown' WHERE receipt_id=?",
            (receipt["receipt_id"],),
        )
    monkeypatch.setattr(mcp, "_api", _session_api("session-orchestrator", repo))
    monkeypatch.setattr(mcp, "WORKER_NAME", "Orchestra-orchestrator")

    result = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": receipt["receipt_id"],
        "outcome": "accepted",
        "outcome_evidence_ref": "he told me it went fine",
    })

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "review_outcome_forbidden"
    stored = db.review_receipt_get(receipt["receipt_id"])
    assert stored["author_outcome"] == "unknown", (
        "чужая подпись не должна доезжать до квитанции даже частично"
    )


@pytest.mark.asyncio
async def test_the_author_session_records_its_own_outcome(reviewed, monkeypatch):
    """Разрешающее плечо: без него отказ выше доказывал бы только вечный отказ."""
    import app.db as db
    import app.mcp_stdio as mcp

    repo, _target, _head, receipt = reviewed
    with db._conn() as connection:
        connection.execute(
            "UPDATE review_receipts SET author_outcome='unknown' WHERE receipt_id=?",
            (receipt["receipt_id"],),
        )
    monkeypatch.setattr(mcp, "_api", _session_api("session-493", repo))
    monkeypatch.setattr(mcp, "WORKER_NAME", "author-493")

    result = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": receipt["receipt_id"],
        "outcome": "accepted",
        "outcome_evidence_ref": ".orchestra/tasks/493/report.md#author-outcome",
    })

    assert result.isError is False, result.structuredContent
    assert db.review_receipt_get(receipt["receipt_id"])["author_outcome"] == "accepted"


# ── Шов 2: вердикт из артефакта ──

def test_review_without_a_verdict_in_the_artifact_authorizes_nothing(reviewed):
    import app.db as db

    repo, _target, _head, receipt = reviewed
    with db._conn() as connection:
        connection.execute(
            "UPDATE review_receipts SET verdict_present=0, verdict_value='' "
            "WHERE receipt_id=?",
            (receipt["receipt_id"],),
        )

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "review_verdict_missing", (
        "ревью без вердикта обязано отбиваться ИМЕНЕМ, а не общим «квитанции нет»"
    )


def test_the_merge_carries_the_verdict_read_from_the_artifact(reviewed):
    """Пересказ автора в доказательство мержа не попадает ни на одном пути."""
    repo, _target, _head, receipt = reviewed

    decision = _decision(repo)

    assert decision["status"] == "satisfied"
    assert decision["verdict_value"] == receipt["verdict_value"]


# ── Шов 3: постревьюная дельта ──

def test_delta_after_the_last_round_is_not_covered_by_the_review(reviewed):
    repo, _target, _head, _receipt = reviewed
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    # Аттестации автор не заявлял → причина прежняя, «на этот снимок ревью нет». Именем
    # отбивается только ЗАЯВЛЕННАЯ и не прошедшая проверку подпись (тесты ниже).
    assert decision["reason"] == "review_receipt_missing"


def test_the_author_attestation_covers_a_delta_inside_the_named_findings(reviewed):
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "satisfied", decision.get("reason")
    assert decision["coverage_outcome"] == "attested"
    assert decision["attestation"]["closed_findings"] == ["app/helper.py:3"]
    assert decision["attestation"]["delta_paths"] == ["app/helper.py"]


def test_attestation_does_not_stretch_to_a_file_the_review_never_named(reviewed):
    """Приёмка #493: дельта за пределами принятых находок обязана отбиваться."""
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/untouched.py", "NEW = 1\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_delta_outside_findings"
    assert "app/untouched.py" in decision["reason_detail"]


def test_attestation_cannot_close_a_finding_the_reviewer_never_wrote(reviewed):
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:999"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_findings_unknown"


def test_attestation_dies_with_the_artifact_it_quotes(reviewed):
    """Находки читаются из БАЙТОВ артефакта, поэтому байты здесь и пиннятся."""
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])
    _commit(
        repo,
        ".orchestra/tasks/493/codex-review-impl.md",
        ARTIFACT + "\n- blocking: app/untouched.py:1 — invented later\n",
    )

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_artifact_modified"


def test_attestation_signed_for_one_delta_does_not_cover_the_next(reviewed):
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])
    assert _decision(repo)["status"] == "satisfied"

    _commit(repo, "app/widget.py", "VALUE = 99\n")

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_diff_mismatch"


def test_attestation_sees_a_production_change_that_arrived_by_moving_the_target(reviewed):
    """Sol, раунд 1: дельта, не видимая диффом двух рабочих деревьев.

    После ревью автор мерджит свежий main и возвращает ЧУЖОЙ продовый файл в прежнее
    содержимое. Его дерево при этом не менялось (`H1..H2` пусто), а предмет ревью изменился:
    в продовом диффе против новой цели появился откат чужой правки, которого ревьюер не видел.
    """
    repo, _target, _head, receipt = reviewed
    reviewed_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "main")
    _commit(repo, "app/admin.py", "PERMISSION = 'write'\n")
    _git(repo, "switch", "task-493/author")
    _git(repo, "merge", "--no-edit", "main")
    _commit(repo, "app/admin.py", "PERMISSION = 'read'\n")
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")

    # Предусловие замера: дерево автора по чужому файлу НЕ изменилось — прежняя проверка
    # смотрела ровно сюда и потому была слепа.
    assert _git(
        repo, "diff", "--name-only", f"{reviewed_head}..HEAD", "--", "app/admin.py",
    ) == ""
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_delta_outside_findings"
    assert "app/admin.py" in decision["reason_detail"]


def test_one_closed_finding_does_not_license_every_file_named_in_the_round(reviewed):
    """Sol, раунд 1: `allowed` строится из ЗАКРЫТЫХ находок, а не из всех упомянутых."""
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/widget.py", "VALUE = 42\n")

    # `app/widget.py:1` в артефакте есть — но автор его закрытым не объявлял.
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_delta_outside_findings"
    assert "app/widget.py" in decision["reason_detail"]


@pytest.mark.parametrize(
    "anchor,reason",
    [
        ("../app/admin.py:1", "attestation_delta_outside_findings"),
        (".app/admin.py:1", "attestation_delta_outside_findings"),
        ("app\\admin.py:1", "attestation_findings_unknown"),
    ],
)
def test_a_finding_path_is_taken_literally_and_never_normalized(reviewed, anchor, reason):
    """Sol, раунд 1: нормализация пути превращала «почти путь» в настоящий продовый файл."""
    repo, _target, _head, receipt = reviewed
    artifact = repo / ".orchestra" / "tasks" / "493" / "codex-review-impl.md"
    spoofed = ARTIFACT.replace(
        "- suggestion: app/helper.py:3 — extract the constant",
        f"- suggestion: {anchor} — extract the constant",
    )
    artifact.write_text(spoofed)
    _git(repo, "add", str(artifact.relative_to(repo)))
    _git(repo, "commit", "-m", "#493: artifact")
    import app.db as db

    with db._conn() as connection:
        connection.execute(
            "UPDATE review_receipts SET artifact_sha256=?, artifact_bytes=? "
            "WHERE receipt_id=?",
            (
                hashlib.sha256(spoofed.encode()).hexdigest(),
                len(spoofed.encode()),
                receipt["receipt_id"],
            ),
        )
    _commit(repo, "app/admin.py", "PERMISSION = 'write'\n")
    _write_attestation(
        repo, {**receipt, "artifact_sha256": hashlib.sha256(spoofed.encode()).hexdigest()},
        [anchor],
    )

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == reason


def test_the_subject_is_identified_by_full_object_ids(reviewed):
    """Sol, раунд 2: `--full-index` разворачивает id только в патче, в `--raw` их 7 символов.

    На укороченном id личность предмета ревью держится на 28 битах — столько подбирается
    перебором, и два разных содержимых дают одну и ту же запись. Проверяется свойство, а не
    коллизия: запись обязана нести полные 40-символьные id обеих сторон.
    """
    import re as _re

    from app.review_coverage import _production_diff_entries

    repo, target_sha, _head, _receipt = reviewed
    entries = _production_diff_entries(repo, target_sha, _git(repo, "rev-parse", "HEAD"))

    assert entries, "предусловие: продовый дифф непуст"
    for path, record in entries.items():
        ids = _re.findall(r"\b[0-9a-f]{7,40}\b", record.split("\0")[0])
        assert ids, path
        assert all(len(item) == 40 for item in ids), (
            f"{path}: сокращённый object id в записи предмета — {record.split(chr(0))[0]!r}"
        )


def test_only_the_latest_review_can_authorize_the_delta(reviewed):
    """Sol, раунд 2: две квитанции, вторая спорная — подписывать нечем.

    Автор держит артефакты двух раундов, получает неразрешённый второй и аттестуется против
    первого. Перебор кандидатов находил разрешающую квитанцию; последнее ревью — не находит.
    """
    import app.db as db

    repo, _target, _head, receipt = reviewed
    second_artifact = repo / ".orchestra" / "tasks" / "493" / "codex-review-round2.md"
    second_artifact.write_text(ARTIFACT.replace("ACK", "needs work"))
    _git(repo, "add", str(second_artifact.relative_to(repo)))
    _git(repo, "commit", "-m", "#493: round 2 artifact")
    later = _receipt(
        receipt_id="review-receipt:later-493",
        scope=receipt["scope"],
        artifact_path=str(second_artifact),
        artifact_sha256=hashlib.sha256(second_artifact.read_bytes()).hexdigest(),
        artifact_bytes=second_artifact.stat().st_size,
        target_sha=receipt["target_sha"],
        worker_head=_git(repo, "rev-parse", "HEAD"),
        production_snapshot_sha256=receipt["production_snapshot_sha256"],
        production_diff_sha256=receipt["production_diff_sha256"],
        completed_at="2026-09-04T02:00:00+00:00",
        author_outcome="disputed",
        verdict_value="needs work",
    )
    db.review_receipt_create(later)
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_receipt_mismatch", (
        "подпись против прошлого раунда не должна перекрывать более свежее ревью"
    )


def test_a_slow_earlier_round_does_not_become_the_latest_review(reviewed):
    """Sol, раунд 3: порядок по времени ЗАВЕРШЕНИЯ инвертируется при параллельных раундах.

    R1 заказан раньше и финиширует позже, R2 заказан позже и финиширует спорным. По
    `completed_at` последним оказывался принятый R1, и подпись против него снова перекрывала
    более свежее ревью. Предмет пиннится в момент заказа → считаем по `requested_at`.
    """
    import app.db as db

    repo, _target, _head, receipt = reviewed
    second_artifact = repo / ".orchestra" / "tasks" / "493" / "codex-review-parallel.md"
    second_artifact.write_text(ARTIFACT.replace("ACK", "needs work"))
    _git(repo, "add", str(second_artifact.relative_to(repo)))
    _git(repo, "commit", "-m", "#493: parallel round artifact")
    db.review_receipt_create(_receipt(
        receipt_id="review-receipt:parallel-493",
        scope=receipt["scope"],
        artifact_path=str(second_artifact),
        artifact_sha256=hashlib.sha256(second_artifact.read_bytes()).hexdigest(),
        artifact_bytes=second_artifact.stat().st_size,
        target_sha=receipt["target_sha"],
        worker_head=_git(repo, "rev-parse", "HEAD"),
        production_snapshot_sha256=receipt["production_snapshot_sha256"],
        production_diff_sha256=receipt["production_diff_sha256"],
        # Заказан ПОЗЖЕ первого, а завершился РАНЬШЕ — ровно инверсия из находки.
        requested_at="2026-09-04T00:00:30+00:00",
        completed_at="2026-09-04T00:00:40+00:00",
        author_outcome="disputed",
        verdict_value="needs work",
    ))
    with db._conn() as connection:
        connection.execute(
            "UPDATE review_receipts SET completed_at='2026-09-04T00:05:00+00:00' "
            "WHERE receipt_id=?",
            (receipt["receipt_id"],),
        )
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_receipt_mismatch", (
        "медленный ранний раунд не должен становиться «последним ревью»"
    )


def test_a_corrupt_attestation_is_not_reported_as_an_absent_one(reviewed):
    """Sol, раунд 2: чинить надо подпись, а не запускать ревью заново."""
    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])
    _commit(repo, ".orchestra/tasks/493/review-attestation.json", "{ not json")

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_invalid"


def test_disputed_review_cannot_be_extended_by_an_attestation(reviewed):
    import app.db as db

    repo, _target, _head, receipt = reviewed
    with db._conn() as connection:
        connection.execute(
            "UPDATE review_receipts SET author_outcome='disputed' WHERE receipt_id=?",
            (receipt["receipt_id"],),
        )
    _commit(repo, "app/helper.py", "A = 1\nB = 2\nC = 30\n")
    _write_attestation(repo, receipt, ["app/helper.py:3"])

    decision = _decision(repo)

    assert decision["status"] == "blocked"
    assert decision["reason"] == "attestation_outcome_not_attestable"


@pytest.mark.asyncio
async def test_the_attestation_tool_refuses_to_leave_a_rejected_file_behind(
    reviewed, monkeypatch,
):
    import app.mcp_stdio as mcp
    from app.review_coverage import attestation_path

    repo, _target, _head, receipt = reviewed
    _commit(repo, "app/untouched.py", "NEW = 1\n")
    monkeypatch.setattr(mcp, "_api", _session_api("session-493", repo))
    monkeypatch.setattr(mcp, "WORKER_NAME", "author-493")

    result = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": receipt["receipt_id"],
        "outcome": "attested",
        "closed_findings": ["app/helper.py:3"],
        "statement": "unrelated rewrite",
    })

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "attestation_rejected"
    assert not attestation_path(str(repo), "493").exists(), (
        "отклонённая аттестация не остаётся на диске: иначе «файл есть» читается как подпись"
    )
