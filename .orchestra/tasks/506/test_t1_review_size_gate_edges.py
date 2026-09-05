import inspect
import sqlite3
import subprocess

import pytest


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repo(tmp_path, relative, content, *, binary=False):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    target = _git(repo, "rev-parse", "HEAD")
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(content)
    else:
        path.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "candidate")
    return repo, target, _git(repo, "rev-parse", "HEAD")


def test_t1_binary_malformed_numstat_and_unresolved_ref_fail_safe(tmp_path):
    import app.mcp_stdio as mcp

    parser = getattr(mcp, "_parse_review_numstat", None)
    gate = getattr(mcp, "_implementation_review_size_decision", None)
    assert callable(parser), "T1 missing fail-safe numstat parser"
    assert callable(gate), "T1 missing complete-diff review size gate"

    with pytest.raises(ValueError, match="numstat"):
        parser(b"20\t0\tmissing-nul-terminator")

    repo, target, head = _repo(
        tmp_path / "binary",
        "assets/payload.bin",
        b"\x00\x01\x02\xff" * 20,
        binary=True,
    )
    binary = gate(str(repo), target, head, required=False)
    assert binary["status"] == "review"
    assert binary["reason"] == "binary_diff"
    assert binary["changed_files"] == 1
    assert binary["binary_files"] == 1

    failed = gate(str(repo), "not-a-commit", head, required=False)
    assert failed["status"] == "review"
    assert failed["reason"] == "measurement_failed"
    assert "not-a-commit" not in failed["evidence"], (
        "raw Git failure details must not become an uncontrolled user-facing contract"
    )


@pytest.mark.asyncio
async def test_t1_size_skip_retry_reuses_one_receipt(tmp_path, monkeypatch):
    import app.db as db
    import app.mcp_stdio as mcp

    assert "required" in inspect.signature(mcp.codex_review).parameters, (
        "T1 codex_review has no fail-safe risk input"
    )
    repo, target, _head = _repo(
        tmp_path / "retry",
        "app/ordinary.py",
        "".join(f"line-{index}\n" for index in range(20)),
    )
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "review.db")
    db.init_db()

    async def fake_api(method, path, **kwargs):
        assert method == "GET" and path.startswith("/api/sessions/")
        return {
            "id": "worker-session-506",
            "name": "review-policy",
            "cwd": str(repo),
            "worktree_path": str(repo),
            "scope": str(repo),
            "task_id": "506",
            "base_branch": target,
        }

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "review-policy")
    monkeypatch.setattr(mcp, "SCOPE", str(repo))
    monkeypatch.setattr(
        mcp,
        "_load_review_project_context",
        lambda *_args, **_kwargs: pytest.fail("size skip must precede review ingestion"),
    )

    kwargs = {
        "context": "Final task diff; explicit low risk.",
        "output": ".orchestra/tasks/506/review.md",
        "mode": "implementation",
        "model": "gpt5.6luna",
        "required": False,
    }
    first = await mcp.codex_review(**kwargs)
    second = await mcp.codex_review(**kwargs)
    first_payload = first.structuredContent["result"]
    second_payload = second.structuredContent["result"]
    assert first_payload["receipt_id"] == second_payload["receipt_id"]
    assert first_payload == second_payload

    with sqlite3.connect(db.DB_PATH) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM review_receipts WHERE coverage_outcome='skipped'"
        ).fetchone()[0]
    assert count == 1
