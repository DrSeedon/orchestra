"""#474 — состоявшееся ревью переживает посторонний коммит в main, но не правку прода.

Замер 04.09 на #472: ревью Luna прошло (`review-receipt:01435214-…`, status=completed, rc=0,
coverage_outcome=reviewed), после чего в main приехал посторонний коммит `525684a4`, а воркер
дописал коммиты с тестами. Сырой продовый дифф остался БАЙТ-В-БАЙТ тем же — обе команды дают
одинаковые 167 байт:
    git diff --raw --full-index -z 2268e0fe...2735fcf1 -- app scripts
    git diff --raw --full-index -z 525684a4...598a5848 -- app scripts
— а дайджест сменился `67cf8c11…` → `f8f83743…`, потому что в него входил хеш ЦЕЛИ, и мерж был
отбит «production diff has no snapshot-bound review».

Пара близнецов. Второй важнее первого: он и есть доказательство, что гарантию не сняли, а
только отвязали от постороннего движения main.
"""
import subprocess
import uuid
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()


def _raw_production_diff(repo: Path, target_sha: str, head: str) -> bytes:
    return subprocess.run(
        [
            "git", "diff", "--raw", "--full-index", "-z",
            f"{target_sha}...{head}", "--", "app", "scripts",
        ],
        cwd=repo, capture_output=True, check=True,
    ).stdout


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    """main на T1, ветка воркера с продовой правкой на H1."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "drift-474@test")
    _git(repo, "config", "user.name", "drift 474")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-c", "task-474/worker")
    widget = repo / "app" / "widget.py"
    widget.parent.mkdir(parents=True, exist_ok=True)
    widget.write_text("VALUE = 1\n")
    _git(repo, "add", "app/widget.py")
    _git(repo, "commit", "-m", "production change")
    return repo, target_sha, _git(repo, "rev-parse", "HEAD")


def _advance_main_with_a_foreign_commit(repo: Path) -> str:
    """Чужая работа в main, продовых файлов этой задачи не касавшаяся."""
    _git(repo, "switch", "main")
    guard = repo / "app" / "memory_guard.py"
    guard.parent.mkdir(parents=True, exist_ok=True)
    guard.write_text("LIMIT = 1\n")
    _git(repo, "add", "app/memory_guard.py")
    _git(repo, "commit", "-m", "сторож памяти")
    moved = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "task-474/worker")
    return moved


def _receipt(**overrides) -> dict:
    payload = {
        "receipt_id": f"review-receipt:{uuid.uuid4()}",
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "session-474",
        "worker_name": "worker-474",
        "scope": "",
        "task_id": "474",
        "task_source": "session_lookup",
        "artifact_path": "/tmp/review-474.md",
        "mode": "implementation",
        "round": 1,
        "job_id": "bg-474",
        "usage_event_id": "usage-474",
        "requested_at": "2026-09-04T00:00:00+00:00",
        "completed_at": "2026-09-04T00:01:00+00:00",
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
        "outcome_evidence_ref": ".orchestra/tasks/474/report.md#author-outcome",
        "notification_event_id": "",
        "subject_kind": "implementation",
        "target_sha": "",
        "worker_head": "",
        "production_snapshot_sha256": "",
        "production_diff_sha256": "",
        "production_paths_json": '["app/widget.py"]',
        "coverage_outcome": "reviewed",
        "policy_ref": "",
        "decision_actor": "",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    """Репозиторий с состоявшимся ревью, привязанным к снимку на момент ревью."""
    import app.acceptance as acceptance
    import app.db as db
    import app.merge_operations as operations
    from app.review_coverage import production_snapshot

    repo, target_sha, worker_head = _repo(tmp_path)
    db_path = tmp_path / "drift-474.db"
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
    db.review_receipt_create(_receipt(
        scope=str(repo),
        target_sha=target_sha,
        worker_head=worker_head,
        production_snapshot_sha256=str(snapshot["production_snapshot_sha256"]),
        production_diff_sha256=str(snapshot["production_diff_sha256"]),
    ))
    return repo, target_sha, worker_head


def _decision(repo: Path) -> dict:
    import app.merge_operations as operations

    admission = operations._prepare_admission_snapshot(
        {
            "session_id": "session-474",
            "task_id": "474",
            "base_branch": "main",
            "worker_head": _git(repo, "rev-parse", "HEAD"),
            "worktree_path": str(repo),
        },
        operations.normalize_request(
            name="worker-474", scope=str(repo), target="main",
        ),
    )
    return admission.get("review_coverage", {})


def test_foreign_main_commit_does_not_invalidate_the_reviewed_production_diff(reviewed):
    repo, target_sha, worker_head = reviewed

    moved_target = _advance_main_with_a_foreign_commit(repo)
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_widget.py").write_text("def test_widget():\n    assert True\n")
    _git(repo, "add", "tests/test_widget.py")
    _git(repo, "commit", "-m", "#474: tests")
    moved_head = _git(repo, "rev-parse", "HEAD")

    # Предусловие замера: предмет ревью не менялся ни на байт. Без него тест зелен вакуумно —
    # он проверял бы допуск на диффе, который и правда стал другим.
    assert _raw_production_diff(repo, target_sha, worker_head) == _raw_production_diff(
        repo, moved_target, moved_head,
    )
    assert moved_target != target_sha

    decision = _decision(repo)

    assert decision.get("status") == "satisfied", (
        "review bound to an unchanged production diff must survive a foreign main commit; "
        f"got {decision.get('reason')!r}"
    )
    assert decision.get("coverage_outcome") == "reviewed"


def test_one_changed_production_byte_still_revokes_the_receipt(reviewed):
    """Ослабление касается ТОЛЬКО неизменного предмета — иначе гарантии больше нет."""
    repo, target_sha, worker_head = reviewed

    _advance_main_with_a_foreign_commit(repo)
    (repo / "app" / "widget.py").write_text("VALUE = 2\n")
    _git(repo, "add", "app/widget.py")
    _git(repo, "commit", "-m", "#474: one byte")

    assert _raw_production_diff(repo, target_sha, worker_head) != _raw_production_diff(
        repo, _git(repo, "rev-parse", "main"), _git(repo, "rev-parse", "HEAD"),
    )

    decision = _decision(repo)

    assert decision.get("status") == "blocked", (
        "a changed production diff must not be covered by the old receipt"
    )
    assert decision.get("reason") == "review_receipt_missing"


def test_receipt_without_a_diff_digest_stays_bound_to_its_target(reviewed):
    """Квитанции до #474 не переписываются задним числом и остаются привязаны к цели.

    Пустой `production_diff_sha256` не покрывает ничего: без явного `<>''` в допуске он
    совпал бы сам с собой у любой квитанции, где колонка пуста.
    """
    import app.db as db

    with db._conn() as connection:
        connection.execute("UPDATE review_receipts SET production_diff_sha256=''")

    assert _decision(repo=reviewed[0]).get("status") == "satisfied", (
        "a legacy receipt must still cover its own target"
    )

    _advance_main_with_a_foreign_commit(reviewed[0])

    assert _decision(repo=reviewed[0]).get("reason") == "review_receipt_missing"


def test_empty_production_diff_never_matches_a_legacy_empty_digest(reviewed):
    """Отрицательный контроль на `production_diff_sha256<>''` в допуске.

    Продовая правка может быть НЕ в коммитах: `changed_paths` считает и untracked-файлы,
    поэтому существует состояние «продовый путь есть, а сырой дифф пуст». Дайджест такого
    состояния — пустая строка, и без явного `<>''` он совпал бы с пустой колонкой ЛЮБОЙ
    квитанции до #474, то есть чужое ревью авторизовало бы непросмотренный файл.
    """
    import app.db as db

    repo, _target_sha, _worker_head = reviewed
    with db._conn() as connection:
        connection.execute("UPDATE review_receipts SET production_diff_sha256=''")

    # Продовый коммит откачен → сырой дифф к цели пуст; продовый путь остаётся untracked-файлом.
    (repo / "app" / "widget.py").unlink()
    _git(repo, "add", "-A", "app")
    _git(repo, "commit", "-m", "#474: revert the reviewed production change")
    (repo / "app" / "extra.py").write_text("EXTRA = 1\n")

    assert _raw_production_diff(repo, _git(repo, "rev-parse", "main"), _git(repo, "rev-parse", "HEAD")) == b""

    decision = _decision(repo)

    assert decision.get("required") is True, "untracked production path must still require review"
    assert decision.get("production_diff_sha256") == ""
    assert decision.get("status") == "blocked", (
        "an empty production diff must not be authorized by a legacy empty digest"
    )


def test_unresolvable_worker_head_is_a_structured_refusal_not_a_crash(reviewed):
    """#474 — неразрешимый ref даёт ОПРЕДЕЛЁННЫЙ отказ, а не исключение наружу.

    Это возможное состояние прода, а не выдумка стенда: ветку сносят, worktree переезжает,
    ссылку переписывают. Раньше `ValueError` из `_git_bytes` летел через
    `_prepare_admission_snapshot` наружу и ронял весь путь мержа
    (`fatal: Invalid symmetric difference expression <sha>...bbbb…`).
    """
    import app.merge_operations as operations

    repo, _target_sha, _worker_head = reviewed

    admission = operations._prepare_admission_snapshot(
        {
            "session_id": "session-474",
            "task_id": "474",
            "base_branch": "main",
            "worker_head": "b" * 40,
            "worktree_path": str(repo),
        },
        operations.normalize_request(
            name="worker-474", scope=str(repo), target="main",
        ),
    )
    decision = admission.get("review_coverage", {})

    assert decision.get("status") == "blocked", "fail-closed: не посчитали снимок — не мержим"
    assert decision.get("required") is True
    assert decision.get("reason") == "review_snapshot_unavailable"
    assert "fatal" in str(decision.get("reason_detail") or ""), (
        "отказ обязан нести причину от git, иначе он неотличим от отсутствия квитанции"
    )


def test_unresolvable_target_branch_in_revalidation_is_a_structured_refusal(tmp_path):
    """Второй шов того же класса: цель не разрешается на этапе перепроверки.

    Предусловие устанавливается ЗДЕСЬ, а не наследуется от окружения. Прежняя версия брала
    просто пустой каталог и рассчитывала, что он лежит вне любого git-репозитория; это
    свойство принадлежит машине, а не тесту. Замер 04.09 (#474): под `TMPDIR` внутри чекаута
    (именно так шёл прогон merge-гейта) `main` РАЗРЕШАЛСЯ обходом вверх, `_target_head`
    отрабатывал, и до `_review_snapshot_unavailable` дело доходило уже из другого шва —
    `production_snapshot` с `Invalid symmetric difference expression`. Тест при этом краснел
    на третьей строке, а два первых утверждения проходили: он мерил НЕ ТОТ шов и молчал об этом.

    Отсюда две правки. Свой репозиторий ограничивает обход вверх детерминированно, а
    утверждение опирается на текст, которым владеет НАШ код (`cannot resolve merge target`),
    а не на формулировку git, зависящую от версии и от точки запуска. Заодно это и различитель
    швов: сработай вместо цели снимок, в `reason_detail` стояло бы `Invalid symmetric
    difference`, и тест обязан покраснеть.
    """
    import app.merge_operations as operations

    repo, _target_sha, _worker_head = _repo(tmp_path)
    _git(repo, "branch", "-D", "main")

    # Предусловие, а не надежда: репозиторий наш, и `main` в нём действительно не разрешается.
    assert (repo / ".git").exists()
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "main^{commit}"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert probe.returncode != 0, "предусловие сломано: цель разрешается, шов не тот"

    decision = operations._revalidate_review_coverage(
        {"request": {"target": "main"}, "accepted_admission": {}},
        {"worktree_path": str(repo), "worker_head": "b" * 40,
         "session_id": "session-474", "task_id": "474", "scope": str(repo)},
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "review_snapshot_unavailable"
    assert "cannot resolve merge target main" in decision["reason_detail"], (
        "отказ обязан прийти из ШВА ЦЕЛИ; получено: " + repr(decision["reason_detail"])
    )


def test_untracked_production_file_is_not_covered_by_the_old_receipt(reviewed):
    """Находка Luna, раунд 1 #474: `git diff` не видит untracked, а `changed_paths` видит.

    Добавленный после ревью untracked `app/new.py` оставляет ОБА дайджеста прежними, и при той
    же цели квитанция проходила бы по target-привязанной ветке — то есть ревью одного файла
    авторизовало бы второй, непросмотренный. Закрыто сравнением `production_paths_json`.
    """
    repo, target_sha, worker_head = reviewed

    before = _decision(repo)
    assert before.get("status") == "satisfied", "предусловие: до появления файла ревью покрывает"

    (repo / "app" / "new.py").write_text("SNEAKED = 1\n")

    # Предусловие находки: оба дайджеста НЕ изменились — untracked-файла в `git diff` нет.
    after = _decision(repo)
    assert after.get("production_snapshot_sha256") == before.get("production_snapshot_sha256")
    assert after.get("production_diff_sha256") == before.get("production_diff_sha256")
    assert "app/new.py" in (after.get("production_paths") or [])

    assert after.get("status") == "blocked", (
        "untracked production file must not inherit coverage from the reviewed diff"
    )
    assert after.get("reason") == "review_receipt_missing"


def test_unresolvable_target_in_initial_admission_is_a_structured_refusal(tmp_path, monkeypatch):
    """#474 раунд 2: второй вход в admission тоже обязан отказывать, а не падать.

    `_prepare_admission_snapshot` звал `_target_head` напрямую. Исключение оттуда ловил общий
    `except` вызывающего и называло причиной ОРАКУЛ (`ORACLE_METADATA_INVALID`), которого
    проблема не касается. Отказ обязан называть настоящую причину.
    """
    import app.acceptance as acceptance
    import app.db as db
    import app.merge_operations as operations

    repo, _target_sha, _worker_head = _repo(tmp_path)
    db_path = tmp_path / "no-target.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    monkeypatch.setattr(acceptance, "task_oracle_for_session", lambda _sid: {})
    monkeypatch.setattr(
        operations, "review_coverage_policy_active", lambda: True, raising=False,
    )
    _git(repo, "branch", "-D", "main")

    admission = operations._prepare_admission_snapshot(
        {
            "session_id": "session-474",
            "task_id": "474",
            "base_branch": "main",
            "worker_head": _git(repo, "rev-parse", "HEAD"),
            "worktree_path": str(repo),
        },
        operations.normalize_request(
            name="worker-474", scope=str(repo), target="main",
        ),
    )
    decision = admission.get("review_coverage", {})

    assert decision.get("status") == "blocked"
    assert decision.get("reason") == "review_snapshot_unavailable"
    assert "cannot resolve merge target main" in str(decision.get("reason_detail") or ""), (
        "отказ обязан прийти из шва ЦЕЛИ, а не из снимка; получено: "
        + repr(decision.get("reason_detail"))
    )

    error, action = operations._review_coverage_refusal(
        "op-474", decision, execution=False,
    )
    assert error["code"] == "REVIEW_SNAPSHOT_UNAVAILABLE", (
        "refusal must name the real cause, not 'no qualifying receipt'"
    )
    assert decision["reason_detail"] in error["message"]
    assert action["code"] == "FIX_WORKER_REFS_THEN_NEW_OPERATION"


def test_replayed_skip_receipt_from_before_the_new_column_is_not_a_conflict(tmp_path, monkeypatch):
    """#474 раунд 2: skip-полоса не должна ни писать NULL, ни ломаться на повторе.

    `review_receipt_record_skip` строит значения через `receipt.get(key)` и нормализует лишь
    часть колонок: payload без нового ключа дал бы `NOT NULL constraint failed`. А включение
    нового дайджеста в identity повтора превращало бы вторую попытку ТОГО ЖЕ решения в
    `skip decision id conflicts with existing provenance`, потому что у старой строки колонка
    пуста.
    """
    import app.db as db

    db_path = tmp_path / "skip-474.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    payload = _receipt(
        receipt_id="review-skip:474",
        scope=str(tmp_path),
        target_sha="1" * 40,
        worker_head="2" * 40,
        production_snapshot_sha256="3" * 64,
        coverage_outcome="skipped",
        status="completed",
        return_code=None,
        artifact_path="",
        round=None,
        artifact_exists=0,
        artifact_bytes=0,
        verdict_present=0,
        jsonl_response_present=0,
        policy_ref="codex-debate@sha256:" + "4" * 64,
        decision_actor="orchestrator",
    )
    # Payload БЕЗ нового ключа — ровно то, что пришлёт вызывающий, не знающий про #474.
    payload.pop("production_diff_sha256")

    saved = db.review_receipt_record_skip(dict(payload))
    assert saved["production_diff_sha256"] == "", "NOT NULL column must default, not crash"

    replay = db.review_receipt_record_skip({**payload, "production_diff_sha256": "5" * 64})
    assert replay["receipt_id"] == saved["receipt_id"], "same decision must replay, not conflict"
