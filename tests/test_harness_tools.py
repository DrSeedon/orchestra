"""#367: red tests for harness built-in tools + loop round guard.

Each test_tN_* is committed FAILING (red) before its ticket's implementation and must turn
green when the ticket lands. Failures are behavioural (wrong output), never ImportError.
Run: /home/kesha/orchestra/.venv/bin/python -m pytest tests/test_harness_tools.py -q
"""
import asyncio
import os
import stat
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.harness import tools  # noqa: E402

CWD_ROOT = Path(__file__).resolve().parents[1]      # repo root for repo-tree perf probe


@pytest.fixture()
def stand(tmp_path):
    """Fixture tree mirroring the audit stand."""
    (tmp_path / "app" / "sub").mkdir(parents=True)
    (tmp_path / "app" / "models.py").write_text(
        "line one nemotron-3-super here\nnothing\ninkling word\nlaguna here\nnorth-mini here\n")
    (tmp_path / "app" / "other.py").write_text("nemotron-3 in other file\n")
    (tmp_path / "app" / "sub" / "deep.py").write_text("deep laguna match\n")
    (tmp_path / ".hidden").write_text("hidden laguna match\n")
    return tmp_path


def grep(pattern, cwd, **kw):
    return tools.grep(pattern, str(cwd), **kw)


# ── T1 — grep: single python engine ──────────────────────────────────────────

def test_t1_grep_alternation_finds_matches(stand):
    # ox-probe defect: BRE fallback turned | into a literal → "(no matches)"
    out = grep("nemotron-3|inkling|laguna|north-mini", stand)
    assert "(no matches)" != out.strip(), "alternation silently returned no matches"
    assert "app/models.py" in out and "inkling" in out


def test_t1_grep_glob_filter_restricts_files(stand):
    out = grep("laguna", stand, glob_filter="app/models.py")
    assert "app/models.py" in out
    assert ".hidden" not in out and "deep.py" not in out, "glob_filter ignored"


def test_t1_grep_invalid_regex_reports_error(stand):
    # re.error must be caught inside grep (not only by dispatch's blanket handler)
    for bad in ["(", "*x"]:
        out = grep(bad, stand)
        assert out.startswith("[grep error]"), f"invalid regex {bad!r} masked as result: {out[:80]}"


def test_t1_grep_dash_pattern_treated_as_literal(stand):
    # "-x" is a VALID literal pattern under the python engine — must search, never crash
    (stand / "dashfile.txt").write_text("value -x here\n")
    out = grep("-x", stand)
    assert "grep error" not in out and "dashfile.txt" in out, f"-x mishandled: {out[:120]!r}"


def test_t1_grep_non_utf8_match_not_silent(stand):
    (stand / "latin.txt").write_bytes(b"name caf\xe9 laguna\n")
    out = grep("laguna", stand)
    assert "latin.txt" in out or "skipped" in out.lower(), \
        f"match in non-UTF-8 file vanished silently: {out!r}"


def test_t1_grep_context_lines(stand):
    out = grep("inkling", stand, context=1)
    lines = [l for l in out.splitlines() if l.strip()]
    assert any("nothing" in l for l in lines), "context=1 did not include neighbouring line"
    assert any("inkling" in l for l in lines)


def test_t1_grep_limit_in_action(stand):
    schemas = {s["function"]["name"]: s["function"] for s in tools.tool_schemas()}
    assert "limit" in schemas["grep"]["parameters"]["properties"], "grep limit not in schema"
    out = grep("laguna", stand, glob_filter="app/*.py", limit=1)
    body = [l for l in out.splitlines() if "laguna" in l]
    assert len(body) <= 1, "limit param did not restrict output"
    assert "app/sub/deep.py" not in out


def test_t1_grep_perf_repo_tree():
    t0 = time.monotonic()
    out = grep("MAX_TOOL_ROUNDS", CWD_ROOT)
    dt = time.monotonic() - t0
    assert dt < 20.0, f"python-engine grep over repo took {dt:.1f}s (>20s)"
    assert "loop.py" in out


# ── T2 — read: honest ────────────────────────────────────────────────────────

def test_t2_read_multibyte_split_is_not_binary(tmp_path):
    p = tmp_path / "split.md"
    p.write_bytes(b"a" * 262_143 + "х".encode())     # byte cap lands mid-character
    out = tools.read(str(p), str(tmp_path), limit=1)
    assert "[binary file" not in out, f"valid UTF-8 declared binary: {out[:80]}"


def test_t2_read_truncated_marker(tmp_path):
    p = tmp_path / "big.txt"
    total = tools.READ_MAX_BYTES + 4096
    p.write_bytes(b"x" * total)
    out = tools.read(str(p), str(tmp_path))
    assert "truncat" in out.lower()
    assert str(total) in out, f"marker must state the full file size ({total} bytes)"


def test_t2_read_offset_is_display_line_number(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("l1\nl2\nl3\nl4\nl5\n")
    out = tools.read(str(p), str(tmp_path), offset=5)
    assert out.splitlines()[0].startswith("5\t"), f"offset=5 must start at displayed line 5, got {out!r}"


def test_t2_read_offset_past_eof_explicit(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("l1\nl2\n")
    out = tools.read(str(p), str(tmp_path), offset=100)
    assert "past EOF" in out or "has 2 lines" in out, f"misleading '(empty)': {out!r}"


def test_t2_read_rejects_fifo_immediately(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    import threading
    res = {}
    def call():
        res["out"] = tools.read(str(tmp_path / "pipe"), str(tmp_path))
    th = threading.Thread(target=call, daemon=True)
    th.start()
    th.join(timeout=1.0)
    if th.is_alive():
        assert False, "read blocked on FIFO (>1s) instead of erroring immediately"
    out = res["out"]
    assert "regular file" in out or "read error" in out


def test_t2_read_does_not_load_whole_file(tmp_path):
    import tracemalloc
    p = tmp_path / "huge.bin"
    size = 64 * 1024 * 1024
    with open(p, "wb") as f:
        f.seek(size - 1)
        f.write(b"\0")                                # sparse 64 MiB file
    tracemalloc.start()
    tools.read(str(p), str(tmp_path), limit=1)
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 4 * 1024 * 1024, f"read() loaded the whole file: peak {peak/1e6:.0f} MB"


# ── T3 — write/edit: mode + feedback ─────────────────────────────────────────

def test_t3_edit_preserves_mode(tmp_path):
    p = tmp_path / "t.sh"
    p.write_text("#!/bin/sh\nx=1\n")
    os.chmod(p, 0o755)
    tools.edit(str(p), "x=1", "x=2", str(tmp_path))
    assert stat.S_IMODE(p.stat().st_mode) == 0o755, "edit clobbered file mode to 0600"


def test_t3_new_file_mode_0644(tmp_path):
    p = tmp_path / "new.txt"
    tools.write(str(p), "hi\n", str(tmp_path))
    assert stat.S_IMODE(p.stat().st_mode) == 0o644


def test_t3_write_preserves_mode(tmp_path):
    p = tmp_path / "t.sh"
    p.write_text("x=1\n")
    os.chmod(p, 0o755)
    tools.write(str(p), "x=2\n", str(tmp_path))
    assert stat.S_IMODE(p.stat().st_mode) == 0o755


def test_t3_umask_branch_022_gives_0644():
    from app.harness.tools import _umask_from_status, _read_umask_nondestructive
    # kernel prints %04o (octal) — measured live: `sh -c 'umask 077'` → "Umask: 0077"
    assert _umask_from_status("Umask:\t0022\n") == 0o022
    assert _umask_from_status("Umask:\t0077\n") == 0o077
    assert (0o666 & ~_umask_from_status("Umask:\t0022\n")) == 0o644
    assert (0o666 & ~_umask_from_status("Umask:\t0077\n")) == 0o600
    # live: NEW_FILE_MODE must equal 0o666 & ~the REAL process umask (dev shells differ
    # from the prod unit's 0022 — do NOT hardcode 0644 here)
    import os as _os
    real = _os.umask(0o022); _os.umask(real)
    assert tools.NEW_FILE_MODE == 0o666 & ~real
    assert _read_umask_nondestructive() == real


def test_t3_umask_branch_077_gives_0600(tmp_path, monkeypatch):
    import app.harness.tools as T
    monkeypatch.setattr(T, "NEW_FILE_MODE", 0o666 & ~0o077)   # what a UMask=0077 unit would yield
    p = tmp_path / "secret.txt"
    out = tools.write(str(p), "x\n", str(tmp_path))
    assert out.startswith("wrote")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600, "umask 077 must yield 0600 new-file mode"


def test_t3_edit_reports_replacement_count(tmp_path):
    p = tmp_path / "t.py"
    p.write_text("a = 1\nb = 1\nc = 1\n")
    out = tools.edit(str(p), "= 1", "= 2", str(tmp_path), replace_all=True)
    assert "replaced 3" in out, f"edit feedback does not state replacement count: {out!r}"


# ── T4 — glob schema ─────────────────────────────────────────────────────────

def test_t4_glob_schema_documents_recursion():
    schemas = {s["function"]["name"]: s["function"] for s in tools.tool_schemas()}
    desc = schemas["glob"]["description"]
    assert "**" in desc and "recursiv" in desc.lower()
    props = schemas["glob"]["parameters"]["properties"]
    assert "limit" in props, "glob limit not exposed in schema"


# ── T5 — dispatch off the event loop ─────────────────────────────────────────

def test_t5_dispatch_does_not_block_loop(monkeypatch):
    def slow_grep(*a, **k):
        time.sleep(1.0)
        return "(no matches)"
    monkeypatch.setattr(tools, "grep", slow_grep)

    async def probe():
        async def tick():
            t0 = time.monotonic(); await asyncio.sleep(0.01); return (time.monotonic() - t0) * 1000
        task = asyncio.ensure_future(tick())
        await asyncio.sleep(0.001)
        await tools.dispatch("grep", {"pattern": "x"}, "/tmp")
        return await task
    jitter_ms = asyncio.run(probe())
    assert jitter_ms < 300, f"sync tool blocked event loop: 10ms sleep took {jitter_ms:.0f}ms"


# ── T6 — round ceiling + wind-down ───────────────────────────────────────────

class _FakeLLM:
    """Always requests one more tool call — never ends voluntarily."""
    async def stream(self, history, tool_schemas, abort=None, effort=None):
        yield type("Ev", (), {"kind": "tool_call_done", "tool_id": "c1",
                              "tool_name": "read", "arguments": "{\"path\": \"f.txt\"}"})()


@pytest.mark.asyncio
async def test_t6_winddown_warnings_before_cap(tmp_path):
    from app.harness.loop import AgentLoop
    (tmp_path / "f.txt").write_text("data\n")
    schemas = [s for s in tools.tool_schemas() if s["function"]["name"] == "read"]
    loop = AgentLoop(_FakeLLM(), _NoMCP(), str(tmp_path), [], schemas, max_context=100_000,
                     max_rounds=12)
    warnings, during_turn_counts = [], []
    async for ev in loop.run("go"):
        if ev.type == "warning":
            warnings.append(ev.content)
            during_turn_counts.append(sum(
                1 for m in loop.history if str(m.get("content", "")).startswith("[round guard]")))
    assert len(warnings) == 2, f"expected wind-down warnings at remaining 10 and 3, got {warnings}"
    assert all("rounds remain" in w and "wrap up" in w.lower() for w in warnings)
    # each warning was backed by an injected history entry WHILE the turn was running
    assert all(c >= 1 for c in during_turn_counts), f"guard not in history mid-turn: {during_turn_counts}"
    assert loop.stop_reason == "max_turns" and loop.ok is False
    # B3: the guard must be turn-scoped — after run() returns, the shared session history
    # must NOT retain stale "N rounds remain" messages (standing false signal).
    leftover = [m for m in loop.history if "round guard" in str(m.get("content"))]
    assert not leftover, f"turn-scoped warnings leaked into persistent history: {leftover}"


def test_t6_max_rounds_value_100():
    # derived AFTER batching (#367 group D): 2× the highest observed demand (>50, censored);
    # defect-fixes measured to cut rounds up to 4x; worst case = 10% of daily quota per turn
    from app.harness import loop
    assert loop.MAX_TOOL_ROUNDS == 100


class _NoMCP:
    def has_tool(self, name): return False
    async def call(self, name, args): return "[noop]"


# ── T9 — _fit_context truncation visibility ─────────────────────────────────

@pytest.mark.asyncio
async def test_t9_truncation_is_visible(tmp_path):
    from app.harness.loop import AgentLoop

    class _BigHistoryLLM:
        async def stream(self, history, tool_schemas, abort=None, effort=None):
            yield type("Ev", (), {"kind": "text_delta", "text": "x" * 50_000})()
            yield type("Ev", (), {"kind": "final", "finish_reason": "stop",
                                  "usage": {}, "reasoning_details": []})()

    (tmp_path / "f.txt").write_text("data\n")
    schemas = [s for s in tools.tool_schemas() if s["function"]["name"] == "read"]
    loop = AgentLoop(_BigHistoryLLM(), _NoMCP(), str(tmp_path), [], schemas,
                     max_context=200_000)
    warns = []
    async for ev in loop.run("fill history"):
        if ev.type == "warning":
            warns.append(ev.content)

    # force truncation: stuff history far over the guard, then run one more turn
    for i in range(400):
        loop.history.append({"role": "user", "content": "padding %d %s" % (i, "y" * 5000)})
    n_before = len(loop.history)
    async for ev in loop.run("one more"):
        if ev.type == "warning":
            warns.append(ev.content)
    truncation_warns = [w for w in warns if "truncat" in w.lower() or "history" in w.lower()]
    assert truncation_warns, "_fit_context truncated history silently - no external event"
    assert len(loop.history) < n_before


# ── T7 — request economy: flag + prompt line ────────────────────────────────

def test_t7_body_sets_parallel_tool_calls():
    from app.harness.llm import OpenRouterClient
    c = OpenRouterClient("sk-test", "stealth/ox-alpha")
    body = c._build_body([{"role": "user", "content": "hi"}], [{"type": "function"}])
    assert body.get("parallel_tool_calls") is True
    bare = c._build_body([{"role": "user", "content": "hi"}], [])
    assert "parallel_tool_calls" not in bare


def test_t7_guidelines_mention_batching():
    from app.harness.prompts import _TOOL_GUIDELINES
    assert "independent" in _TOOL_GUIDELINES.lower()
    assert "one reply" in _TOOL_GUIDELINES.lower()
