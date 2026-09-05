"""#509 — ревью переживает поглощение части работы целью, и заказчик отделён от предмета.

Замер 05.09 на #507: Luna проверила три файла, затем чужой сквош `b71e6310` увёз часть той же
работы в main. `production_paths_json` схлопнулся с трёх путей до одного, `target_sha` и
`production_snapshot_sha256` сменились сами, `production_diff_sha256` тоже — и правомерно:
дельта после сквоша ДРУГАЯ, ревьюировали `11695d7b…82d741f8`, где `app/db.py` несёт оба
коммита, а осталось только второй. Совпадает конечное содержимое, и ни одно существующее поле
квитанции этого не выражало.

Отрицательные плечи здесь важнее положительного: они доказывают, что подмножество не стало
дырой. Непроверенный код в дельте — это лишний путь или другой блоб, и оба обязаны отказывать.
"""
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    """main на базе, ветка воркера с ТРЕМЯ продовыми файлами."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "subject-509@test")
    _git(repo, "config", "user.name", "subject 509")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-c", "task-509/worker")
    for name, body in (
        ("app/db.py", "GUARD = False\n"),
        ("app/runtime_history.py", "BUDGET = 16000\n"),
        ("app/session.py", "DELIVERY = True\n"),
    ):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    _git(repo, "add", "app")
    _git(repo, "commit", "-m", "#509: three production files")
    return repo, target_sha, _git(repo, "rev-parse", "HEAD")


def _target_absorbs(repo: Path, *paths: str) -> str:
    """Чужой сквош увозит часть ТОЙ ЖЕ работы в main — как `b71e6310` в #507."""
    worker = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "switch", "main")
    for path in paths:
        _git(repo, "checkout", worker, "--", path)
    _git(repo, "add", *paths)
    _git(repo, "commit", "-m", "squash of part of the same work")
    moved = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", worker)
    _git(repo, "merge", "main", "-m", "merge main")
    return moved


def _receipt(**overrides) -> dict:
    payload = {
        "receipt_id": f"review-receipt:{uuid.uuid4()}",
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "session-509",
        "worker_name": "worker-509",
        "scope": "",
        "task_id": "509",
        "task_source": "session_lookup",
        "artifact_path": "/tmp/review-509.md",
        "mode": "implementation",
        "round": 1,
        "job_id": "bg-509",
        "usage_event_id": "usage-509",
        "requested_at": "2026-09-05T00:00:00+00:00",
        "completed_at": "2026-09-05T00:01:00+00:00",
        "status": "completed",
        "return_code": 0,
        "failure_code": "",
        "artifact_exists": 1,
        "artifact_bytes": 10,
        "artifact_sha256": "a" * 64,
        "verdict_present": 1,
        "verdict_value": "ACK",
        "jsonl_response_present": 1,
        "recovery_source": "",
        "author_outcome": "accepted",
        "outcome_source": "direct",
        "outcome_evidence_ref": ".orchestra/tasks/509/result.md#author-outcome",
        "notification_event_id": "",
        "subject_kind": "implementation",
        "coverage_outcome": "reviewed",
        "policy_ref": "",
        "decision_actor": "",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    import app.acceptance as acceptance
    import app.db as db
    import app.merge_operations as operations
    from app.review_coverage import production_snapshot

    repo, target_sha, worker_head = _repo(tmp_path)
    db_path = tmp_path / "subject-509.db"
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
    assert sorted(snapshot["production_path_heads"]) == [
        "app/db.py", "app/runtime_history.py", "app/session.py",
    ]
    db.review_receipt_create(_receipt(
        scope=str(repo),
        target_sha=target_sha,
        worker_head=worker_head,
        production_snapshot_sha256=str(snapshot["production_snapshot_sha256"]),
        production_diff_sha256=str(snapshot["production_diff_sha256"]),
        production_paths_json=str(snapshot["production_paths_json"]),
        production_path_heads_json=str(snapshot["production_path_heads_json"]),
    ))
    return repo, target_sha, worker_head


def _decision(repo: Path) -> dict:
    import app.merge_operations as operations

    admission = operations._prepare_admission_snapshot(
        {
            "session_id": "session-509",
            "task_id": "509",
            "base_branch": "main",
            "worker_head": _git(repo, "rev-parse", "HEAD"),
            "worktree_path": str(repo),
        },
        operations.normalize_request(
            name="worker-509", scope=str(repo), target="main",
        ),
    )
    return admission.get("review_coverage", {})


def test_target_absorbing_part_of_the_reviewed_work_keeps_the_coverage(reviewed):
    repo, target_sha, worker_head = reviewed

    moved_target = _target_absorbs(repo, "app/runtime_history.py", "app/session.py")

    # Предусловия замера, без которых тест зелен вакуумно: дельта РЕАЛЬНО схлопнулась в один
    # путь, и её сырой дифф РЕАЛЬНО стал другим — то есть ни одна из двух старых веток здесь
    # помочь уже не может.
    from app.review_coverage import production_snapshot

    now = production_snapshot(
        str(repo), target_sha=moved_target, worker_head=_git(repo, "rev-parse", "HEAD"),
    )
    before = production_snapshot(
        str(repo), target_sha=target_sha, worker_head=worker_head,
    )
    assert json.loads(now["production_paths_json"]) == ["app/db.py"]
    assert now["production_diff_sha256"] != before["production_diff_sha256"]
    assert now["production_snapshot_sha256"] != before["production_snapshot_sha256"]
    assert now["production_path_heads"]["app/db.py"] == (
        before["production_path_heads"]["app/db.py"]
    )

    decision = _decision(repo)

    assert decision.get("status") == "satisfied", (
        "delta that shrank into the reviewed one must stay covered; "
        f"got {decision.get('reason')!r}"
    )
    assert decision.get("coverage_outcome") == "reviewed"
    # Допуск подмножеством обязан быть виден в журнале операции, а не только в чьей-то памяти.
    assert decision.get("reason", "").startswith("subset_of_reviewed_delta")
    assert "2 reviewed path(s)" in decision["reason"]


def test_one_changed_byte_in_the_surviving_file_revokes_the_coverage(reviewed):
    """Ослабление касается ТОЛЬКО неизменного содержимого — иначе гарантии больше нет."""
    repo, _target_sha, _worker_head = reviewed

    _target_absorbs(repo, "app/runtime_history.py", "app/session.py")
    (repo / "app" / "db.py").write_text("GUARD = True\n")
    _git(repo, "add", "app/db.py")
    _git(repo, "commit", "-m", "#509: unreviewed production byte")

    decision = _decision(repo)

    assert decision.get("status") == "blocked"
    assert decision.get("reason") == "review_receipt_missing"


def test_untracked_production_file_is_not_a_subset_of_the_reviewed_delta(reviewed):
    """`git diff` untracked не видит, поэтому его нет в карте — и он обязан отказывать."""
    repo, _target_sha, _worker_head = reviewed

    _target_absorbs(repo, "app/runtime_history.py", "app/session.py")
    (repo / "app" / "new.py").write_text("SNEAKED = True\n")

    decision = _decision(repo)

    assert "app/new.py" in decision.get("production_paths", [])
    assert decision.get("status") == "blocked"
    assert decision.get("reason") == "review_receipt_missing"


def test_same_blob_with_a_changed_file_mode_revokes_the_coverage(reviewed):
    """Блоб один и тот же, а файл уже другой — Luna, раунд 1 #509.

    Замеренный git-вывод `chmod +x` над отревьюированным файлом:
    `:100644 100755 4e5de3a4… 4e5de3a4… M` — dst-sha совпадает побайтово, меняется только
    режим. Тот же зазор шире: замена обычного файла симлинком с тем же блобом даёт
    `:100644 120000 <sha> <sha> T`. Карта из одних sha пропустила бы и то и другое.
    """
    repo, target_sha, worker_head = reviewed
    from app.review_coverage import production_snapshot

    before = production_snapshot(
        str(repo), target_sha=target_sha, worker_head=worker_head,
    )
    _target_absorbs(repo, "app/runtime_history.py", "app/session.py")
    (repo / "app" / "db.py").chmod(0o755)
    _git(repo, "add", "app/db.py")
    _git(repo, "commit", "-m", "#509: same blob, different mode")

    raw = subprocess.run(
        ["git", "diff", "--raw", "--full-index", "--no-abbrev", "-z",
         f"{_git(repo, 'rev-parse', 'main')}...HEAD", "--", "app"],
        cwd=repo, capture_output=True, check=True,
    ).stdout.decode()
    # Предусловия: режим действительно сменился, а блоб действительно тот же, что читал
    # ревьюер. Без них тест зелен вакуумно — он ловил бы обычную правку содержимого.
    record = next(part for part in raw.split("\0") if part.startswith(":")).split(" ")
    assert record[1] == "100755"
    assert record[3] in before["production_path_heads"]["app/db.py"]

    decision = _decision(repo)

    assert decision.get("status") == "blocked"
    assert decision.get("reason") == "review_receipt_missing"


def test_committed_file_outside_the_reviewed_map_revokes_the_coverage(reviewed):
    repo, _target_sha, _worker_head = reviewed

    _target_absorbs(repo, "app/runtime_history.py", "app/session.py")
    (repo / "app" / "extra.py").write_text("EXTRA = 1\n")
    _git(repo, "add", "app/extra.py")
    _git(repo, "commit", "-m", "#509: production file the reviewer never saw")

    decision = _decision(repo)

    assert decision.get("status") == "blocked"
    assert decision.get("reason") == "review_receipt_missing"


def test_legacy_receipt_without_the_heads_map_never_uses_the_subset_branch(reviewed):
    """Старые квитанции не переписываются, поэтому подмножеством не допускаются вовсе."""
    import app.db as db

    repo, _target_sha, _worker_head = reviewed
    with db._conn() as connection:
        connection.execute("UPDATE review_receipts SET production_path_heads_json=''")
    _target_absorbs(repo, "app/runtime_history.py", "app/session.py")

    decision = _decision(repo)

    assert decision.get("status") == "blocked"
    assert decision.get("reason") == "review_receipt_missing"


def _save_session(db, *, session_id: str, name: str, scope: str, worktree: str,
                  is_orchestrator: bool, task_id: str) -> None:
    db.save_session({
        "id": session_id,
        "name": name,
        "scope": scope,
        "cwd": scope,
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": worktree,
        "branch": "main" if is_orchestrator else "task-509/worker",
        "base_branch": "main",
        "is_orchestrator": is_orchestrator,
        "role": "orchestrator" if is_orchestrator else "worker",
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": task_id,
        "needs_switch": 0,
    })


@pytest.mark.asyncio
async def test_review_subject_route_pins_the_target_and_refuses_a_plain_worker(
    tmp_path, monkeypatch,
):
    from starlette.requests import Request

    import app.db as db
    import app.mcp_proof as proof
    import app.routes.merge_operations as route

    handler = getattr(route, "resolve_review_subject", None)
    assert callable(handler), "no server endpoint pins another worker's review subject"
    repo, target_sha, worker_head = _repo(tmp_path)
    db_path = tmp_path / "subject-route-509.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    _save_session(
        db, session_id="orchestrator-509", name="Orchestra-orchestrator",
        scope=str(repo), worktree=str(repo), is_orchestrator=True, task_id="",
    )
    _save_session(
        db, session_id="session-509", name="worker-509", scope=str(repo),
        worktree=str(repo), is_orchestrator=False, task_id="509",
    )

    def request(session_id: str) -> Request:
        return Request({
            "type": "http", "method": "POST",
            "path": "/api/merge-operations/review-subject",
            "headers": [
                (b"x-orchestra-session-id", session_id.encode()),
                (b"x-orchestra-mcp-proof", proof.issue_mcp_proof(session_id).encode()),
            ],
        })

    payload = {"target_worker": "worker-509", "scope": str(repo)}

    refused = await handler(payload, request("session-509"))
    assert refused.status_code == 403
    assert b"orchestrator-only" in refused.body
    assert worker_head.encode() not in refused.body

    allowed = await handler(payload, request("orchestrator-509"))
    assert allowed.status_code == 200
    body = json.loads(allowed.body)["result"]
    assert body["owner"] == {
        "session_id": "session-509",
        "worker_name": "worker-509",
        "task_id": "509",
        "worktree_path": str(repo),
        "base_branch": "main",
    }
    assert body["subject"]["target_sha"] == target_sha
    assert body["subject"]["worker_head"] == worker_head
    assert sorted(json.loads(body["subject"]["production_path_heads_json"])) == [
        "app/db.py", "app/runtime_history.py", "app/session.py",
    ]


@pytest.mark.asyncio
async def test_the_requester_signs_the_outcome_and_the_subject_owner_cannot(
    tmp_path, monkeypatch,
):
    """Оба видны в квитанции: подписывает заказчик, предмет принадлежит воркеру."""
    import app.db as db
    import app.mcp_stdio as mcp

    db_path = tmp_path / "signer-509.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    receipt_id = f"review-receipt:{uuid.uuid4()}"
    db.review_receipt_create(_receipt(
        receipt_id=receipt_id,
        scope="/repo",
        session_id="session-509",
        worker_name="worker-509",
        requested_by_session_id="orchestrator-509",
        requested_by_worker="Orchestra-orchestrator",
        author_outcome="unknown",
        outcome_evidence_ref="",
    ))

    async def fake_api(_method, _path, **_kwargs):
        return {"id": caller["id"]}

    caller = {"id": "session-509"}
    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "worker-509")
    monkeypatch.setattr(mcp, "SCOPE", "/repo")

    with pytest.raises(mcp.ApiToolError) as refused:
        await mcp._receipt_author_session(receipt_id)
    assert refused.value.code == "review_outcome_forbidden"
    assert "Orchestra-orchestrator" in refused.value.message

    caller["id"] = "orchestrator-509"
    signed, _info = await mcp._receipt_author_session(receipt_id)
    assert signed["session_id"] == "session-509"
    assert signed["requested_by_session_id"] == "orchestrator-509"


@pytest.mark.asyncio
async def test_cross_worker_attestation_refuses_by_name_not_by_missing_task(
    tmp_path, monkeypatch,
):
    """Аттестация пишет файл в дерево ВЛАДЕЛЬЦА, а в чужое дерево мы не пишем.

    Прежний отказ назвал бы неверную причину: у оркестратора `task_id` пуст, и подписант
    получил бы «attestation needs a bound task» вместо настоящей причины.
    """
    import app.db as db
    import app.mcp_stdio as mcp

    db_path = tmp_path / "cross-attest-509.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    receipt_id = f"review-receipt:{uuid.uuid4()}"
    db.review_receipt_create(_receipt(
        receipt_id=receipt_id, scope="/repo",
        session_id="session-509", worker_name="worker-509",
        requested_by_session_id="orchestrator-509",
        requested_by_worker="Orchestra-orchestrator",
    ))

    async def fake_api(_method, _path, **_kwargs):
        return {"id": "orchestrator-509", "worktree_path": "/repo", "task_id": ""}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "Orchestra-orchestrator")
    monkeypatch.setattr(mcp, "SCOPE", "/repo")

    with pytest.raises(mcp.ApiToolError) as refused:
        await mcp._write_delta_attestation(receipt_id, ["app/db.py:10"], "closed")
    assert refused.value.code == "attestation_cross_worker_unsupported"
    assert "worker-509" in refused.value.message


@pytest.mark.asyncio
async def test_a_legacy_receipt_is_still_signed_by_its_own_session(tmp_path, monkeypatch):
    import app.db as db
    import app.mcp_stdio as mcp

    db_path = tmp_path / "legacy-signer-509.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    receipt_id = f"review-receipt:{uuid.uuid4()}"
    db.review_receipt_create(_receipt(
        receipt_id=receipt_id, scope="/repo", author_outcome="unknown",
        outcome_evidence_ref="",
    ))
    with db._conn() as connection:
        connection.execute("UPDATE review_receipts SET requested_by_session_id=''")

    async def fake_api(_method, _path, **_kwargs):
        return {"id": "session-509"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "worker-509")
    monkeypatch.setattr(mcp, "SCOPE", "/repo")

    receipt, _info = await mcp._receipt_author_session(receipt_id)
    assert receipt["receipt_id"] == receipt_id
