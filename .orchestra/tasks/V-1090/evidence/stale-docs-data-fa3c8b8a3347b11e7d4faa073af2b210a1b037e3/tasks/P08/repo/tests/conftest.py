import os

import pytest


def write_file(root, rel, content):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return full


@pytest.fixture
def workdir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def source(workdir):
    src = os.path.join(workdir, "src")
    write_file(src, "notes.txt", "hello\n")
    write_file(src, "docs/plan.md", "# plan\n")
    return src


@pytest.fixture
def backup_root(workdir):
    root = os.path.join(workdir, "backups")
    os.makedirs(root)
    return root
