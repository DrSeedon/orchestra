"""V-1047: literals use secret_scan's existing API; git shapes have one owner.

Runnable with stdlib unittest offline. Actual scanner integration is explicitly
skipped if that file was excluded from the worker upload, never reimplemented.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import forbidden_strings as guard, publication_secrets as secrets
from scripts import install_git_hooks as installer

ARTIFACTS = ROOT / ".orchestra" / "tasks" / "V-1047"
SCANNER = ROOT / "scripts" / "secret_scan.py"
MODULES = ("publication_secrets.py", "forbidden_strings.py", "secret_mask.py", "runtime_history.py",
           "workspace.py", "private_folder.py", "sparse_worktree.py", "diff_budget.py")


class GateTests(unittest.TestCase):
    def setUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ARTIFACTS, prefix="offline-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.directory),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
            guard.ENV_VAR: str(self.directory / "absent-list"),
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.platform = self.repository("platform checkout")
        self.repo = self.repository("target")
        (self.platform / "scripts").mkdir()
        # Dispatch sentinel only: no credential rules or scanner emulation.
        (self.platform / "scripts" / "secret_scan.py").write_text(
            "import pathlib, sys\n"
            "pathlib.Path('scanner-args').write_text('\\n'.join(sys.argv[1:]))\n"
            "raise SystemExit(23)\n"
        )
        context = patch.object(secrets, "PLATFORM_ROOT", self.platform)
        context.start()
        self.addCleanup(context.stop)
        self.literal = "local-value-" + "ab78" * 7
        self.shape = "gh" + "p_" + "A4b5" * 9

    def git(self, repo, *args, data=None):
        result = subprocess.run(["git", "-C", str(repo), *args], input=data,
                                text=True, capture_output=True)
        if result.returncode:
            self.fail(f"fixture git {args[0]} failed (output suppressed)")
        return result.stdout.strip()

    def snapshot(self, repo, message="work"):
        tree = self.git(repo, "write-tree")
        parent = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
                                capture_output=True, text=True)
        args = ("-p", parent.stdout.strip()) if parent.returncode == 0 else ()
        head = self.git(repo, "commit-tree", tree, *args, data=message + "\n")
        self.git(repo, "update-ref", "HEAD", head)
        return head

    def repository(self, name):
        repo = self.directory / name
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        (repo / ".gitignore").write_text(".env\ndata/\n")
        (repo / "base.txt").write_text("base\n")
        self.git(repo, "add", ".")
        self.snapshot(repo, "base")
        return repo

    def stage(self, text, filename="note.txt", repo=None):
        repo = repo or self.repo
        (repo / filename).write_text(text)
        self.git(repo, "add", "--", filename)

    def rules(self, repo=None):
        # This is precisely the unmodified secret_scan pre-push API.
        return guard.load_rules(guard.list_path(repo or self.repo))

    def assert_private_diagnostic(self, found, rule, origin="note.txt:2"):
        self.assertTrue(found)
        message = guard.block_message(found)
        self.assertIn(rule, message)
        self.assertIn(origin, message)
        self.assertTrue(self.literal not in message, "literal appeared in diagnostics")

    def test_existing_scanner_load_path_adds_target_env(self):
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY='{self.literal}'\n")
        found = guard.scan_text("first\n" + self.literal, "note.txt:2", self.rules())
        self.assert_private_diagnostic(found, "DEEPGRAM_API_KEY")

    def test_default_list_path_also_carries_target_context(self):
        os.environ.pop(guard.ENV_VAR)
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        self.assert_private_diagnostic(guard.scan_text(self.literal, "note.txt:2", self.rules()),
                                       "DEEPGRAM_API_KEY")

    def test_rule_paths_keep_project_context_when_interleaved(self):
        other = self.repository("other")
        alternate = "other-value-" + "cd89" * 7
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        (other / ".env").write_text(f"DEEPGRAM_API_KEY={alternate}\n")
        first, second = guard.list_path(self.repo), guard.list_path(other)
        self.assertEqual(first, second)  # One shared explicit stop-list override.
        self.assertTrue(any(value == self.literal for _, value in guard.load_rules(first)))
        self.assertFalse(any(value == alternate for _, value in guard.load_rules(first)))
        self.assertTrue(any(value == alternate for _, value in guard.load_rules(second)))
        self.assertFalse(any(value == self.literal for _, value in guard.load_rules(second)))
        self.assertEqual(guard.load_rules(Path(first)), [])  # Plain Path remains list-only.

    def test_missing_stop_list_does_not_skip_platform_env_and_secret_files(self):
        (self.platform / ".env").write_text(f"PLATFORM_TOKEN={self.literal}\n")
        directory = self.platform / "data" / "secrets"
        directory.mkdir(parents=True)
        file_value = "file-value-" + "ef90" * 6
        (directory / "tok").write_text(file_value + "\n")
        rules = self.rules()
        self.assert_private_diagnostic(guard.scan_text(self.literal, "note.txt:2", rules), "PLATFORM_TOKEN")
        found = guard.scan_text(file_value, "artifact.txt:7", rules)
        self.assertTrue(found and "secret file tok" in found[0])
        self.assertTrue(file_value not in guard.block_message(found))

    def test_existing_stop_list_and_local_credentials_both_apply(self):
        listing = self.directory / "stop-list"
        listing.write_text("# comment\n" + self.literal + "\n")
        os.environ[guard.ENV_VAR] = str(listing)
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        found = guard.scan_text(self.literal, "note.txt:2", self.rules())
        self.assert_private_diagnostic(found, "forbidden-string line 2")
        self.assertTrue(any("DEEPGRAM_API_KEY" in row for row in found))

    def test_names_placeholders_paths_quotes_and_interpolation(self):
        (self.repo / ".env").write_text(
            "SECRET=\n" + f"BASE={self.literal}\nexport DEEPGRAM_API_KEY=\"${{BASE}}\" # comment\n"
            "API_KEY=your-api-key-here\nTOKEN=short\nSECRET_PATH=data/secrets/token-file\n"
            "PASSWORD=/some/local/path\nAPI_HASH=${MISSING}\n"
        )
        rules = self.rules()
        self.assertTrue(any(value == self.literal for _, value in rules))
        self.assertFalse(any(value in {"short", "your-api-key-here", "data/secrets/token-file",
                                       "/some/local/path", "${MISSING}"} for _, value in rules))
        self.assertEqual(guard.scan_text("DEEPGRAM_API_KEY API_KEY=<put-key-here>", "notes:1", rules), [])

    def test_worktree_reads_own_and_main_env(self):
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        worker = self.directory / "worker"
        self.git(self.repo, "worktree", "add", "-q", "-b", "worker", str(worker))
        own_value = "worker-value-" + "ef90" * 6
        (worker / ".env").write_text(f"WORKER_TOKEN={own_value}\n")
        rules = self.rules(worker)
        self.assertTrue(any(value == self.literal for _, value in rules))
        self.assertTrue(any(value == own_value for _, value in rules))

    def test_literal_in_path_message_and_multiline_content_is_redacted(self):
        multiline = self.literal + "\n" + "second-value-" + "cd89" * 6
        (self.repo / ".env").write_text('API_KEY="' + multiline + '"\nSOME_TOKEN=' + self.literal + '\n')
        base = self.git(self.repo, "rev-parse", "HEAD")
        self.stage("first\n" + multiline + "\n", filename=self.literal + ".txt")
        head = self.snapshot(self.repo, "message " + self.literal)
        found = guard.scan_range(self.repo, base, head, self.rules())
        self.assertTrue(any("API_KEY" in row for row in found))
        self.assertTrue(any("message:1" in row for row in found))
        self.assertTrue(self.literal not in guard.block_message(found))
        self.assertTrue(multiline not in guard.block_message(found))

    def test_history_added_then_removed_is_blocked_but_old_removal_passes(self):
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        base = self.git(self.repo, "rev-parse", "HEAD")
        self.stage("first\n" + self.literal + "\n")
        leaked = self.snapshot(self.repo)
        self.stage("removed\n")
        clean = self.snapshot(self.repo)
        self.assert_private_diagnostic(guard.scan_range(self.repo, base, clean, []), "DEEPGRAM_API_KEY")
        self.assertEqual(guard.scan_range(self.repo, leaked, clean, []), [])

    def test_scan_range_does_not_apply_hub_shapes(self):
        base = self.git(self.repo, "rev-parse", "HEAD")
        self.stage("Documentation: " + self.shape + "\n")
        head = self.snapshot(self.repo, "mention " + self.shape)
        self.assertEqual(guard.scan_range(self.repo, base, head, []), [])
        self.assertEqual(guard.scan_text(self.shape, "notes:1", []), [])

    def test_empty_filename_literal_and_binary_literals_are_checked(self):
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        base = self.git(self.repo, "rev-parse", "HEAD")
        self.stage("", filename=self.literal + ".txt")
        (self.repo / "binary.dat").write_bytes(b"\0\n" + self.literal.encode())
        self.git(self.repo, "add", "binary.dat")
        head = self.snapshot(self.repo)
        found = guard.scan_range(self.repo, base, head, [])
        self.assertTrue(any("(path)" in row for row in found))
        self.assert_private_diagnostic(found, "DEEPGRAM_API_KEY", "binary.dat:2")

    def test_hub_pem_header_mentions_pass_but_body_requires_40_characters(self):
        from app import hub_workspace as hub
        header = "-" * 5 + "BEGIN " + "PRIVATE KEY" + "-" * 5
        for text in (header, header + "\n", header + "\n" + "A" * 39 + "\n",
                     header + "\nThis documentation mentions a header without any private key body\n"):
            with self.subTest(size=len(text)):
                self.assertIsNone(hub.secret_in_text(text, []))
        for body in ("A" * 40, "A" * 20 + "\n" + "B" * 20):
            self.assertIsNotNone(hub.secret_in_text(header + "\n" + body + "\n", []))
        source = self.repo / "pem-notes.txt"
        source.write_text("Header mention: " + header + "\n")
        plan = hub.plan_upload(self.repo, ["pem-notes.txt"], known=[])
        self.assertIn("pem-notes.txt", plan.manifest)

    def test_hub_reuses_literal_inventory(self):
        from app import hub_workspace as hub
        directory = self.platform / "data" / "secrets"
        directory.mkdir(parents=True)
        (directory / "tok").write_text(self.literal)
        with patch.object(hub, "DATA_DIR", self.platform / "data"):
            self.assertTrue(self.literal in hub.known_secret_values())
        self.assertEqual(hub._SECRET_SHAPES, tuple(pattern for _, pattern in secrets.HUB_SECRET_SHAPES))

    def minimal_app(self):
        package = self.platform / "app"
        package.mkdir()
        (package / "__init__.py").write_text("")
        for name in ("forbidden_strings.py", "publication_secrets.py"):
            shutil.copyfile(ROOT / "app" / name, package / name)
        scanner = self.platform / "scripts" / "secret_scan.py"
        scanner.write_text(
            "import pathlib, sys\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n"
            "from app import forbidden_strings\n" + scanner.read_text()
        )

    def test_minimal_hook_import_and_literal_inventory_use_only_stdlib(self):
        self.minimal_app()
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        (self.repo / "sample").write_text(self.literal)
        probe = (
            "import pathlib, sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from app import forbidden_strings as gate\n"
            "repo = pathlib.Path(sys.argv[2])\n"
            "rules = gate.load_rules(gate.list_path(repo))\n"
            "value = (repo / 'sample').read_text()\n"
            "found = gate.scan_text(value, 'sample:1', rules)\n"
            "assert found and 'DEEPGRAM_API_KEY' in gate.block_message(found)\n"
            "assert value not in gate.block_message(found)\n"
            "assert {name for name in sys.modules if name.startswith('app.')} == "
            "{'app.forbidden_strings', 'app.publication_secrets'}\n"
        )
        result = subprocess.run([sys.executable, "-I", "-S", "-c", probe,
                                 str(self.platform), str(self.repo)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, "minimal gate must import and enforce literals without app runtime")

    def test_secret_mask_uses_shared_names_and_length(self):
        from app import secret_mask

        self.assertIs(secret_mask._SECRET_WORDS, secrets._SECRET_WORDS)
        self.assertEqual(secret_mask._MIN_LEN, secrets._MIN_LEN)
        self.assertTrue(self.literal not in secret_mask.mask_secrets("API_KEY=" + self.literal))
        self.assertEqual(secret_mask.mask_secrets("API_KEY=short"), "API_KEY=short")

    def test_generated_hook_ignores_foreign_venv_and_caller_python(self):
        self.minimal_app()
        foreign = self.repo / ".venv" / "bin"
        foreign.mkdir(parents=True)
        for name in ("python", "python3"):
            path = foreign / name
            path.write_text("#!/bin/sh\nexit 91\n")
            path.chmod(0o755)
        with patch.object(installer.sys, "executable", str(foreign / "python")), \
             patch.dict(os.environ, {"PATH": str(foreign) + os.pathsep + os.environ["PATH"]}):
            installer.install_hooks(self.repo, self.platform)
            hook = self.repo / ".git" / "hooks" / "pre-commit"
            self.assertTrue(str(foreign) not in hook.read_text())
            result = subprocess.run([str(hook)], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 23, "system Python must load the minimal gate despite foreign venv")

    def test_generated_hook_prefers_orchestra_venv(self):
        self.minimal_app()
        system_python = shutil.which("python3", path=os.defpath)
        self.assertIsNotNone(system_python)
        python = self.platform / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        marker = self.platform / "orchestra-python-used"
        python.write_text("#!/bin/sh\n: > " + shlex.quote(str(marker)) + "\nexec "
                          + shlex.quote(system_python) + ' "$@"\n')
        python.chmod(0o755)
        installer.install_hooks(self.repo, self.platform)
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        self.assertIn(str(python), hook.read_text())
        result = subprocess.run([str(hook)], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 23)
        self.assertTrue(marker.is_file())

    def test_installer_dispatches_existing_canonical_scanner_in_all_modes(self):
        paths = installer.install_hooks(self.repo, self.platform)
        for path, flags in zip(paths, (["--staged"], ["--commit-msg", "message-file"], ["--pre-push"])):
            self.assertIn(str(self.platform / "scripts" / "secret_scan.py"), path.read_text())
            result = subprocess.run([str(path), *flags[1:]], cwd=self.repo,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 23)
            self.assertEqual((self.repo / "scanner-args").read_text().splitlines(), flags)

    def test_generated_hooks_missing_scanner_fail_closed_and_name_cause(self):
        paths = installer.install_hooks(self.repo, self.platform)
        scanner = self.platform / "scripts" / "secret_scan.py"
        content = scanner.read_text()
        scanner.unlink()
        for hook in paths:
            with self.subTest(hook=hook.name):
                result = subprocess.run([str(hook), "message-file"], cwd=self.repo,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertTrue(result.stderr.startswith("secret-gate:"))
                self.assertIn(str(scanner), result.stderr)
        self.assertFalse((self.repo / "scanner-args").exists())
        scanner.write_text(content)
        for hook in paths:
            result = subprocess.run([str(hook), "message-file"], cwd=self.repo,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 23)

    def test_installer_cli_from_repository_with_existing_secret_scanner(self):
        shutil.copyfile(ROOT / "scripts" / "install_git_hooks.py",
                        self.platform / "scripts" / "install_git_hooks.py")
        result = subprocess.run([sys.executable, "scripts/install_git_hooks.py"], cwd=self.platform,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        hook = self.platform / ".git" / "hooks" / "pre-commit"
        self.assertIn(str(self.platform / "scripts" / "secret_scan.py"), hook.read_text())

    def test_versioned_hook_shims_dispatch_canonical_scanner(self):
        for name, flags in (("pre-commit", ["--staged"]),
                            ("commit-msg", ["--commit-msg", "message-file"]),
                            ("pre-push", ["--pre-push"])):
            result = subprocess.run(["sh", str(ROOT / "scripts" / "hooks" / name), *flags[1:]],
                                    cwd=self.platform, capture_output=True, text=True)
            self.assertEqual(result.returncode, 23)
            self.assertEqual((self.platform / "scanner-args").read_text().splitlines(), flags)

    def test_installer_idempotent_and_preserves_foreign_hooks(self):
        paths = installer.install_hooks(self.repo, self.platform)
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        self.assertEqual(installer.install_hooks(self.repo, self.platform), paths)
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])
        paths[0].chmod(0o644)
        installer.install_hooks(self.repo, self.platform)
        self.assertTrue(paths[0].stat().st_mode & 0o111)
        paths[1].write_text("#!/bin/sh\n# project hook\nexit 7\n")
        with self.assertRaisesRegex(installer.HookInstallError, "foreign hook preserved"):
            installer.install_hooks(self.repo, self.platform)
        self.assertIn("project hook", paths[1].read_text())

    def test_registered_scopes_install_and_foreign_scope_reports_error(self):
        catalog = self.platform / ".orchestra" / "projects.yaml"
        catalog.parent.mkdir()
        catalog.write_text(f'version: 1\ninclude_scopes: ["{self.repo}"]\n')
        paths = installer.install_registered_hooks(self.platform)
        self.assertEqual(len(paths), 6)
        self.assertEqual(installer.install_registered_hooks(self.platform), paths)
        foreign = self.repo / ".git" / "hooks" / "pre-push"
        foreign.write_text("project hook\n")
        with self.assertRaisesRegex(installer.HookInstallError, "foreign hook preserved"):
            installer.install_registered_hooks(self.platform)
        self.assertEqual(foreign.read_text(), "project hook\n")

    def test_redirects_and_symlinks_are_not_overwritten(self):
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        foreign = self.directory / "foreign"
        foreign.write_text("project hook\n")
        hook.symlink_to(foreign)
        with self.assertRaises(installer.HookInstallError):
            installer.install_hooks(self.repo, self.platform)
        self.assertTrue(hook.is_symlink())
        self.assertEqual(foreign.read_text(), "project hook\n")
        hook.unlink()
        self.git(self.repo, "config", "core.hooksPath", str(self.directory / "other-hooks"))
        with self.assertRaisesRegex(installer.HookInstallError, "core.hooksPath"):
            installer.install_hooks(self.repo, self.platform)

    def test_merge_worker_blocks_literal_without_changing_refs(self):
        from app import workspace
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        worker = self.directory / "worker"
        self.git(self.repo, "worktree", "add", "-q", "-b", "worker", str(worker))
        self.stage("first\n" + self.literal + "\n", repo=worker)
        head = self.snapshot(worker)
        base = self.git(self.repo, "rev-parse", "main")
        result = workspace.merge_worktree_to_main(str(worker), str(self.repo), target_branch="main")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "FORBIDDEN_STRING")
        self.assertIn("DEEPGRAM_API_KEY", result["error"])
        self.assertTrue(self.literal not in result["error"])
        self.assertEqual(self.git(self.repo, "rev-parse", "main"), base)
        self.assertEqual(self.git(worker, "rev-parse", "HEAD"), head)

    def test_merge_worker_allows_shape_mentions(self):
        from app import workspace

        worker = self.directory / "worker"
        self.git(self.repo, "worktree", "add", "-q", "-b", "worker", str(worker))
        self.stage("Documented example: " + self.shape + "\n", repo=worker)
        self.snapshot(worker, "mention " + self.shape)
        result = workspace.merge_worktree_to_main(str(worker), str(self.repo), target_branch="main")
        self.assertTrue(result["ok"], "merge must defer shape policy to the canonical scanner")
        self.assertTrue((self.repo / "note.txt").is_file())

    def test_inventory_refresh_and_read_failure(self):
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        self.assertTrue(self.rules())
        (self.repo / ".env").write_text("API_KEY=short\n")
        self.assertFalse(self.rules())
        (self.repo / ".env").unlink()
        (self.repo / ".env").mkdir()
        with self.assertRaises(OSError):
            self.rules()

    @unittest.skipUnless(SCANNER.is_file(), "canonical secret_scan.py excluded from worker upload")
    def test_real_secret_scanner_pre_push_uses_literal_rules(self):
        (self.platform / "app").mkdir()
        (self.platform / "app" / "__init__.py").write_text("")
        for name in ("forbidden_strings.py", "publication_secrets.py"):
            shutil.copyfile(ROOT / "app" / name, self.platform / "app" / name)
        shutil.copyfile(SCANNER, self.platform / "scripts" / "secret_scan.py")
        (self.repo / ".env").write_text(f"DEEPGRAM_API_KEY={self.literal}\n")
        self.stage("first\n" + self.literal + "\n")
        head = self.snapshot(self.repo)
        installer.install_hooks(self.repo, self.platform)
        result = subprocess.run([str(self.repo / ".git" / "hooks" / "pre-push")], cwd=self.repo,
                                input=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n",
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("DEEPGRAM_API_KEY", result.stdout + result.stderr)
        self.assertIn("note.txt", result.stdout + result.stderr)
        self.assertTrue(self.literal not in result.stdout + result.stderr)


class MutationTests(unittest.TestCase):
    def test_reverting_each_requested_guard_fails_its_behavioral_test(self):
        mutations = (
            ("app/publication_secrets.py", "PLATFORM_ROOT = Path(__file__).resolve().parents[1]",
             "from app import secret_mask\\nPLATFORM_ROOT = Path(__file__).resolve().parents[1]",
             "GateTests.test_minimal_hook_import_and_literal_inventory_use_only_stdlib"),
            ("scripts/install_git_hooks.py", 'return Path(system_python).resolve()',
             'return Path(sys.executable).absolute()',
             "GateTests.test_generated_hook_ignores_foreign_venv_and_caller_python"),
            ("scripts/install_git_hooks.py", 'python = hook_python(root)',
             'python = Path(shutil.which("python3", path=os.defpath)).resolve()',
             "GateTests.test_generated_hook_prefers_orchestra_venv"),
            ("app/forbidden_strings.py", "rules += publication_secrets.literal_rules(repo)", "pass",
             "GateTests.test_existing_scanner_load_path_adds_target_env"),
            ("app/forbidden_strings.py", "_RulePath(override, repo=repo)", "_RulePath(override, repo=None)",
             "GateTests.test_rule_paths_keep_project_context_when_interleaved"),
            ("app/publication_secrets.py", "if value in text", "if False and value in text",
             "GateTests.test_existing_scanner_load_path_adds_target_env"),
            ("app/publication_secrets.py", 'r"(?:[A-Za-z0-9+/=][\\r\\n]*){40,}"', 'r""',
             "GateTests.test_hub_pem_header_mentions_pass_but_body_requires_40_characters"),
            ("app/publication_secrets.py", "    names = [name for name, value in rules if value in text]",
             "    names = [name for name, value in rules if value in text]\\n"
             "    names.extend(name for name, pattern in HUB_SECRET_SHAPES if pattern.search(text))",
             "GateTests.test_scan_range_does_not_apply_hub_shapes"),
            ("app/publication_secrets.py",
             "    matches = [(name, text.find(value)) for name, value in rules if value in text]",
             "    matches = [(name, text.find(value)) for name, value in rules if value in text]\\n"
             "    matches.extend((name, match.start()) for name, pattern in HUB_SECRET_SHAPES "
             "if (match := pattern.search(text)))",
             "GateTests.test_merge_worker_allows_shape_mentions"),
            ("scripts/install_git_hooks.py", 'scanner = root / "scripts" / "secret_scan.py"',
             'scanner = root / "scripts" / "missing-scanner.py"',
             "GateTests.test_installer_dispatches_existing_canonical_scanner_in_all_modes"),
            ("scripts/hooks/pre-push", 'scan="$root/scripts/secret_scan.py"',
             'scan="$root/scripts/missing-scanner.py"',
             "GateTests.test_versioned_hook_shims_dispatch_canonical_scanner"),
            ("scripts/install_git_hooks.py",
             '            raise HookInstallError(f"foreign hook preserved: {path}; chain it explicitly before retrying")',
             '            pass', "GateTests.test_installer_idempotent_and_preserves_foreign_hooks"),
        )
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        for filename, original, replacement, test in mutations:
            with self.subTest(check=test), tempfile.TemporaryDirectory(dir=ARTIFACTS, prefix="mutation-") as tmp:
                directory = Path(tmp)
                for name in MODULES:
                    target = directory / "app" / name
                    target.parent.mkdir(exist_ok=True)
                    shutil.copyfile(ROOT / "app" / name, target)
                # Hub planning and workspace merges need their real runtime
                # imports. Keep the minimal hook-import mutants isolated above.
                if "hub_pem" in test or "merge_worker" in test:
                    shutil.copytree(ROOT / "app", directory / "app", dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("__pycache__"))
                (directory / "scripts").mkdir()
                shutil.copytree(ROOT / "scripts" / "hooks", directory / "scripts" / "hooks")
                shutil.copyfile(ROOT / "scripts" / "install_git_hooks.py",
                                directory / "scripts" / "install_git_hooks.py")
                (directory / "tests").mkdir()
                target_test = directory / "tests" / Path(__file__).name
                shutil.copyfile(__file__, target_test)
                source = directory / filename
                text = source.read_text()
                self.assertIn(original, text, "explicit mutation target disappeared")
                command = [sys.executable, str(target_test), test]
                environment = {**os.environ, "PYTHONPATH": str(directory)}
                control = subprocess.run(command, cwd=directory, capture_output=True,
                                         text=True, timeout=45, env=environment)
                self.assertEqual(control.returncode, 0, control.stderr)
                source.write_text(text.replace(original, replacement.replace("\\n", "\n")))
                # The control may have cached same-size source within this
                # filesystem's timestamp granularity; always load the mutant.
                for cache in directory.rglob("__pycache__"):
                    shutil.rmtree(cache)
                result = subprocess.run(command, cwd=directory, capture_output=True,
                                        text=True, timeout=45, env=environment)
                self.assertEqual(result.returncode, 1)
                self.assertIn("FAIL:", result.stderr, "must fail an assertion, not setup/import")
                self.assertNotIn("ERROR:", result.stderr, "mutation must not produce import/setup errors")


if __name__ == "__main__":
    unittest.main()
