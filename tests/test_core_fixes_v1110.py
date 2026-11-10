"""Regression contracts for six harness/core defects found by the Astra and Argon probes."""

import json
import os
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

from app.harness.loop import AgentLoop, REREAD_HINT, _inspected_path
from app.harness.sessions import SessionStore


class _NoMCP:
    def has_tool(self, name):
        return False

    def display_name(self, name):
        return name

    async def call(self, name, args):
        return "[noop]"


class _ScriptLLM:
    """Plays a fixed list of tool calls, one per request, then answers in text."""

    def __init__(self, calls):
        self.calls = list(calls)
        self.requests = 0

    async def stream(self, messages, tools, abort=None):
        from app.harness.llm import LLMEvent

        self.requests += 1
        if tools and self.calls:
            name, args = self.calls.pop(0)
            yield LLMEvent("tool_call_done", tool_id=f"c{self.requests}", tool_name=name,
                           arguments=json.dumps(args))
            yield LLMEvent("final", finish_reason="tool_calls")
        else:
            yield LLMEvent("text_delta", text="done")
            yield LLMEvent("final", finish_reason="stop")


async def _run(tmp_path, calls, monkeypatch):
    from app.harness import tools as builtin

    served = []

    async def fake_dispatch(name, args, cwd):
        # A distinct result per call: only the re-read guard is under test here, not the
        # verbatim-repeat or same-result guards.
        served.append(name)
        if name in ("write", "edit"):
            return f"written #{len(served)}", True
        return f"line {len(served)}", False

    monkeypatch.setattr(builtin, "dispatch", fake_dispatch)
    schemas = [{"type": "function", "function": {"name": n, "parameters": {}}}
               for n in ("read", "bash", "write", "edit")]
    loop = AgentLoop(_ScriptLLM(calls), _NoMCP(), str(tmp_path),
                     [{"role": "system", "content": "s"}], schemas, max_context=100000)
    [event async for event in loop.run("go")]
    return loop, [m["content"] for m in loop.history if m["role"] == "tool"]


# ── 1. re-read guard keys on the full path and resets on write/edit ──

def test_inspected_path_is_normalized_full_path():
    assert _inspected_path("read", {"path": "pkg0/__init__.py"}, "/w") == "/w/pkg0/__init__.py"
    assert _inspected_path("read", {"path": "./pkg0/../pkg0/__init__.py"}, "/w") == "/w/pkg0/__init__.py"
    assert _inspected_path("bash", {"command": "cat /w/pkg1/__init__.py"}, "/w") == "/w/pkg1/__init__.py"
    assert _inspected_path("edit", {"path": "/w/a.py"}, "/w") == "/w/a.py"
    assert _inspected_path("bash", {"command": "ls"}, "/w") == ""


@pytest.mark.asyncio
async def test_same_basename_in_eight_packages_is_not_a_reread(tmp_path, monkeypatch):
    calls = [("read", {"path": f"pkg{i}/__init__.py"}) for i in range(8)]
    loop, results = await _run(tmp_path, calls, monkeypatch)

    assert len(results) == 8
    assert not any("[harness]" in result for result in results)
    assert loop._tools_off is False


@pytest.mark.asyncio
async def test_writing_a_file_resets_its_read_count(tmp_path, monkeypatch):
    read = ("read", {"path": "report.md"})
    calls = [read] * (REREAD_HINT - 1) + [("write", {"path": "report.md", "content": "x"})]
    calls += [read] * (REREAD_HINT - 1)
    loop, results = await _run(tmp_path, calls, monkeypatch)

    assert not any("Stop re-reading" in result or "switched off" in result for result in results)
    assert loop._tools_off is False


@pytest.mark.asyncio
async def test_real_rereads_of_one_file_are_still_stopped(tmp_path, monkeypatch):
    calls = [("read", {"path": "report.md"})] + [("read", {"path": "./report.md"})] * (REREAD_HINT - 1)
    _loop, results = await _run(tmp_path, calls, monkeypatch)

    assert "Stop re-reading" in results[REREAD_HINT - 1]


# ── 2. a torn JSONL tail is cut on disk, so the next append cannot glue to it ──

@pytest.mark.asyncio
async def test_truncated_tail_is_repaired_on_disk_before_the_next_append(tmp_path):
    store = SessionStore(str(tmp_path), "s1")
    await store.append({"role": "user", "content": "one"})
    await store.close()
    with open(store.path, "ab") as fh:
        fh.write(b'{"role": "assistant", "cont')          # crash mid-write

    first = SessionStore(str(tmp_path), "s1")
    assert [m["content"] for m in first.load()] == ["one"]
    assert store.path.read_bytes().endswith(b"\n")
    await first.append({"role": "assistant", "content": "two"})
    await first.close()

    second = SessionStore(str(tmp_path), "s1")
    assert [m["content"] for m in second.load()] == ["one", "two"]


@pytest.mark.asyncio
async def test_complete_last_record_without_newline_is_terminated(tmp_path):
    store = SessionStore(str(tmp_path), "s2")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b'{"role": "user", "content": "one"}')    # LF lost

    assert [m["content"] for m in store.load()] == ["one"]
    await store.append({"role": "assistant", "content": "two"})
    await store.close()
    assert [m["content"] for m in SessionStore(str(tmp_path), "s2").load()] == ["one", "two"]


def test_torn_multibyte_tail_does_not_fail_the_whole_load(tmp_path):
    store = SessionStore(str(tmp_path), "s3")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    good = json.dumps({"role": "user", "content": "привет"}, ensure_ascii=False).encode()
    torn = json.dumps({"role": "user", "content": "мир"}, ensure_ascii=False).encode()[:-4]
    store.path.write_bytes(good + b"\n" + torn)

    assert [m["content"] for m in store.load()] == ["привет"]
    assert store.path.read_bytes() == good + b"\n"


def test_corruption_in_the_middle_stays_loud(tmp_path):
    store = SessionStore(str(tmp_path), "s4")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b'{"role": "user", "content": "a"}\n{broken\n{"role": "user", "content": "b"}\n')

    with pytest.raises(RuntimeError, match="invalid JSONL line 2"):
        store.load()


# ── 4. merge gate: prompt sources select their contracts; one archive per target ──

def test_pipeline_and_root_instruction_edits_select_prompt_contracts(tmp_path):
    from app.merge_test_gate import PROMPT_CONTRACT_TESTS, select_tests

    (tmp_path / "tests").mkdir()
    for test in PROMPT_CONTRACT_TESTS[:3]:
        (tmp_path / test).write_text("def test_x():\n    assert True\n", encoding="utf-8")

    for changed in ([".orchestra/pipelines/default/prompts/modules/orchestration.md"],
                    ["./.orchestra/pipelines/default/pipeline.yaml"], ["AGENTS.md"]):
        assert select_tests(changed, worktree=str(tmp_path)) == sorted(PROMPT_CONTRACT_TESTS[:3])
    assert select_tests(["docs/a.md"], worktree=str(tmp_path)) == []


def test_mutation_gate_archives_the_target_once(tmp_path, monkeypatch):
    from app import merge_test_gate as gate
    from tests.test_merge_test_gate import _mutation_repo

    repo, target = _mutation_repo(
        tmp_path, "from app.widget import VALUE\n\ndef test_widget():\n    assert VALUE == 2\n",
    )
    archives = []
    real_run = subprocess.run

    def counting_run(argv, *args, **kwargs):
        if list(argv[:2]) == ["git", "archive"]:
            archives.append(list(argv))
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(gate.subprocess, "run", counting_run)
    monkeypatch.setattr(
        gate, "run_pytest",
        lambda _worktree, tests, **_kwargs: {
            "status": gate.PASSED, "reason": "", "exit_code": 0, "output": "", "tests": list(tests),
        },
    )
    result = gate.evaluate_mutation_gate(
        str(repo), ["app/widget.py", "tests/test_widget.py"], target_sha=target,
    )

    assert result["control_status"] == gate.PASSED
    assert len(archives) == 1, archives
    assert gate._ARCHIVE_CACHE.get() is None


# ── 5. hub upload packs exactly the bytes it scanned ──

def test_write_tar_refuses_a_file_that_gained_a_secret_after_planning(tmp_path):
    from app import hub_workspace as hw

    secret = "orchestra-test-credential-value-1110"
    (tmp_path / "notes.md").write_text("clean\n", encoding="utf-8")
    plan = hw.plan_upload(tmp_path, known=[secret])
    assert "notes.md" in plan.manifest
    (tmp_path / "notes.md").write_text(f"token: {secret}\n", encoding="utf-8")

    with pytest.raises(hw.HubWorkspaceError, match="contains a credential"):
        hw.write_tar(tmp_path, sorted(plan.manifest), tmp_path / "out.tar", known=[secret])


def test_write_tar_refuses_a_file_swapped_for_a_symlink(tmp_path):
    from app import hub_workspace as hw

    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    plan = hw.plan_upload(tmp_path, known=[])
    (tmp_path / "a.txt").unlink()
    (tmp_path / "a.txt").symlink_to(tmp_path / "outside.txt")

    with pytest.raises(hw.HubWorkspaceError, match="a.txt"):
        hw.write_tar(tmp_path, sorted(plan.manifest), tmp_path / "out.tar", known=[])


def test_write_tar_archives_the_scanned_bytes_with_mode(tmp_path):
    from app import hub_workspace as hw

    script = tmp_path / "run.sh"
    script.write_text("echo ok\n", encoding="utf-8")
    script.chmod(0o755)
    hw.write_tar(tmp_path, ["run.sh"], tmp_path / "out.tar", known=[])

    with tarfile.open(tmp_path / "out.tar") as archive:
        member = archive.getmember("run.sh")
        assert member.isreg() and member.mode == 0o755 and member.uid == 0
        assert archive.extractfile(member).read() == b"echo ok\n"


# ── 6. publication inventory is cached by stat stamps, never past a change ──

def _aged(path: Path) -> None:
    old = time.time() - 60
    os.utime(path, (old, old))


def test_literal_rules_reuse_unchanged_sources_and_see_every_change(tmp_path, monkeypatch):
    from app import publication_secrets as ps

    ps.clear_caches()
    root = tmp_path / "platform"
    (root / "data" / "secrets").mkdir(parents=True)
    env = root / ".env"
    env.write_text("SERVICE_TOKEN=first-value-1234567\n", encoding="utf-8")
    _aged(env)
    _aged(root / "data" / "secrets")
    monkeypatch.setattr(ps, "PLATFORM_ROOT", root)
    reads = []
    real_env_values = ps._env_values
    monkeypatch.setattr(ps, "_env_values", lambda path: reads.append(path) or real_env_values(path))

    assert (".env SERVICE_TOKEN", "first-value-1234567") in ps.literal_rules()
    assert (".env SERVICE_TOKEN", "first-value-1234567") in ps.literal_rules()
    assert len(reads) == 1, "unchanged sources are not re-read"

    env.write_text("SERVICE_TOKEN=second-value-7654321\n", encoding="utf-8")
    assert (".env SERVICE_TOKEN", "second-value-7654321") in ps.literal_rules()
    (root / "data" / "secrets" / "tok").write_text("file-secret-abcdefghij", encoding="utf-8")
    assert ("secret file tok", "file-secret-abcdefghij") in ps.literal_rules()


def test_fresh_sources_are_never_cached(tmp_path, monkeypatch):
    from app import publication_secrets as ps

    ps.clear_caches()
    root = tmp_path / "platform"
    root.mkdir()
    monkeypatch.setattr(ps, "PLATFORM_ROOT", root)
    (root / ".env").write_text("SERVICE_TOKEN=aaaaaaaaaaaaaaaa\n", encoding="utf-8")
    assert (".env SERVICE_TOKEN", "aaaaaaaaaaaaaaaa") in ps.literal_rules()
    # Same size, same coarse mtime tick: the stamp may not move, the racy window still re-reads.
    (root / ".env").write_text("SERVICE_TOKEN=bbbbbbbbbbbbbbbb\n", encoding="utf-8")
    assert (".env SERVICE_TOKEN", "bbbbbbbbbbbbbbbb") in ps.literal_rules()


def test_main_checkout_runs_git_once_per_repository(tmp_path, monkeypatch):
    from app import publication_secrets as ps

    ps.clear_caches()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git_calls = []
    real_run = ps.subprocess.run
    monkeypatch.setattr(ps.subprocess, "run",
                        lambda argv, *a, **k: git_calls.append(argv) or real_run(argv, *a, **k))

    assert ps.main_checkout(repo) == repo.resolve()
    assert ps.main_checkout(repo) == repo.resolve()
    assert len(git_calls) == 1


def test_temp_rules_fingerprints_are_defined_once():
    import inspect

    from app import temp_rules

    source = inspect.getsource(temp_rules)
    assert source.count("\ndef fingerprint(") == 1
    assert source.count("\ndef block_fingerprint(") == 1
    prompt = "base\n\n<temporary-rules>\n- R\n</temporary-rules>"
    assert temp_rules.current_block(prompt) == "<temporary-rules>\n- R\n</temporary-rules>"
    assert temp_rules.current_block("base") == ""
