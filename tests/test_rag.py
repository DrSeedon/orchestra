"""Tests for app/rag.py — chunkers, log classification, index/dedup/delete, unified
search + project isolation, backfill. Ported from kesha-tg-bot/tests/test_rag_files.py,
adapted for Orchestra (project namespace, log layer, [from:] agent_msg classification).

Pure-logic tests (chunkers, _classify_log, _rrf, file_change_target) run WITHOUT the model.
Embed-dependent tests are marked `@pytest.mark.rag` and skip when fastembed/model unavailable.
"""

import asyncio
import sqlite3
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import rag


@pytest.mark.asyncio
async def test_background_backfill_trims_native_heap(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    trimmed = []

    class FakeRag:
        def backfill_files(self):
            return 1

        def pending_files(self):
            return 0

    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(rag, "_executor", executor)
    monkeypatch.setattr(rag, "get_rag", lambda: FakeRag())
    monkeypatch.setattr(
        "app.native_memory.trim_native_heap",
        lambda reason: trimmed.append(reason) or True,
    )
    try:
        loop = asyncio.get_running_loop()
        assert await rag.run(loop, "backfill_files") == 1
        assert await rag.run(loop, "pending_files") == 0
    finally:
        executor.shutdown(wait=True)

    assert trimmed == ["rag:backfill_files"]


def test_background_onnx_default_is_single_thread():
    """The default must leave one CPU lane to latency-sensitive work."""
    env = os.environ.copy()
    env.pop("RAG_ONNX_THREADS", None)
    result = subprocess.run(
        [sys.executable, "-c", "from app import rag; print(rag.RAG_ONNX_THREADS)"],
        cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1"


def test_background_onnx_explicit_thread_override_is_preserved():
    env = os.environ.copy()
    env["RAG_ONNX_THREADS"] = "3"
    result = subprocess.run(
        [sys.executable, "-c", "from app import rag; print(rag.RAG_ONNX_THREADS)"],
        cwd=Path(__file__).parents[1], env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "3"


# skip embed-dependent tests if fastembed/sqlite-vec/model not installed (RAG optional dep)
def _rag_available() -> bool:
    try:
        import fastembed  # noqa: F401
        import sqlite_vec  # noqa: F401
    except Exception:
        return False
    try:
        rag._get_embedder()
        return True
    except Exception:
        return False


def needs_model(test):
    """Пометить тест как требующий эмбеддера и пропустить, если его нет.

    Маркер нужен ОТДЕЛЬНО от `skipif`: по нему `tests/conftest.py` печатает в конце прогона
    громкую строку. Эмбеддинг заглушками не моделируется, а молчаливый `skipped` даёт ту же
    зелёную сводку, что и пройденный. В worktree воркера без `orchestra[rag]` так скипается
    ВЕСЬ реальный слой RAG — и правка индексации выглядит проверенной, не будучи ею.
    """
    test = pytest.mark.needs_model(test)
    return pytest.mark.skipif(
        not _rag_available(),
        reason="нет эмбеддера: /home/kesha/orchestra/.venv/bin/python -m pytest tests/test_rag.py",
    )(test)


# ---------------------------------------------------------------- T1: chunkers (pure, no model)

MD_SAMPLE = """# Physics

Intro paragraph about physics that is reasonably long so the section is not merged away too early.

## Thermodynamics

- Carnot limit sets max efficiency
- Heat pump COP 300-500 percent

### Entropy

Second law says entropy never decreases in isolated system, a fundamental limit on engines.

## Electricity

Voltage current power, water analogy pressure flow.
"""


def test_markdown_chunks_start_clean():
    chunks = rag._chunk_markdown(MD_SAMPLE)
    assert chunks
    for c in chunks:
        first = c.lstrip()[0]
        assert first in "#-*•>" or first.isupper() or first.isdigit(), f"bad start: {c[:40]!r}"


def test_markdown_keeps_heading_context():
    chunks = rag._chunk_markdown(MD_SAMPLE)
    joined = "\n---\n".join(chunks)
    assert "Thermodynamics" in joined
    assert "Electricity" in joined


def test_headingless_falls_back_to_paragraphs():
    text = "First paragraph here.\n\nSecond paragraph totally separate.\n\nThird one."
    chunks = rag._chunk_markdown(text)
    assert chunks
    assert not any(c.startswith("#") for c in chunks)


def test_empty_content_returns_empty():
    assert rag._chunk_file("x.md", "") == []
    assert rag._chunk_file("x.md", "   \n\n  ") == []
    assert rag._chunk_markdown("") == []


def test_single_paragraph_one_chunk():
    chunks = rag._chunk_file("note.md", "just one paragraph no breaks")
    assert chunks == ["just one paragraph no breaks"]


def test_oversized_word_is_capped():
    blob = "x" * 5000
    chunks = rag._chunk_file("note.md", blob)
    assert all(len(c) <= rag.CHUNK_SIZE for c in chunks)


def test_dispatcher_by_extension():
    assert rag._chunk_file("a.md", MD_SAMPLE)
    # unknown ext → char-window fallback, no crash
    assert rag._chunk_file("a.unknown", "some text content here") == ["some text content here"]


# ---------------------------------------------------------------- T2: log classification (pure)

def test_classify_agent_msg():
    kind, author = rag._classify_log("user_message", "[from:worker-x] DONE #7: fixed the bug")
    assert kind == "agent_msg"
    assert author == "worker-x"


def test_classify_human_user_msg():
    kind, author = rag._classify_log("user_message", "обычное сообщение от человека")
    assert kind == "user_msg"
    assert author is None


def test_classify_agent_text():
    kind, author = rag._classify_log("text", "Let me check the logs")
    assert kind == "text"
    assert author is None


def test_classify_from_with_dashes_and_digits():
    kind, author = rag._classify_log("user_message", "[from:seedon-orchestrator-2] research approved")
    assert kind == "agent_msg"
    assert author == "seedon-orchestrator-2"


def test_log_signal_filter_by_kind():
    long_text = "x" * 300
    short_text = "ok"
    # agent_msg: no length threshold (signal even if short)
    assert rag.RagMemory._log_is_signal("agent_msg", short_text) is True
    # user_msg/text: below MIN_LOG_LEN → noise
    assert rag.RagMemory._log_is_signal("user_msg", short_text) is False
    assert rag.RagMemory._log_is_signal("text", short_text) is False
    assert rag.RagMemory._log_is_signal("user_msg", long_text) is True
    # empty agent_msg → not signal
    assert rag.RagMemory._log_is_signal("agent_msg", "   ") is False


# ---------------------------------------------------------------- T3: file_change_target (pure)

def test_file_change_target_filters(tmp_path):
    root = tmp_path
    assert rag.file_change_target(str(root / "a.md"), root) == "a.md"
    assert rag.file_change_target(str(root / "sub" / "b.md"), root) == "sub/b.md"
    # wrong extension → None
    assert rag.file_change_target(str(root / "data.json"), root) is None
    assert rag.file_change_target(str(root / "img.png"), root) is None
    # excluded dir → None
    assert rag.file_change_target(str(root / ".claude" / "x.md"), root) is None
    assert rag.file_change_target(str(root / ".git" / "y.md"), root) is None
    assert rag.file_change_target(str(root / "worktrees" / "z.md"), root) is None
    # codex-review blacklist → None
    assert rag.file_change_target(str(root / "codex-review-plan.md"), root) is None


# ---------------------------------------------------------------- RRF (pure)

def test_rrf_namespaced_keys_no_collision():
    # a file chunk_id and a log chunk_id can be equal ints — must not merge
    fused = rag.RagMemory._rrf([("file", 5)], [("log", 5)])
    assert ("file", 5) in fused and ("log", 5) in fused
    assert len(fused) == 2


def test_rrf_orders_by_score():
    # item appearing in both lists ranks above item in one list
    fused = rag.RagMemory._rrf([("file", 1), ("file", 2)], [("file", 1)])
    assert fused[0] == ("file", 1)


# ============================================================ embed-dependent (T2/T3 index/search)

@pytest.fixture
def mem(tmp_path):
    return rag.RagMemory(path=tmp_path / "vec.db")


def _file_counts(m, project=None):
    where = f" WHERE project='{project}'" if project else ""
    return {
        "files": m.conn.execute(f"SELECT COUNT(*) FROM files{where}").fetchone()[0],
        "vec": m.conn.execute(f"SELECT COUNT(*) FROM vec_files{where}").fetchone()[0],
        "chunks": m.conn.execute("SELECT COUNT(*) FROM file_chunks").fetchone()[0],
        "fts": m.conn.execute("SELECT COUNT(*) FROM fts_files").fetchone()[0],
    }


@needs_model
def test_index_file_creates_rows(mem):
    n = mem.index_file("/proj/a", "docs/dump.md", MD_SAMPLE)
    assert n > 0
    c = _file_counts(mem)
    assert c["files"] == 1
    assert c["vec"] == c["chunks"] == c["fts"] == n


@needs_model
def test_index_file_idempotent_same_content(mem):
    mem.index_file("/proj/a", "a.md", MD_SAMPLE)
    fid1 = mem.conn.execute("SELECT file_id FROM files WHERE path='a.md'").fetchone()[0]
    n2 = mem.index_file("/proj/a", "a.md", MD_SAMPLE)  # same content
    assert n2 == 0
    fid2 = mem.conn.execute("SELECT file_id FROM files WHERE path='a.md'").fetchone()[0]
    assert fid1 == fid2  # stable file_id


@needs_model
def test_reindex_changed_content_replaces(mem):
    mem.index_file("/proj/a", "a.md", "# Old\n\nold content paragraph here that is long enough.")
    fid = mem.conn.execute("SELECT file_id FROM files WHERE path='a.md'").fetchone()[0]
    old = mem.conn.execute("SELECT text FROM file_chunks WHERE file_id=?", (fid,)).fetchone()[0]
    mem.index_file("/proj/a", "a.md", MD_SAMPLE)
    assert mem.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    new_texts = [r[0] for r in mem.conn.execute(
        "SELECT text FROM file_chunks WHERE file_id=?", (fid,)).fetchall()]
    assert old not in new_texts
    assert any("Thermodynamics" in t for t in new_texts)


@needs_model
def test_delete_file_removes_all(mem):
    mem.index_file("/proj/a", "a.md", MD_SAMPLE)
    assert mem.delete_file("/proj/a", "a.md") is True
    assert _file_counts(mem) == {"files": 0, "vec": 0, "chunks": 0, "fts": 0}
    assert mem.delete_file("/proj/a", "a.md") is False


@needs_model
def test_same_path_different_projects_coexist(mem):
    # same rel path in two projects → two independent files (UNIQUE(project,path))
    mem.index_file("/proj/a", "README.md", "# A\n\nProject A readme content here that is long.")
    mem.index_file("/proj/b", "README.md", "# B\n\nProject B readme content here that is long.")
    assert mem.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 2


# ---------------------------------------------------- log index + search

RU_MD = """# Здоровье

## Витамин D

Дефицит витамина D вызывает усталость и снижение иммунитета. Норма 30-50 нг/мл в крови.

## Сон

Глубокий сон важен для восстановления, фазы по 90 минут за ночь.
"""


@needs_model
def test_index_log_creates_rows(mem):
    n = mem.index_log("/proj/a", 42, "agent_msg", "worker-x",
                      "[from:worker-x] DONE #7: fixed the biome shift bug via WorldCover mosaic")
    assert n > 0
    row = mem.conn.execute("SELECT kind, author FROM log_chunks WHERE log_id=42").fetchone()
    assert row["kind"] == "agent_msg"
    assert row["author"] == "worker-x"
    assert mem.conn.execute("SELECT COUNT(*) FROM logs_indexed WHERE log_id=42").fetchone()[0] == 1


@needs_model
def test_index_log_dedup(mem):
    mem.index_log("/proj/a", 1, "text", None, "some agent report about the thing " * 10)
    n2 = mem.index_log("/proj/a", 1, "text", None, "some agent report about the thing " * 10)
    assert n2 == 0  # already indexed by log_id


@needs_model
def test_search_project_isolation(mem):
    # two projects, same topic → search('/proj/a') must NOT leak /proj/b
    mem.index_file("/proj/a", "health.md", RU_MD)
    mem.index_file("/proj/b", "health.md", RU_MD)
    res = mem.search("/proj/a", "норма витамина D в крови", limit=10)
    assert res
    assert all(r["project"] == "/proj/a" for r in res), f"leak: {[r['project'] for r in res]}"


@needs_model
def test_search_cross_project_optin(mem):
    mem.index_file("/proj/a", "health.md", RU_MD)
    mem.index_file("/proj/b", "health.md", RU_MD)
    res = mem.search("/proj/a", "норма витамина D", limit=10, cross_project=True)
    projects = {r["project"] for r in res}
    assert "/proj/b" in projects  # cross_project=True surfaces other projects


@needs_model
def test_search_file_and_log_sources(mem):
    mem.index_file("/proj/a", "health.md", RU_MD)
    mem.index_log("/proj/a", 100, "agent_msg", "doc-writer",
                  "[from:doc-writer] DONE: витамин D дефицит вызывает усталость, норма в крови важна " * 3)
    res = mem.search("/proj/a", "витамин D норма усталость", limit=10)
    sources = {r["source"] for r in res}
    assert "file" in sources
    # log result carries kind+author attribution
    log_hits = [r for r in res if r["source"] == "log"]
    if log_hits:
        assert log_hits[0]["kind"] == "agent_msg"
        assert log_hits[0]["author"] == "doc-writer"


@needs_model
def test_search_kinds_filter(mem):
    mem.index_log("/proj/a", 1, "agent_msg", "w1", "[from:w1] витамин D отчёт готов норма важна " * 5)
    mem.index_log("/proj/a", 2, "text", None, "витамин D дефицит усталость иммунитет норма крови " * 5)
    res = mem.search("/proj/a", "витамин D норма", limit=10, kinds=("agent_msg",))
    log_hits = [r for r in res if r["source"] == "log"]
    assert log_hits
    assert all(r["kind"] == "agent_msg" for r in log_hits)


@needs_model
def test_empty_query_returns_empty(mem):
    mem.index_file("/proj/a", "a.md", MD_SAMPLE)
    assert mem.search("/proj/a", "") == []
    assert mem.search("/proj/a", "   ") == []


# ---------------------------------------------------- backfill_files

def _build_knowledge(root: Path):
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "dump.md").write_text(MD_SAMPLE, encoding="utf-8")
    (root / "README.md").write_text("# Readme\n\nproject description here long enough", encoding="utf-8")
    (root / ".claude").mkdir()
    (root / ".claude" / "SKILL.md").write_text("# Tool\n\nskipped", encoding="utf-8")
    (root / "codex-review-plan.md").write_text("# Debate\n\nnoise skipped", encoding="utf-8")
    (root / "data.json").write_text('{"x": 1}', encoding="utf-8")


@needs_model
def test_backfill_indexes_md_only(mem, tmp_path):
    kb = tmp_path / "kb"
    _build_knowledge(kb)
    n = mem.backfill_files("/proj/a", kb)
    assert n == 2  # docs/dump.md + README.md
    paths = {r[0] for r in mem.conn.execute("SELECT path FROM files").fetchall()}
    assert paths == {"docs/dump.md", "README.md"}
    assert not any(".claude" in p for p in paths)
    assert not any("codex-review" in p for p in paths)
    assert not any(p.endswith(".json") for p in paths)


@needs_model
def test_backfill_second_run_no_changes(mem, tmp_path):
    kb = tmp_path / "kb"
    _build_knowledge(kb)
    mem.backfill_files("/proj/a", kb)
    assert mem.backfill_files("/proj/a", kb) == 0


@needs_model
def test_backfill_prunes_deleted(mem, tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    f = kb / "temp.md"
    f.write_text("# Temp\n\nwill be deleted later on disk here", encoding="utf-8")
    mem.backfill_files("/proj/a", kb)
    assert mem.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    f.unlink()
    mem.backfill_files("/proj/a", kb)
    assert mem.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0


# ---------------------------------------------------- backfill_logs (from orchestra.db)

def _make_orchestra_db(path: Path, sessions: list[tuple], logs: list[tuple]) -> None:
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, scope TEXT);
        CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
                           ts TEXT, type TEXT, content TEXT);
    """)
    con.executemany("INSERT INTO sessions(id, name, scope) VALUES(?,?,?)", sessions)
    con.executemany("INSERT INTO logs(session_id, ts, type, content) VALUES(?,?,?,?)", logs)
    con.commit()
    con.close()


@needs_model
def test_backfill_logs_type_and_length_filter(mem, tmp_path):
    odb = tmp_path / "orchestra.db"
    long_text = "агент проанализировал root cause и починил баг через мозаику тайлов. " * 5
    long_user = "юзер даёт развёрнутую инструкцию по задаче с деталями и требованиями. " * 5
    _make_orchestra_db(odb,
        sessions=[("s1", "w1", "/proj/a"), ("s2", "w2", "/proj/b")],
        logs=[
            ("s1", "t", "text", long_text),                              # indexed (text, long)
            ("s1", "t", "user_message", "[from:w2] DONE отчёт готов"),   # indexed (agent_msg, short OK)
            ("s1", "t", "user_message", long_user),                      # indexed (user_msg, long)
            ("s1", "t", "user_message", "ок"),                           # SKIP (user_msg, short)
            ("s1", "t", "text", "Проверю."),                             # SKIP (text, short)
            ("s1", "t", "tool_result", "x" * 5000),                      # SKIP (tool_result type)
            ("s1", "t", "status", "running"),                            # SKIP (status type)
            ("s2", "t", "text", long_text),                             # different project — not indexed for /proj/a
        ])
    n = mem.backfill_logs("/proj/a", odb)
    assert n == 3  # long text + agent_msg + long user_msg
    kinds = [r[0] for r in mem.conn.execute("SELECT kind FROM log_chunks GROUP BY log_id").fetchall()]
    assert sorted(kinds) == ["agent_msg", "text", "user_msg"]
    # /proj/b log not pulled into /proj/a
    assert mem.conn.execute("SELECT COUNT(*) FROM logs_indexed WHERE project='/proj/b'").fetchone()[0] == 0


@needs_model
def test_backfill_logs_session_name_filter(mem, tmp_path):
    odb = tmp_path / "orchestra.db"
    long_a = "агент A проанализировал root cause и починил баг через мозаику тайлов подробно. " * 5
    long_b = "агент B сделал совсем другую задачу про рендеринг карты мира и террейн. " * 5
    _make_orchestra_db(odb,
        sessions=[("s1", "worker-a", "/proj/a"), ("s2", "worker-b", "/proj/a")],
        logs=[("s1", "t", "text", long_a), ("s2", "t", "text", long_b)])
    # only worker-a's session → 1 log, worker-b untouched
    n = mem.backfill_logs("/proj/a", odb, session_name="worker-a")
    assert n == 1
    # the indexed log belongs to s1 (worker-a): its content is long_a
    txt = mem.conn.execute("SELECT text FROM log_chunks LIMIT 1").fetchone()[0]
    assert "агент A" in txt
    # worker-b's log still not indexed
    assert mem.conn.execute("SELECT COUNT(*) FROM logs_indexed").fetchone()[0] == 1


@needs_model
def test_backfill_logs_dedup_second_run(mem, tmp_path):
    odb = tmp_path / "orchestra.db"
    long_text = "агент проанализировал проблему и починил через мозаику тайлов подробно. " * 5
    _make_orchestra_db(odb, sessions=[("s1", "w1", "/proj/a")],
                       logs=[("s1", "t", "text", long_text)])
    assert mem.backfill_logs("/proj/a", odb) == 1
    assert mem.backfill_logs("/proj/a", odb) == 0  # dedup via logs_indexed


# ---------------------------------------------------- concurrency: RO conn (embed-dependent)

@needs_model
def test_readonly_conn_sees_writes_and_searches(tmp_path):
    vec = tmp_path / "vec.db"
    w = rag.RagMemory(path=vec)
    w.index_file("/proj/a", "health.md", RU_MD)
    ro = rag.RagMemory(path=vec, readonly=True)
    res = ro.search("/proj/a", "витамин D норма в крови", limit=5)
    assert any(r["source"] == "file" and r["path"] == "health.md" for r in res)


@needs_model
def test_readonly_conn_cannot_write(tmp_path):
    vec = tmp_path / "vec.db"
    rag.RagMemory(path=vec)  # create schema
    ro = rag.RagMemory(path=vec, readonly=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.index_file("/proj/a", "x.md", RU_MD)


def test_run_routes_search_to_read_executor(monkeypatch):
    """run() routes search → read-executor, index → write-executor (pure, no model)."""
    calls = []
    monkeypatch.setattr(rag, "_executor", "WRITE")
    monkeypatch.setattr(rag, "_read_executor", "READ")

    async def fake_run_in_executor(ex, fn):
        calls.append(ex)
        return None

    class FakeLoop:
        run_in_executor = staticmethod(fake_run_in_executor)

    import asyncio
    asyncio.run(rag.run(FakeLoop(), "search", "/proj/a", "q"))
    asyncio.run(rag.run(FakeLoop(), "index_file", "/proj/a", "x.md", "content"))
    assert calls == ["READ", "WRITE"]


# ------------------------------------------- #16: порядок шагов, срезы, фантомы в выдаче

def _md(root: Path, name: str, body: str, mtime: float | None = None) -> Path:
    p = root / name
    p.write_text(f"# {name}\n\n{body} " * 4, encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))
    return p


@needs_model
def test_prune_runs_before_embedding_so_a_cut_short_pass_still_drops_phantoms(mem, tmp_path):
    """Фантом должен исчезать в прогоне, который НЕ дошёл до конца корпуса.
    Пока prune стоял последней строкой, при обрыве он не отрабатывал никогда."""
    kb = tmp_path / "kb"
    kb.mkdir()
    gone = _md(kb, "gone.md", "будет удалён с диска")
    mem.backfill_files("/proj/a", kb)
    assert mem.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    gone.unlink()
    for i in range(4):
        _md(kb, f"new{i}.md", f"новый файл номер {i} с содержимым")

    indexed = mem.backfill_files("/proj/a", kb, limit=1)

    assert indexed == 1, "срез обязан остановиться после лимита"
    paths = {r[0] for r in mem.conn.execute("SELECT path FROM files")}
    assert "gone.md" not in paths, "prune не отработал в оборванном прогоне"


@needs_model
def test_interrupted_pass_resumes_instead_of_restarting(mem, tmp_path):
    """Критерий приёмки E: прогон, прерванный на середине, продолжается с места обрыва."""
    kb = tmp_path / "kb"
    kb.mkdir()
    for i in range(5):
        _md(kb, f"f{i}.md", f"содержимое файла номер {i} для проверки продолжения")

    first = mem.backfill_files("/proj/a", kb, limit=2)
    after_first = {r[0] for r in mem.conn.execute("SELECT path FROM files")}
    second = mem.backfill_files("/proj/a", kb, limit=2)
    after_second = {r[0] for r in mem.conn.execute("SELECT path FROM files")}

    assert first == 2 and second == 2
    assert after_first < after_second, "второй срез начал с нуля вместо продолжения"
    assert len(after_second) == 4
    assert mem.backfill_files("/proj/a", kb, limit=2) == 1  # остался ровно один
    assert mem.backfill_files("/proj/a", kb, limit=2) == 0  # и больше работы нет


@needs_model
def test_freshest_file_is_indexed_first(mem, tmp_path):
    """C: ради только что смерженной правки поиск и зовут — она идёт вперёд хвоста."""
    kb = tmp_path / "kb"
    kb.mkdir()
    _md(kb, "ancient.md", "древний файл из хвоста корпуса", mtime=1_600_000_000)
    _md(kb, "old.md", "просто старый файл корпуса", mtime=1_700_000_000)
    fresh = _md(kb, "fresh.md", "только что смерженная правка", mtime=1_800_000_000)

    mem.backfill_files("/proj/a", kb, limit=1)

    assert {r[0] for r in mem.conn.execute("SELECT path FROM files")} == {fresh.name}


@needs_model
def test_search_never_returns_a_file_deleted_from_disk(mem, tmp_path):
    """B: удалённый файл не выдаётся как текущий, даже пока prune до него не дошёл."""
    kb = tmp_path / "kb"
    kb.mkdir()
    doomed = _md(kb, "doomed.md", "уникальный маркер квазар для поиска")
    mem.backfill_files(str(kb), kb)
    assert mem.search(str(kb), "квазар", limit=5), "маркер должен находиться, пока файл на диске"

    doomed.unlink()  # индекс ещё НЕ перестроен — строка в files осталась

    assert mem.search(str(kb), "квазар", limit=5) == []


@needs_model
def test_backfill_logs_limit_bounds_one_pass(mem, tmp_path):
    """E для логового слоя: без LIMIT это fetchall по всей истории scope."""
    odb = tmp_path / "orchestra.db"
    long_a = "агент разобрал причину и починил через перестановку шагов бэкфилла подробно. " * 5
    _make_orchestra_db(odb, sessions=[("s1", "w1", "/proj/a")],
                       logs=[("s1", "t", "text", long_a + str(i)) for i in range(4)])

    assert mem.backfill_logs("/proj/a", odb, batch_size=2) == 2
    assert mem.backfill_logs("/proj/a", odb, batch_size=2) == 2
    assert mem.backfill_logs("/proj/a", odb, batch_size=2) == 0


@needs_model
def test_pending_files_counts_missing_and_stale(mem, tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    a = _md(kb, "a.md", "первый файл корпуса")
    _md(kb, "b.md", "второй файл корпуса")
    assert mem.pending_files("/proj/a", kb) == 2

    mem.backfill_files("/proj/a", kb)
    assert mem.pending_files("/proj/a", kb) == 0

    a.write_text("# a.md\n\nсодержимое поменялось целиком", encoding="utf-8")
    assert mem.pending_files("/proj/a", kb) == 1

    (kb / "empty.md").write_text("", encoding="utf-8")
    assert mem.pending_files("/proj/a", kb) == 1, "пустой файл не может висеть в долге вечно"


@needs_model
def test_backfill_files_stops_inside_the_slice_on_deadline(mem, tmp_path):
    """Бюджет обязан рвать слой ВНУТРИ. Пока он проверялся только между срезами, один срез
    длиной 27 минут съедал прогон целиком, и за прогон индексировалось ровно _FILE_SLICE
    файлов — при долге в сотни файлов это «не догонит никогда» (#44)."""
    kb = tmp_path / "kb"
    kb.mkdir()
    for i in range(5):
        (kb / f"doc{i}.md").write_text(f"# Doc {i}\n\nсодержимое документа номер {i} подлиннее",
                                       encoding="utf-8")
    # дедлайн уже истёк: слой обязан сделать РОВНО один файл — не ноль (иначе долг не движется)
    # и не все пять (иначе бюджет ничего не ограничивает)
    n = mem.backfill_files("/proj/a", kb, deadline=time.monotonic() - 1)
    assert n == 1
    assert mem.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
    # остаток догоняется следующим вызовом, с места обрыва
    assert mem.backfill_files("/proj/a", kb) == 4


@needs_model
def test_backfill_logs_stops_inside_the_slice_on_deadline(mem, tmp_path):
    odb = tmp_path / "orchestra.db"
    long_text = "агент проанализировал root cause и починил баг через мозаику тайлов. " * 5
    _make_orchestra_db(odb,
        sessions=[("s1", "w1", "/proj/a")],
        logs=[("s1", "t", "text", long_text + str(i)) for i in range(4)])
    n = mem.backfill_logs("/proj/a", odb, deadline=time.monotonic() - 1)
    assert n == 1
    assert mem.backfill_logs("/proj/a", odb) == 3


@needs_model
def test_backfill_skips_git_ignored_files(mem, tmp_path):
    """Игнорируемое git'ом — рабочий мусор, а не знание проекта.

    Замер #63: 459 из 490 файлов в долге были корпусом чужого бенчмарка под `.gitignore`,
    и именно они делали долг несходящимся.
    """
    kb = tmp_path / "repo"
    kb.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=kb, check=True)
    (kb / ".gitignore").write_text("data/\n", encoding="utf-8")
    (kb / "README.md").write_text("# Readme\n\nреальный документ проекта подлиннее", encoding="utf-8")
    (kb / "data").mkdir()
    (kb / "data" / "corpus.md").write_text("# Corpus\n\nчужой бенчмарк, индексу не нужен",
                                           encoding="utf-8")

    assert mem.backfill_files("/proj/a", kb) == 1
    paths = {r[0] for r in mem.conn.execute("SELECT path FROM files").fetchall()}
    assert paths == {"README.md"}


@needs_model
def test_walk_indexes_everything_when_git_is_unavailable(mem, tmp_path, monkeypatch):
    """Сбой git не имеет права молча сужать корпус: пустая память хуже шумной."""
    kb = tmp_path / "notrepo"          # не git-репозиторий вовсе → rc=128
    kb.mkdir()
    (kb / "a.md").write_text("# A\n\nдокумент один достаточной длины", encoding="utf-8")
    (kb / "b.md").write_text("# B\n\nдокумент два достаточной длины", encoding="utf-8")
    assert len(mem._walk_files(kb)) == 2

    def boom(*a, **k):
        raise OSError("git отсутствует")

    monkeypatch.setattr(rag.subprocess, "run", boom)
    assert len(mem._walk_files(kb)) == 2


@needs_model
def test_reindex_reuses_embeddings_of_unchanged_chunks(mem, monkeypatch):
    """Переиндексация считает эмбеддинги только для НОВЫХ по тексту чанков.

    Замер #73: `CHANGELOG.md` — 352 чанка × 2.2 с ≈ 775 с на переиндексацию при бюджете
    прохода 300 с, а меняется в нём 0.6–11.2 % текстов. Ключ переиспользования — текст чанка,
    не позиция: блок дописывается СВЕРХУ, у чанков меняется индекс, а не содержимое.
    """
    # Секции длиннее MD_MIN_MERGE: короткие чанкер сливает с соседними, и тогда при дописывании
    # меняется ТЕКСТ соседа, а не только его позиция. На реальном CHANGELOG секции крупные —
    # оттуда и 0.6–11.2 % новых текстов вместо 100 %.
    head = "# Раздел А\n\n" + "первый раздел с подробным описанием и деталями. " * 12 + "\n\n"
    tail = "## Раздел Б\n\n" + "второй раздел про совершенно другое, тоже подробно. " * 12 + "\n\n"
    mem.index_file("/proj/a", "log.md", head + tail)
    before = {r[0] for r in mem.conn.execute("SELECT text FROM file_chunks").fetchall()}

    embedded: list[list[str]] = []
    original = mem._embed
    monkeypatch.setattr(mem, "_embed", lambda texts, **kw: embedded.append(list(texts)) or original(texts, **kw))

    added = "# Новое\n\n" + "свежая запись, которой в прошлой версии файла не было. " * 12 + "\n\n"
    n = mem.index_file("/proj/a", "log.md", added + head + tail)

    assert n == len(before) + 1, "новый блок сверху добавляет чанк, старые сохраняются"
    assert len(embedded) == 1
    assert len(embedded[0]) == 1, f"переэмбеддить надо только новый чанк, а не {len(embedded[0])}"
    assert "свежая запись" in embedded[0][0]
    # старые тексты на месте, только с новыми chunk_id
    after = {r[0] for r in mem.conn.execute("SELECT text FROM file_chunks").fetchall()}
    assert before <= after


@needs_model
def test_reused_vectors_are_the_same_bytes(mem):
    """Переложенный вектор обязан быть тем же, иначе поиск поедет незаметно."""
    body = "# Тема\n\n" + "текст раздела достаточной длины для самостоятельного чанка. " * 12 + "\n\n"
    mem.index_file("/proj/a", "doc.md", body)
    old = mem.conn.execute("SELECT c.text, v.embedding FROM file_chunks c "
                           "JOIN vec_files v USING(chunk_id)").fetchall()
    mem.index_file("/proj/a", "doc.md",
                   body + "## Хвост\n\n" + "дописанный раздел с новым текстом внутри. " * 12 + "\n")
    new = {r["text"]: r["embedding"] for r in mem.conn.execute(
        "SELECT c.text, v.embedding FROM file_chunks c JOIN vec_files v USING(chunk_id)").fetchall()}
    for row in old:
        assert new[row["text"]] == row["embedding"]
