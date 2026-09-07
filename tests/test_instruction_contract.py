from pathlib import Path
import subprocess
import sys

import pytest

from scripts.check_instruction_contract import MAX_INSTRUCTION_BYTES, check, sync


@pytest.fixture
def root(tmp_path):
    kb = tmp_path / ".orchestra/kb"
    kb.mkdir(parents=True)
    (kb / "README.md").write_text("- [runtime](runtime.md) — Runtime: запуск и ошибки\n")
    (kb / "runtime.md").write_text("# Runtime\nDetails remain on demand.\n")
    (tmp_path / "AGENTS.md").write_text("# Rules\nNever restart without authority.\n")
    (tmp_path / "CLAUDE.md").write_text("old copy")
    sync(tmp_path)
    return tmp_path


def test_sync_mirrors_the_source_without_inlining_the_topic_index(root):
    check(root)
    source = (root / "AGENTS.md").read_bytes()
    assert (root / "CLAUDE.md").read_bytes() == source
    assert b"Never restart without authority." in source
    # The topic list is injected by the platform (app.kb_index), so neither the topic
    # description nor its body may appear in the committed rules.
    assert "Runtime: запуск и ошибки" not in source.decode()
    assert b"Details remain on demand" not in source
    before = [(root / name).stat().st_mtime_ns for name in ("AGENTS.md", "CLAUDE.md")]
    sync(root)
    assert before == [(root / name).stat().st_mtime_ns for name in ("AGENTS.md", "CLAUDE.md")]


def test_one_sided_edit_is_rejected_without_repair(root):
    target = root / "CLAUDE.md"
    target.write_bytes(target.read_bytes() + b"\nOne-sided rule")
    before = target.read_bytes()
    with pytest.raises(ValueError, match="differ"):
        check(root)
    assert target.read_bytes() == before


def test_unindexed_topic_is_rejected_but_needs_no_root_edit(root):
    kb = root / ".orchestra/kb"
    (kb / "network.md").write_text("# Network")
    with pytest.raises(ValueError, match="missing from README"):
        check(root)
    before = (root / "AGENTS.md").read_bytes()
    index = kb / "README.md"
    index.write_text(index.read_text() + "- [network](network.md) — Сеть: диагностика\n")
    check(root)
    assert (root / "AGENTS.md").read_bytes() == before


def test_equal_utf8_bloat_is_rejected_and_sync_does_not_touch_other_copy(root):
    source = root / "AGENTS.md"
    source.write_text(source.read_text() + "я" * (MAX_INSTRUCTION_BYTES // 2))
    before = (root / "CLAUDE.md").read_bytes()
    with pytest.raises(ValueError, match="budget"):
        sync(root)
    assert (root / "CLAUDE.md").read_bytes() == before
    (root / "CLAUDE.md").write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="budget"):
        check(root)


@pytest.mark.parametrize("mutation", ["empty", "import", "broken_link", "duplicate", "description"])
def test_invalid_sources_fail_before_writes(root, mutation):
    source = root / "AGENTS.md"
    index = root / ".orchestra/kb/README.md"
    (root / "CLAUDE.md").write_text("stale mirror")
    if mutation == "empty":
        source.write_text("")
    elif mutation == "import":
        source.write_text(source.read_text() + "\nRead @archive.md now.\n")
    elif mutation == "broken_link":
        index.write_text(index.read_text().replace("(runtime.md)", "(missing.md)"))
    elif mutation == "duplicate":
        index.write_text(index.read_text() * 2)
    else:
        index.write_text("- [runtime](runtime.md) —    \n")
    before = (source.read_bytes(), (root / "CLAUDE.md").read_bytes())
    with pytest.raises(ValueError):
        sync(root)
    assert before == (source.read_bytes(), (root / "CLAUDE.md").read_bytes())


def test_ci_command_fails_on_drift(root):
    (root / "CLAUDE.md").write_text("different")
    script = Path(__file__).parents[1] / "scripts/check_instruction_contract.py"
    result = subprocess.run([sys.executable, str(script), "--root", str(root)], capture_output=True, text=True)
    assert result.returncode == 1
    assert "differ" in result.stderr
