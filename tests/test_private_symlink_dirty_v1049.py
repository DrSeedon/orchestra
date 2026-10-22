"""V-1049: clean checks must not depend on a generated local ignore surviving.

Uses real temporary repositories; also runnable with stdlib unittest on a bare hub.
"""
import asyncio
import importlib.util
import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import hub_workspace as hw, private_folder as private, sparse_worktree, workspace


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout


class PrivateSymlinkDirtyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="private-status-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Test", "GIT_COMMITTER_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
            "ORCHESTRA_FORBIDDEN_STRINGS": str(self.root / "no-forbidden-strings"),
        })
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / ".orchestra").mkdir()
        (self.repo / ".orchestra/README.md").write_text("Project metadata\n")
        (self.repo / ".gitignore").write_text(
            ".orchestra/\n!.orchestra/\n!.orchestra/**\n")
        (self.repo / "code.txt").write_text("initial\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "initial")
        (self.repo / ".git/info/exclude").write_text(private.EXCLUDE_PATTERN + "\n")
        self.wt = self.root / "worker"
        git(self.repo, "worktree", "add", "-qb", "task-V-1049/worker", str(self.wt))
        self.shared = private.ensure_private(self.wt)
        self.assertEqual(self.shared, self.repo / private.PRIVATE_REL)
        self.link = self.wt / private.PRIVATE_REL
        self.ignore = self.wt / ".orchestra/.gitignore"

    def expose_link(self):
        self.ignore.unlink()
        self.assertIn("?? " + private.PRIVATE_REL, self.raw_status())

    def raw_status(self, nul=False):
        return git(self.wt, "status", "--porcelain", "--untracked-files=all",
                   *(["-z"] if nul else []))

    def assert_clean(self):
        result = workspace.branch_wip_status(str(self.wt), "main")
        self.assertNotIn("error", result)
        self.assertEqual(result["uncommitted"], [])
        self.assertNotIn(private.PRIVATE_REL, [p["path"] for p in result["changed_files"]])
        self.assertIsNone(workspace._clean_worktree_error(self.wt, "worker"))

    def test_reinclude_with_missing_generated_ignore(self):
        self.expose_link()
        self.assert_clean()
        self.assertFalse(self.ignore.exists(), "clean checks must not mutate ignore files")
        result = workspace.switch_worktree_branch(
            str(self.wt), "task-V-1050/worker", from_ref="main")
        self.assertTrue(result["ok"], result)

    def test_tracked_project_ignore_cannot_be_repaired(self):
        self.ignore.write_text("/project-cache\n")
        git(self.wt, "add", "-f", ".orchestra/.gitignore")
        git(self.wt, "commit", "-qm", "project owns the deeper ignore")
        with self.assertLogs(private.logger, level="WARNING"):
            private.ensure_private(self.wt)
        self.assertEqual(self.ignore.read_text(), "/project-cache\n")
        self.assertIn("?? " + private.PRIVATE_REL, self.raw_status())
        self.assert_clean()

    def test_branch_reset_replaces_generated_ignore_and_sparse_reapply(self):
        # Git may overwrite an ignored untracked file when the new tree tracks that path.
        (self.repo / ".orchestra/.gitignore").write_text("/project-cache\n")
        git(self.repo, "add", "-f", ".orchestra/.gitignore")
        git(self.repo, "commit", "-qm", "version project ignore")
        self.assertEqual(self.ignore.read_text(), "/private\n/.gitignore\n")
        self.assertEqual(sparse_worktree.apply_patterns(
            self.wt, ["/*", "!/.orchestra/history/"], workspace._git_cmd), "")
        result = workspace.switch_worktree_branch(
            str(self.wt), "task-V-1050/worker", from_ref="main")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.ignore.read_text(), "/project-cache\n")
        git(self.wt, "sparse-checkout", "reapply")
        self.assertIn("?? " + private.PRIVATE_REL, self.raw_status())
        self.assert_clean()

    def test_hub_roundtrip_and_merge_with_exposed_link(self):
        self.expose_link()
        self.assertEqual(sparse_worktree.apply_patterns(
            self.wt, ["/*", "!/.orchestra/history/"], workspace._git_cmd), "")
        plan = hw.plan_upload(self.wt, known=[])
        self.assertNotIn(private.PRIVATE_REL, plan.manifest)
        snapshot = self.root / "snapshot.tar"
        with tarfile.open(snapshot, "w") as archive:
            for name in plan.manifest:
                data = b"hub fix\n" if name == "code.txt" else (self.wt / name).read_bytes()
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        synced = hw.apply_changes(snapshot, self.wt, plan.manifest, known=[])
        self.assertEqual(synced.changed, ["code.txt"])
        self.assertEqual(synced.deleted, [])
        self.assertEqual(synced.rejected, [])
        commit, failed = hw.commit_sync(self.wt, synced.changed, synced.deleted, "hub fix")
        self.assertTrue(commit)
        self.assertEqual(failed, [])
        self.assert_clean()
        result = workspace.merge_worktree_to_main(str(self.wt), str(self.repo), "main")
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.repo / "code.txt").read_text(), "hub fix\n")
        self.assertTrue(self.link.is_symlink())
        self.assert_clean()

    def test_ordinary_hub_roundtrip_does_not_remove_generated_ignore(self):
        plan = hw.plan_upload(self.wt, known=[])
        self.assertNotIn(".orchestra/.gitignore", plan.manifest)
        snapshot = self.root / "snapshot.tar"
        hw.write_tar(self.wt, sorted(plan.manifest), snapshot)
        synced = hw.apply_changes(snapshot, self.wt, plan.manifest, known=[])
        self.assertEqual(synced.deleted, [])
        self.assertEqual(self.ignore.read_text(), "/private\n/.gitignore\n")
        self.assert_clean()

    def test_real_user_file_still_blocks_wip_merge_and_switch(self):
        self.expose_link()
        # Same parent as the planted link: status must expand untracked directories.
        (self.wt / ".orchestra/user-note.txt").write_text("keep my work\n")
        result = workspace.branch_wip_status(str(self.wt), "main")
        self.assertEqual(result["uncommitted"], [".orchestra/user-note.txt"])
        self.assertIn(".orchestra/user-note.txt",
                      workspace._clean_worktree_error(self.wt, "worker"))
        switched = workspace.switch_worktree_branch(
            str(self.wt), "task-V-1050/worker", from_ref="main")
        self.assertFalse(switched["ok"])
        merged = workspace.merge_worktree_to_main(str(self.wt), str(self.repo), "main")
        self.assertFalse(merged["ok"])
        self.assertIn(".orchestra/user-note.txt", merged["error"])
        self.assertEqual((self.wt / ".orchestra/user-note.txt").read_text(), "keep my work\n")

    def test_missing_tracked_metadata_does_not_collapse_user_files(self):
        self.expose_link()
        git(self.wt, "rm", ".orchestra/README.md")
        git(self.wt, "commit", "-qm", "no tracked metadata files")
        (self.wt / ".orchestra/user.txt").write_text("keep\n")
        self.assertEqual(workspace.branch_wip_status(str(self.wt), "main")["uncommitted"],
                         [".orchestra/user.txt"])

    def test_other_links_files_directories_and_lookalikes_are_not_hidden(self):
        self.expose_link()
        self.link.unlink()
        self.link.write_text("user file\n")
        self.assertEqual(private.filter_worktree_status(self.wt, self.raw_status()), self.raw_status())
        self.link.unlink()
        elsewhere = self.root / "other"
        elsewhere.mkdir()
        self.link.symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(private.filter_worktree_status(self.wt, self.raw_status()), self.raw_status())
        self.link.unlink()
        self.link.mkdir()
        (self.link / "user.txt").write_text("keep\n")
        self.assertEqual(private.filter_worktree_status(self.wt, self.raw_status()), self.raw_status())
        (self.wt / ".orchestra/private-other").symlink_to(self.shared)
        self.assertIn(".orchestra/private-other",
                      workspace.branch_wip_status(str(self.wt), "main")["uncommitted"])

    def test_tracked_link_changes_are_preserved(self):
        self.expose_link()
        self.link.unlink()
        self.link.symlink_to(self.root / "user-target")
        git(self.wt, "add", private.PRIVATE_REL)
        git(self.wt, "commit", "-qm", "user tracks private link")
        self.link.unlink()
        self.link.symlink_to(self.shared)
        raw = self.raw_status()
        self.assertIn(" M " + private.PRIVATE_REL, raw)
        self.assertEqual(private.filter_worktree_status(self.wt, raw), raw)
        self.assertEqual(workspace.branch_wip_status(str(self.wt), "main")["uncommitted"],
                         [private.PRIVATE_REL])

    def test_staged_link_addition_is_preserved(self):
        self.expose_link()
        git(self.wt, "add", private.PRIVATE_REL)
        raw = self.raw_status()
        self.assertIn("A  " + private.PRIVATE_REL, raw)
        self.assertEqual(private.filter_worktree_status(self.wt, raw), raw)

    def test_dangling_link_and_git_inspection_failure_fail_closed(self):
        self.expose_link()
        raw = self.raw_status()
        for error in (RuntimeError("git unavailable"), OSError("permission denied")):
            with self.subTest(error=type(error).__name__), patch.object(
                    private, "shared_private_dir", side_effect=error):
                self.assertEqual(private.filter_worktree_status(self.wt, raw), raw)
        self.shared.rmdir()
        self.assertEqual(private.filter_worktree_status(self.wt, raw), raw)

    def test_nul_rename_source_is_never_mistaken_for_untracked_record(self):
        self.expose_link()
        source = "?? " + private.PRIVATE_REL
        raw = "R  renamed\0" + source + "\0?? " + private.PRIVATE_REL + "\0"
        self.assertEqual(private.filter_worktree_status(self.wt, raw, nul=True),
                         "R  renamed\0" + source + "\0")

    def test_git_status_failure_is_preserved(self):
        failed = subprocess.CompletedProcess([], 128, "", "git failed")
        original = workspace._git_cmd

        def fail_status(args, **kwargs):
            return failed if args[:2] == ["git", "status"] else original(args, **kwargs)

        with patch.object(workspace, "_git_cmd", side_effect=fail_status):
            self.assertIn("cannot inspect", workspace._clean_worktree_error(self.wt, "worker"))
            self.assertIn("error", workspace.branch_wip_status(str(self.wt), "main"))

    def test_existing_link_repair_still_recreates_generated_ignore(self):
        self.expose_link()
        self.assert_clean()
        self.assertEqual(private.ensure_private(self.wt), self.shared)
        self.assertEqual(self.ignore.read_text(), "/private\n/.gitignore\n")
        self.assertEqual(self.raw_status(), "")

    def test_real_private_directory_in_main_is_not_filtered(self):
        (self.repo / ".orchestra/.gitignore").unlink()
        (self.shared / "user.txt").write_text("user content\n")
        raw = git(self.repo, "status", "--porcelain", "--untracked-files=all")
        self.assertIn("?? .orchestra/private/user.txt", raw)
        self.assertEqual(private.filter_worktree_status(self.repo, raw), raw)

    def test_kill_guard_allows_only_the_platform_link(self):
        # Full route import needs the normal project dependencies, absent on a bare hub.
        if importlib.util.find_spec("fastapi") is None:
            self.skipTest("full route dependencies unavailable: fastapi")
        from app.routes import sessions
        self.expose_link()
        found = SimpleNamespace(id="worker-id", loaded=False, scope=str(self.repo),
                                worktree_path=str(self.wt))
        manager = SimpleNamespace(
            get_by_name=lambda *args: found, _live_children=lambda *args: [], remove=AsyncMock())
        with patch.object(sessions, "manager", manager), patch.object(
                sessions, "_session_base_branch", return_value="main"):
            self.assertEqual(asyncio.run(sessions.delete_session("worker", str(self.repo))), {"ok": True})
            manager.remove.assert_awaited_once_with("worker-id")
            manager.remove.reset_mock()
            (self.wt / ".orchestra/user.txt").write_text("keep\n")
            refused = asyncio.run(sessions.delete_session("worker", str(self.repo)))
            self.assertEqual(refused.status_code, 400)
            self.assertIn(b".orchestra/user.txt", refused.body)
            manager.remove.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
