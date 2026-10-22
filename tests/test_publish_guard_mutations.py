"""Each committed mutation of the guard code must redden tests/test_publish_guard.py (V-1014)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# (module, original fragment, mutated fragment)
MUTATIONS = [
    ("publication_secrets.py", "if value in text", "if False and value in text"),
    ("forbidden_strings.py", 'added.append(line[1:])', 'added.append("")'),
    ("forbidden_strings.py", '    return list(dict.fromkeys(found))', '    return []'),
    ("private_folder.py", "link.symlink_to(shared, target_is_directory=True)", "link.mkdir()"),
    ("workspace.py", "                    if guard:\n", "                    if False:\n"),
    ("private_folder.py", "return Path(done.stdout.strip()).parent", "return Path(path)"),
]


@pytest.mark.parametrize("module,old,new", MUTATIONS)
def test_mutation_reddens_guard_tests(tmp_path, module, old, new):
    package = tmp_path / "app"
    shutil.copytree(ROOT / "app", package, ignore=shutil.ignore_patterns("__pycache__"))
    source = (package / module).read_text()
    assert old in source, "mutation target vanished — update MUTATIONS"
    (package / module).write_text(source.replace(old, new, 1))
    # Copy the test too: run in place, pytest's rootdir would put the real `app` first.
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "tests" / "test_publish_guard.py", tmp_path / "tests" / "test_guard_copy.py")
    shutil.copy(ROOT / "scripts" / "secret_scan.py", tmp_path / "scripts" / "secret_scan.py")
    run = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "tests" / "test_guard_copy.py"),
         "-q", "--noconftest", "-p", "no:cacheprovider", "-x"],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "HOME": str(tmp_path)},
    )
    assert run.returncode != 0, run.stdout[-800:]
