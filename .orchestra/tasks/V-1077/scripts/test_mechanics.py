"""Synthetic behavior checks of existing Orchestra helpers; no model quality claims."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest
import yaml

from app import prompting


def skill(root, name="sample", description="Synthetic workflow", body="synthetic-body-18302"):
    root.mkdir(parents=True, exist_ok=True)
    file = root / f"{name}.md"
    file.write_text("---\n" + yaml.safe_dump({"name": name, "description": description}) + "---\n" + body + "\n")
    return file


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / "source"
    skill(root)
    refs = root / "sample/references"
    refs.mkdir(parents=True)
    (refs / "edge.md").write_bytes(b"synthetic-reference\n")
    monkeypatch.setattr(prompting, "_SKILLS_DIR", root)
    monkeypatch.setattr(prompting, "_retired_skill_hashes", lambda: {})
    return root


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


@pytest.mark.parametrize("home", [".claude", ".codex"])
def test_delivery_refresh_and_reference_repair(source, repo, home):
    first = prompting.inject_skills_to_worktree_report(["sample"], str(repo), home)
    dest = repo / home / "skills/sample/SKILL.md"
    ref = dest.parent / "references/edge.md"
    assert first.written == 1 and not first.skipped
    assert dest.read_bytes() == (source / "sample.md").read_bytes()
    assert ref.read_bytes() == (source / "sample/references/edge.md").read_bytes()
    unchanged = prompting.inject_skills_to_worktree_report(["sample"], str(repo), home)
    assert unchanged.written == 0
    ref.unlink()
    repaired = prompting.inject_skills_to_worktree_report(["sample"], str(repo), home)
    assert repaired.written == 0 and ref.is_file()
    skill(source, description="Changed source")
    refreshed = prompting.inject_skills_to_worktree_report(["sample"], str(repo), home)
    assert refreshed.written == 1
    assert dest.read_bytes() == (source / "sample.md").read_bytes()
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]) == b""


def test_tracked_destination_preserved(source, repo, monkeypatch):
    dest = repo / ".codex/skills/sample/SKILL.md"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"repository-owner\n")
    subprocess.run(["git", "-C", str(repo), "add", ".codex"], check=True)
    result = prompting.inject_skills_to_worktree_report(["sample"], str(repo), ".codex")
    assert result.written == 0 and result.skipped == ("tracked_skill:sample",)
    assert dest.read_bytes() == b"repository-owner\n"


def test_symlink_destination_preserved(source, repo):
    target = repo / "target"
    target.write_bytes(b"untouched")
    dest = repo / ".codex/skills/sample/SKILL.md"
    dest.parent.mkdir(parents=True)
    dest.symlink_to(target)
    result = prompting.inject_skills_to_worktree_report(["sample"], str(repo), ".codex")
    assert result.skipped == ("symlink:sample",)
    assert target.read_bytes() == b"untouched" and dest.is_symlink()


def test_home_file_conflict(source, repo):
    home = repo / ".codex"
    home.write_bytes(b"repository-owned-file")
    subprocess.run(["git", "-C", str(repo), "add", ".codex"], check=True)
    result = prompting.inject_skills_to_worktree_report(["sample"], str(repo), ".codex")
    assert result.home_path_is_file and result.home_path_tracked
    assert result.written == 0 and home.read_bytes() == b"repository-owned-file"


def test_no_git_state_fails_closed(source, tmp_path):
    dest = tmp_path / "not-a-repo"
    dest.mkdir()
    result = prompting.inject_skills_to_worktree_report(["sample"], str(dest))
    assert result.skipped == ("unsafe_git_state",)
    assert not (dest / ".claude").exists()


def test_missing_root_and_missing_entry(source, repo, monkeypatch):
    missing = prompting.inject_skills_to_worktree_report(["absent"], str(repo))
    assert missing.skipped == ("missing_source:absent",)
    monkeypatch.setattr(prompting, "_SKILLS_DIR", source / "absent")
    assert prompting.inject_skills_to_worktree_report(["sample"], str(repo)).skipped == ("missing_skill_root",)


def test_atomic_same_content_writers(source, repo):
    dest = repo / "destination/SKILL.md"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: prompting._copy_skill_file(source / "sample.md", dest), range(2)))
    assert all(results)
    assert dest.read_bytes() == (source / "sample.md").read_bytes()
    assert list(dest.parent.glob(".SKILL.md.*.tmp")) == []


def test_metadata_only_dedup_required_precedes_optional(tmp_path):
    required = skill(tmp_path / "required", body="synthetic-payload-56182")
    optional = skill(tmp_path / "optional", description="Other workflow")
    name, description, path = prompting._read_skill_index_entry(required)
    assert (name, description, path) == ("sample", "Synthetic workflow", required.resolve())
    index = prompting.build_skills_index([required], [optional])
    assert str(required.resolve()) in index and str(optional.resolve()) not in index
    assert "synthetic-payload-56182" not in index


def test_required_invalid_raises_optional_invalid_skipped(tmp_path):
    invalid = tmp_path / "bad.md"
    invalid.write_text("---\nname: bad\n---\n")
    with pytest.raises(ValueError):
        prompting.build_skills_index([invalid], [])
    assert prompting.build_skills_index([], [invalid]) == ""


@pytest.mark.parametrize("length", [1024, 1025])
def test_current_index_accepts_both_description_lengths(tmp_path, length):
    file = skill(tmp_path / "skill", description="x" * length)
    _, description, _ = prompting._read_skill_index_entry(file)
    assert len(description) == length  # observation: this helper is not the spec validator


def test_offline_guard_active():
    with pytest.raises(RuntimeError):
        socket.create_connection(("127.0.0.1", 1))
    with pytest.raises(RuntimeError):
        subprocess.run(["codex", "--version"])
    with pytest.raises(RuntimeError):
        subprocess.run(["git", "commit", "-m", "denied"])


@pytest.mark.parametrize("home", [".claude", ".codex"])
def test_actual_seven_sources_and_references_deliver_without_manifest(repo, monkeypatch, home):
    root = Path(prompting.__file__).resolve().parents[1] / ".orchestra/pipelines/default/prompts/skills"
    names = sorted(path.stem for path in root.glob("*.md"))
    assert len(names) == 7
    monkeypatch.setattr(prompting, "_retired_skill_hashes", lambda: {})
    result = prompting.inject_skills_to_worktree_report(names, str(repo), home)
    assert result.written == 7 and not result.skipped
    for name in names:
        dest = repo / home / "skills" / name
        assert (dest / "SKILL.md").read_bytes() == (root / f"{name}.md").read_bytes()
        for ref in (root / name / "references").rglob("*"):
            if ref.is_file():
                assert (dest / "references" / ref.relative_to(root / name / "references")).read_bytes() == ref.read_bytes()
    assert subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]) == b""


def test_animation_extraction_observed_source_mismatch():
    root = Path(prompting.__file__).resolve().parents[1] / ".orchestra/pipelines/default/prompts/skills"
    program = '/^```html motion-template/{f=1;next} f&&/^```/{exit} f'
    entry = subprocess.check_output(["awk", program, str(root / "html-artifacts.md")])
    reference = subprocess.check_output(["awk", program, str(root / "html-artifacts/references/animation.md")])
    assert len(entry) == 0
    assert len(reference) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime,home", [("claude", ".claude"), ("codex", ".codex")])
async def test_session_uses_cwd_and_refreshes_explicit_synthetic_role(repo, monkeypatch, runtime, home):
    from app import pipeline
    from app.session import AgentSession
    names = ["html-artifacts", "explainer-craft"]
    monkeypatch.setattr(pipeline, "get_role", lambda *_: SimpleNamespace(skills=names))
    monkeypatch.setattr(prompting, "_retired_skill_hashes", lambda: {})
    session = AgentSession.__new__(AgentSession)
    session.name = "synthetic"
    session.backend_type = runtime
    session.worktree_path = ""
    session.cwd = str(repo)
    session.pipeline = "default"
    session.role = "worker"
    await session._refresh_skills()
    for name in names:
        assert (repo / home / "skills" / name / "SKILL.md").is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["claude", "codex", "hub", "harness", "grok"])
async def test_all_or_unsupported_runtime_creates_no_explicit_skill_files(repo, monkeypatch, runtime):
    from app import pipeline
    from app.session import AgentSession
    monkeypatch.setattr(pipeline, "get_role", lambda *_: SimpleNamespace(skills="all"))
    monkeypatch.setattr(prompting, "_retired_skill_hashes", lambda: {})
    session = AgentSession.__new__(AgentSession)
    session.name = "synthetic"
    session.backend_type = runtime
    session.worktree_path = ""
    session.cwd = str(repo)
    session.pipeline = "default"
    session.role = "worker"
    await session._refresh_skills()
    assert not (repo / ".claude").exists() and not (repo / ".codex").exists()
