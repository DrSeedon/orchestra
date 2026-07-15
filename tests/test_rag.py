"""Tests for app/rag.py — chunkers, log classification, index/dedup/delete, unified
search + project isolation, backfill. Ported from kesha-tg-bot/tests/test_rag_files.py,
adapted for Orchestra (project namespace, log layer, [from:] agent_msg classification).

Pure-logic tests (chunkers, _classify_log, _rrf, file_change_target) run WITHOUT the model.
Embed-dependent tests are marked `@pytest.mark.rag` and skip when fastembed/model unavailable.
"""

import sqlite3
from pathlib import Path

import pytest

from app import rag


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


needs_model = pytest.mark.skipif(not _rag_available(), reason="RAG deps/model not available")


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
