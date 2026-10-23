"""Plain uploads have no merge allowances; failed Git inspection stays retryable."""
import subprocess

import pytest

from app import hub_workspace as hw, workspace
from tests.test_diff_budget import git_repo
from tests.test_merge_worker_v1034 import git


@pytest.mark.parametrize("legacy", [False, True])
def test_plain_upload_freezes_no_exemptions_even_after_git_init(tmp_path, monkeypatch, legacy):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "raw.txt").write_text("original input\n")
    (root / "output.txt").write_text("derived output\n")
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "state")
    plan = hw.plan_upload(root, known=[])
    assert set(plan.manifest) == {"raw.txt", "output.txt"}
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(root), "",
                              manifest=dict(plan.manifest) if legacy else {})
    hw.capture_inputs(root, state, plan.manifest)
    assert state.input_manifest == {}
    state.save()
    state = hw.WorkspaceState.load(state.ws_id)
    assert state.input_manifest == {}

    # Becoming a Git worktree cannot retroactively authorize a plain upload's
    # originals or outputs. In particular, an untracked output must block merge.
    git(root, "init", "-b", "main")
    git(root, "add", "raw.txt")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "base")
    state.manifest = dict(hw.plan_upload(root, known=[]).manifest)
    hw.capture_inputs(root, state, state.manifest)
    assert state.input_manifest == {}
    inputs = hw.merge_inputs(root, "HEAD")
    assert inputs == {}
    error = workspace._clean_worktree_error(root, "worker", hub_inputs=inputs)
    assert error and "output.txt" in error


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("failure", ["unavailable", "index"])
def test_git_inspection_failure_has_no_fallback_and_can_recover(git_repo, monkeypatch, legacy, failure):
    (git_repo / "raw.txt").write_text("original input\n")
    (git_repo / "generated.txt").write_text("hub output\n")
    plan = hw.plan_upload(git_repo, known=[])
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(git_repo), "",
                              manifest=dict(plan.manifest) if legacy else {},
                              hub_made=["generated.txt"])
    real_git = hw._git_out

    def fail(root, *args):
        if failure == "unavailable":
            return None
        if args[0] == "ls-files":
            return subprocess.CompletedProcess(args, 128, b"", b"invalid index")
        return real_git(root, *args)

    monkeypatch.setattr(hw, "_git_out", fail)
    with pytest.raises(hw.HubWorkspaceError):
        hw.capture_inputs(git_repo, state, plan.manifest)
    assert state.input_manifest is None
    monkeypatch.setattr(hw, "_git_out", real_git)
    hw.capture_inputs(git_repo, state, plan.manifest)
    assert state.input_manifest == {"raw.txt": hw.sha256_file(git_repo / "raw.txt")}


@pytest.mark.parametrize("metadata", ["directory", "gitfile", "symlink", "ancestor"])
def test_broken_git_metadata_is_not_a_plain_upload(tmp_path, metadata):
    root = tmp_path / "broken"
    root.mkdir()
    marker = root / ".git"
    if metadata in {"directory", "ancestor"}:
        marker.mkdir()
    elif metadata == "gitfile":
        marker.write_text("gitdir: missing\n")
    else:
        marker.symlink_to("missing")
    if metadata == "ancestor":
        root = root / "nested"
        root.mkdir()
    (root / "raw.txt").write_text("original input\n")
    plan = hw.plan_upload(root, known=[])
    assert "raw.txt" in plan.manifest  # fallback enumeration still supports upload planning
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(root), "")
    with pytest.raises(hw.HubWorkspaceError):
        hw.capture_inputs(root, state, plan.manifest)
    assert state.input_manifest is None
