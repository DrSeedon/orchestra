"""#30 — недоставка обязана быть слышна там, где на другом конце человек.

Стенд живой: настоящий git-репозиторий, занятое имя ветки, отказ авто-switch — то есть
та же недоставка, что и в проде, а не подделанное исключение.
"""
import asyncio
import logging
import subprocess
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.db import init_db, save_session

    init_db()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
    (repo / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, capture_output=True, check=True)

    from app.workspace import create_worktree

    wt = create_worktree(str(repo), "worker", "30", base_branch="main")
    stolen = "adhoc-1785700000-1/worker"
    subprocess.run(["git", "branch", stolen, "main"], cwd=repo, capture_output=True, check=True)

    sid = str(uuid.uuid4())
    save_session({
        "id": sid, "name": "worker", "scope": str(repo), "cwd": str(repo),
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": wt.path,
        "branch": wt.branch, "base_branch": "main", "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 1,
    })
    import app.manager as mgr

    monkeypatch.setattr(mgr, "next_adhoc_branch", lambda _n: stolen)
    return {"repo": str(repo), "sid": sid, "stolen": stolen}


class _Msg:
    """Минимальное сообщение aiogram: путь ответа берёт из него чат и тему."""

    def __init__(self, chat_id=-100500, thread=7):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.message_thread_id = thread


@pytest.fixture
def tg(env, monkeypatch):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        from app.main import manager
        import app.tg_bridge as tgmod

        manager.sessions.clear()
        monkeypatch.setattr(tgmod, "_manager", manager, raising=False)
        monkeypatch.setattr(tgmod, "bot", object(), raising=False)
        sent = []

        async def fake_send(chat_id, text, thread_id=None, **kw):
            sent.append({"chat_id": chat_id, "text": text, "thread_id": thread_id, **kw})

        monkeypatch.setattr(tgmod, "_tg_send_safe", fake_send)
        yield {"tg": tgmod, "manager": manager, "sent": sent}


@pytest.mark.asyncio
async def test_user_is_told_once_per_batch_in_plain_words(env, tg, caplog):
    tgmod, sent = tg["tg"], tg["sent"]
    session = await tg["manager"].ensure_loaded_any("worker")
    batch = [(_Msg(), f"сообщение {i}", None) for i in range(3)]

    with caplog.at_level(logging.WARNING):
        await tgmod._flush_batch(session.id, batch)

    print("\nОТВЕТ ЮЗЕРУ:", sent[0]["text"] if sent else "НИЧЕГО")
    assert len(sent) == 1, f"на батч из трёх ушло {len(sent)} сообщений"
    text = sent[0]["text"]
    assert "worker" in text and "Повтори" in text
    for jargon in ("branch", "HEAD", "auto-switch", "ветк"):
        assert jargon not in text, f"жаргон в сообщении юзеру: {jargon}"
    assert sent[0]["chat_id"] == -100500 and sent[0]["thread_id"] == 7
    assert any("adhoc-1785700000-1/worker" in r.getMessage() for r in caplog.records), \
        "полная причина обязана остаться в журнале"


@pytest.mark.asyncio
async def test_fact_survives_in_session_history(env, tg):
    """Ограничение принято: ответ в чат уходит по тому же каналу, который мог упасть.
    Поэтому факт недоставки пишется ещё и в историю сессии — её видно в дашборде."""
    from app.db import get_logs

    tgmod = tg["tg"]
    session = await tg["manager"].ensure_loaded_any("worker")
    await tgmod._flush_batch(session.id, [(_Msg(), "сообщение", None)])

    rows = [r for r in get_logs(session.id, limit=50) if "[доставка]" in (r["content"] or "")]
    print("\nСЛЕД В ИСТОРИИ СЕССИИ:", rows[0]["content"][:120] if rows else "НЕТ")
    assert rows, "факт недоставки обязан пережить недоступность TG"


@pytest.mark.asyncio
async def test_successful_delivery_says_nothing_to_the_user(env, tg, monkeypatch):
    tgmod, sent = tg["tg"], tg["sent"]
    session = await tg["manager"].ensure_loaded_any("worker")

    async def ok(*_a, **_k):
        return None

    monkeypatch.setattr(tg["manager"], "send", ok)
    await tgmod._flush_batch(session.id, [(_Msg(), "сообщение", None)])
    assert sent == [], "удачная доставка не должна писать юзеру ничего"


@pytest.mark.asyncio
async def test_debounce_task_no_longer_swallows(env, tg):
    """Тот самый путь из Phase 1: фоновая задача дебаунса. Раньше юзер не получал ничего."""
    tgmod, sent = tg["tg"], tg["sent"]
    session = await tg["manager"].ensure_loaded_any("worker")
    from app.tasks import spawn_supervised

    task = spawn_supervised(
        tgmod._flush_batch(session.id, [(_Msg(), "из фоновой задачи", None)]),
        "проверка дебаунса",
    )
    await asyncio.sleep(0.5)
    print("\nФОНОВАЯ ЗАДАЧА: done=%s, сообщений юзеру=%d" % (task.done(), len(sent)))
    assert task.done() and task.exception() is None
    assert len(sent) == 1


class TestNotifyHasNoInventedRecipient:
    @pytest.mark.asyncio
    async def test_reports_to_scope_orchestrator(self, env):
        from app.db import save_session
        from app.notify import report_undelivered

        save_session({
            "id": "orch-1", "name": "boss", "scope": env["repo"], "cwd": env["repo"],
            "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
            "base_branch": "main", "is_orchestrator": True, "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "task_id": "", "needs_switch": 0,
        })
        got = []

        class Mgr:
            async def send(self, sid, text, *, provenance):
                assert provenance.origin == "platform"
                got.append((sid, text))

        outcome = await report_undelivered(Mgr(), scope=env["repo"], worker="worker",
                                           what="пробуждение", reason="RuntimeError: занято")
        print("\nАДРЕСАТ:", outcome, "|", got[0][1][:60] if got else "—")
        assert got and got[0][0] == "orch-1"
        assert "worker" in got[0][1] and "RuntimeError" in got[0][1]
        assert "boss" in outcome

    @pytest.mark.asyncio
    async def test_no_orchestrator_is_said_out_loud_not_invented(self, env, caplog):
        from app.notify import report_undelivered

        sent = []

        class Mgr:
            async def send(self, sid, text, *, provenance):
                assert provenance.origin == "platform"
                sent.append(sid)

        with caplog.at_level(logging.WARNING):
            outcome = await report_undelivered(Mgr(), scope="/nowhere", worker="сирота",
                                               what="пробуждение", reason="RuntimeError: x")
        print("\nБЕЗ ОРКЕСТРАТОРА:", outcome)
        assert sent == [], "получателя по умолчанию быть не должно"
        assert "некому сообщить" in outcome and "сирота" in outcome
        assert any("некому сообщить" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_bg_job_failure_reaches_the_orchestrator(env, monkeypatch):
    from app.db import save_session

    save_session({
        "id": "orch-2", "name": "boss", "scope": env["repo"], "cwd": env["repo"],
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": True, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    })
    import app.bg_jobs as bg

    told = []

    class Mgr:
        # #82: цель ищется по неизменяемому id, а не по имени.
        async def ensure_loaded_by_id(self, session_id):
            raise RuntimeError("auto-switch failed: branch already exists")

        async def send(self, sid, text, *, provenance):
            assert provenance.origin == "platform"
            told.append((sid, text))

    manager = bg.BgJobManager()
    manager.set_session_manager(Mgr())
    monkeypatch.setattr(bg, "bg_claim_trigger", lambda _job: True)
    monkeypatch.setattr(bg, "bg_fail_job", lambda *_a: None)
    monkeypatch.setattr(bg, "bg_get_job", lambda _job: {"target_session_id": "w-1"})
    await manager._trigger("job-1", "готово", "worker", env["repo"])
    print("\nBG-JOB → оркестратору:", told[0][1][:80] if told else "НИКОМУ")
    assert told and told[0][0] == "orch-2"
    assert "job-1" in told[0][1] and "worker" in told[0][1]


class TestSupervisedTasks:
    @pytest.mark.asyncio
    async def test_failure_is_logged_with_exception_class(self, caplog):
        from app.tasks import spawn_supervised

        async def boom():
            raise ValueError("падение внутри фоновой задачи")

        with caplog.at_level(logging.WARNING):
            task = spawn_supervised(boom(), "проверочная задача")
            await asyncio.sleep(0.1)
        messages = [r.getMessage() for r in caplog.records]
        print("\nСТРАЖ:", messages[-1] if messages else "тишина")
        assert task.done() and isinstance(task.exception(), ValueError)
        assert any("проверочная задача" in m and "ValueError" in m for m in messages)

    def test_no_ownerless_task_in_delivery_modules(self):
        """Страж класса — узкий намеренно: ловит ФОРМУ «задача без владельца».

        Задача, чей объект никому не присвоен, не может быть ни отменена, ни проверена:
        её исключение исчезает. Именно так терялось сообщение юзера (#30). Задачи,
        присвоенные переменной/атрибуту/реестру, этот страж не трогает — их владелец
        существует, и читает ли он результат, форма не покажет (см. отчёт).
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        offenders = []
        for name in ("tg_bridge.py", "manager.py", "bg_jobs.py"):
            for n, line in enumerate((root / "app" / name).read_text().splitlines(), 1):
                if line.strip().startswith("asyncio.create_task("):
                    offenders.append(f"{name}:{n}: {line.strip()}")
        assert not offenders, (
            "задача без владельца в модуле доставки — заверни в spawn_supervised:\n"
            + "\n".join(offenders)
        )
