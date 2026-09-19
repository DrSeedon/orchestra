"""Контракт корневых правил: один файл, под бюджетом, с полным оглавлением KB.

Claude Code 2.1.263 читает CLAUDE.md И AGENTS.md ОБА (проверено экспериментом 19.09.2026:
два файла с разными правилами — агент назвал оба и указал расхождение). Пока копия
существовала, она дважды разъезжалась с источником, и Claude-агенты не видели части правил
владельца. Поэтому тест сторожит ОТСУТСТВИЕ дубля, а не его синхронность.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_instruction_contract.py"
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path):
    shutil.copy(REPO / "AGENTS.md", tmp_path / "AGENTS.md")
    kb = tmp_path / ".orchestra" / "kb"
    kb.mkdir(parents=True)
    shutil.copy(REPO / ".orchestra" / "kb" / "README.md", kb / "README.md")
    for topic in (REPO / ".orchestra" / "kb").glob("*.md"):
        if topic.name != "README.md":
            shutil.copy(topic, kb / topic.name)
    return tmp_path


def _run(root: Path):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                          capture_output=True, text=True)


def test_single_source_passes(root):
    assert _run(root).returncode == 0


def test_claude_md_coming_back_is_rejected(root):
    """Дубль не «чинится синхронизацией» — он запрещён: агенту доезжают оба файла."""
    (root / "CLAUDE.md").write_text((root / "AGENTS.md").read_text(), encoding="utf-8")

    result = _run(root)

    assert result.returncode == 1
    assert "CLAUDE.md" in result.stderr


def test_duplicate_is_rejected_even_as_a_symlink(root):
    (root / "CLAUDE.md").symlink_to(root / "AGENTS.md")

    assert _run(root).returncode == 1


def test_oversized_rules_are_rejected(root):
    body = (root / "AGENTS.md").read_text(encoding="utf-8")
    (root / "AGENTS.md").write_text(body + "x" * 17_000, encoding="utf-8")

    result = _run(root)

    assert result.returncode == 1
    assert "16 KiB" in result.stderr


def test_unindexed_kb_topic_is_rejected(root):
    (root / ".orchestra" / "kb" / "brand-new-topic.md").write_text("# тема", encoding="utf-8")

    result = _run(root)

    assert result.returncode == 1
    assert "brand-new-topic" in result.stderr


def test_root_import_is_rejected(root):
    """Импорт в корне вернул бы нас к скрытому второму источнику правил."""
    body = (root / "AGENTS.md").read_text(encoding="utf-8")
    (root / "AGENTS.md").write_text(body + "\n@./extra-rules.md\n", encoding="utf-8")

    assert _run(root).returncode == 1
