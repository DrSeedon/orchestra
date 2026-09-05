import inspect
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


def _repo_with_diff(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    target = _git(repo, "rev-parse", "HEAD")
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "candidate")
    return repo, target, _git(repo, "rev-parse", "HEAD")


def _lines(count):
    return "".join(f"line-{index}\n" for index in range(count))


def _decision(module, repo, target, head, required):
    gate = getattr(module, "_implementation_review_size_decision", None)
    assert callable(gate), "T1 missing complete-diff review size gate"
    return gate(str(repo), target, head, required=required)


def test_t1_complete_diff_threshold_and_fail_safe_risk(tmp_path):
    import app.mcp_stdio as mcp

    ordinary, target, head = _repo_with_diff(
        tmp_path / "ordinary", {"app/ordinary.py": _lines(20)},
    )
    skipped = _decision(mcp, ordinary, target, head, required=False)
    assert skipped == {
        "status": "skip",
        "reason": "size_threshold",
        "changed_lines": 20,
        "changed_files": 1,
        "binary_files": 0,
        "threshold_lines": 40,
        "threshold_files": 3,
        "required": False,
        "evidence": (
            "Review skipped by size: complete pinned diff is 20 changed lines across 1 file; "
            "threshold is <=40 lines AND <=3 files."
        ),
    }

    assert _decision(mcp, ordinary, target, head, required=True)["status"] == "review"
    assert _decision(mcp, ordinary, target, head, required=None)["status"] == "review"
    assert _decision(mcp, ordinary, target, head, required="false")["status"] == "review"
    assert _decision(mcp, ordinary, target, head, required=0)["status"] == "review"

    # `production_paths_json` would be empty here, but the complete pinned diff is large.
    foreign, foreign_target, foreign_head = _repo_with_diff(
        tmp_path / "foreign", {"foreign/core.py": _lines(100)},
    )
    foreign_decision = _decision(
        mcp, foreign, foreign_target, foreign_head, required=False,
    )
    assert foreign_decision["status"] == "review"
    assert foreign_decision["changed_lines"] == 100
    assert foreign_decision["changed_files"] == 1

    four_files, four_target, four_head = _repo_with_diff(
        tmp_path / "four-files",
        {f"src/file_{index}.py": "value = 1\n" for index in range(4)},
    )
    four_decision = _decision(
        mcp, four_files, four_target, four_head, required=False,
    )
    assert four_decision["status"] == "review"
    assert four_decision["changed_lines"] == 4
    assert four_decision["changed_files"] == 4


@pytest.mark.asyncio
async def test_t1_explicit_low_risk_skip_writes_auditable_receipt(tmp_path, monkeypatch):
    import app.db as db
    import app.mcp_stdio as mcp

    assert "required" in inspect.signature(mcp.codex_review).parameters, (
        "T1 codex_review has no fail-safe risk input"
    )
    repo, target, head = _repo_with_diff(
        tmp_path / "audited", {"app/ordinary.py": _lines(20)},
    )
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "review.db")
    db.init_db()
    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
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
        lambda *_args, **_kwargs: pytest.fail("size skip must happen before review ingestion"),
    )

    result = await mcp.codex_review(
        context="Final task diff; explicit low risk.",
        output=".orchestra/tasks/506/review.md",
        mode="implementation",
        model="gpt5.6luna",
        required=False,
    )
    payload = result.structuredContent["result"]
    assert payload["kind"] == "review_skipped_by_size"
    assert payload["changed_lines"] == 20
    assert payload["changed_files"] == 1
    assert payload["threshold_lines"] == 40
    assert payload["threshold_files"] == 3
    assert payload["target_sha"] == target
    assert payload["worker_head"] == head
    assert "20 changed lines across 1 file" in result.content[0].text
    assert "<=40 lines AND <=3 files" in result.content[0].text
    assert calls == [("GET", "/api/sessions/review-policy", {"params": {"scope": str(repo)}})]

    receipt = db.review_receipt_get(payload["receipt_id"])
    assert receipt["status"] == "completed"
    assert receipt["subject_kind"] == "implementation"
    assert receipt["coverage_outcome"] == "skipped"
    assert receipt["target_sha"] == target
    assert receipt["worker_head"] == head
    assert receipt["decision_actor"] == "review-policy"
    assert receipt["outcome_evidence_ref"] == payload["evidence"]


@pytest.mark.asyncio
@pytest.mark.parametrize("required", [True, None, "false", 0])
async def test_t1_required_absent_or_malformed_starts_review(
    tmp_path, monkeypatch, required,
):
    import app.db as db
    import app.mcp_stdio as mcp

    assert "required" in inspect.signature(mcp.codex_review).parameters, (
        "T1 codex_review has no fail-safe risk input"
    )
    repo, target, _head = _repo_with_diff(
        tmp_path / "required", {"app/merge_operations.py": _lines(20)},
    )
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "review.db")
    db.init_db()
    jobs = []

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return {
                "policy": "worker-weekly-v1",
                "state": "available",
                "model": "gpt-5.6-luna",
                "provider": "codex",
                "provider_label": "Codex",
                "weekly_utilization": 1,
                "threshold": 95,
                "observed_at": 1,
                "valid_until": 9_999_999_999,
                "alternatives": [],
                "reason": "test",
            }
        if method == "GET":
            return {
                "id": "worker-session-506",
                "name": "review-policy",
                "cwd": str(repo),
                "worktree_path": str(repo),
                "scope": str(repo),
                "task_id": "506",
                "base_branch": target,
            }
        jobs.append(kwargs["json"])
        return {"id": "bg-review-506"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "review-policy")
    monkeypatch.setattr(mcp, "SCOPE", str(repo))
    monkeypatch.setattr(mcp, "_codex_bin", lambda: "/usr/bin/codex")
    monkeypatch.setattr(
        mcp,
        "_load_review_project_context",
        lambda *_args, **_kwargs: (
            "PROJECT CONTEXT (tool-owned): test",
            {"status": "loaded", "warning": ""},
        ),
    )

    kwargs = {
        "context": "Final task diff.",
        "output": ".orchestra/tasks/506/review.md",
        "mode": "implementation",
        "model": "gpt5.6luna",
    }
    if required is not None:
        kwargs["required"] = required
    result = await mcp.codex_review(**kwargs)
    assert "bg-review-506" in result.content[0].text
    assert len(jobs) == 1, "tiny diff was silently skipped without explicit required=False"
