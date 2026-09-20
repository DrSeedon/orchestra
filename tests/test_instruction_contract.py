"""Контракт корневых правил: ровно один корневой файл, бюджет и полное оглавление KB.

Codex читает `AGENTS.md` сам, Claude Code — модом `agents-md`, включённым на машине
(`~/.claude/mods`, `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`); проверено прогоном с
отключёнными файловыми инструментами и положительным контролем. Пока рядом лежал второй
корневой файл, он дважды разъехался с источником, и один раз Claude-агенты работали на
устаревших правилах владельца. Тест сторожит отсутствие второго файла, а не равенство байтов.
"""
import os
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
    for topic in (REPO / ".orchestra" / "kb").glob("*.md"):
        shutil.copy(topic, kb / topic.name)
    return tmp_path


def _run(root: Path):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                          capture_output=True, text=True)


def test_single_root_file_passes(root):
    assert _run(root).returncode == 0


def test_copy_beside_the_source_is_rejected(root):
    """Копия — это второй источник правды: он разъедется, и никто не заметит."""
    (root / "CLAUDE.md").write_text((root / "AGENTS.md").read_text(encoding="utf-8"),
                                    encoding="utf-8")

    result = _run(root)

    assert result.returncode == 1
    # Не просто «упало»: проверка обязана назвать причину. Ловушка, на которую я попался
    # в прошлой редакции: pytest кладёт tmp_path в каталог с именем теста, и подстрока
    # находилась в ПУТИ из сообщения об ошибке — тест зеленел на любом падении.
    assert "must not exist beside" in result.stderr


def test_symlink_beside_the_source_is_rejected(root):
    """Симлинк тоже запрещён: правила читаются из AGENTS.md напрямую."""
    (root / "CLAUDE.md").symlink_to("AGENTS.md")

    result = _run(root)

    assert result.returncode == 1
    assert "must not exist beside" in result.stderr


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
