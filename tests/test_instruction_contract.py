from pathlib import Path
import subprocess
import sys

import pytest

from scripts.check_instruction_contract import (
    INDEX_END, INDEX_START, MAX_INSTRUCTION_BYTES, check, sync,
)


@pytest.fixture
def root(tmp_path):
    kb = tmp_path / ".orchestra/kb"
    kb.mkdir(parents=True)
    (kb / "README.md").write_text("- [runtime](runtime.md) — Runtime: запуск и ошибки\n")
    (kb / "runtime.md").write_text("# Runtime\nDetails remain on demand.\n")
    (tmp_path / "AGENTS.md").write_text(
        f"# Rules\nNever restart without authority.\n{INDEX_START}\n{INDEX_END}\n"
    )
    (tmp_path / "CLAUDE.md").write_text("old copy")
    sync(tmp_path)
    return tmp_path


def test_sync_produces_identical_rules_with_current_topic_description(root):
    check(root)
    source = (root / "AGENTS.md").read_bytes()
    assert (root / "CLAUDE.md").read_bytes() == source
    assert b"Never restart without authority." in source
    assert "[Runtime: запуск и ошибки](.orchestra/kb/runtime.md)" in source.decode()
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


def test_new_topic_requires_description_then_sync_updates_both_roots(root):
    kb = root / ".orchestra/kb"
    (kb / "network.md").write_text("# Network")
    with pytest.raises(ValueError, match="missing from README"):
        check(root)
    index = kb / "README.md"
    index.write_text(index.read_text() + "- [network](network.md) — Сеть: диагностика\n")
    with pytest.raises(ValueError, match="stale"):
        check(root)
    sync(root)
    check(root)
    for name in ("AGENTS.md", "CLAUDE.md"):
        assert "[Сеть: диагностика](.orchestra/kb/network.md)" in (root / name).read_text()


def test_changed_description_is_not_silently_cached(root):
    index = root / ".orchestra/kb/README.md"
    index.write_text(index.read_text().replace("запуск и ошибки", "восстановление"))
    with pytest.raises(ValueError, match="stale"):
        check(root)
    sync(root)
    assert "восстановление" in (root / "CLAUDE.md").read_text()


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


@pytest.mark.parametrize("mutation", ["empty", "import", "broken_link", "duplicate", "description", "markers"])
def test_invalid_sources_fail_before_writes(root, mutation):
    source = root / "AGENTS.md"
    index = root / ".orchestra/kb/README.md"
    if mutation == "empty":
        source.write_text("")
    elif mutation == "import":
        source.write_text(source.read_text() + "\nRead @archive.md now.\n")
    elif mutation == "broken_link":
        index.write_text(index.read_text().replace("(runtime.md)", "(missing.md)"))
    elif mutation == "duplicate":
        index.write_text(index.read_text() * 2)
    elif mutation == "description":
        index.write_text("- [runtime](runtime.md) —    \n")
    else:
        source.write_text(source.read_text() + INDEX_START)
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
