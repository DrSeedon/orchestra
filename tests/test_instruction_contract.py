"""Контракт корневых правил: один файл, симлинк рядом, бюджет и полное оглавление KB.

Claude Code CLI с модом `agents-md` читает `AGENTS.md` сам, но наши Claude-сессии идут не
через CLI, а через Agent SDK (воркеры Orchestra и бот Кеши), и SDK грузит только `CLAUDE.md`:
ни `setting_sources`, ни `plugins` мод туда не приносят (прогон 20.09.2026). Codex читает
только `AGENTS.md`. Пока рядом лежали две КОПИИ, они дважды разъехались, и один раз
Claude-агенты не видели правил владельца. Симлинк разойтись не может физически — тест
сторожит именно его, а не равенство байтов.
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
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    kb = tmp_path / ".orchestra" / "kb"
    kb.mkdir(parents=True)
    for topic in (REPO / ".orchestra" / "kb").glob("*.md"):
        shutil.copy(topic, kb / topic.name)
    return tmp_path


def _run(root: Path):
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                          capture_output=True, text=True)


def test_symlink_beside_the_source_passes(root):
    assert _run(root).returncode == 0


def test_copy_instead_of_symlink_is_rejected(root):
    """Копия — это второй источник правды: он разъедется, и никто не заметит."""
    link = root / "CLAUDE.md"
    link.unlink()
    link.write_text((root / "AGENTS.md").read_text(encoding="utf-8"), encoding="utf-8")

    result = _run(root)

    assert result.returncode == 1
    # Не просто «упало»: проверка обязана назвать причину. Ловушка, на которую я попался:
    # pytest кладёт tmp_path в каталог с именем теста, и подстрока "symlink" находилась
    # в ПУТИ из сообщения об ошибке — тест зеленел на любом падении.
    assert "must be a symlink" in result.stderr


def test_missing_link_is_rejected(root):
    """Без CLAUDE.md Claude-агенты остаются вообще без правил проекта — молча."""
    (root / "CLAUDE.md").unlink()

    assert _run(root).returncode == 1


def test_link_pointing_elsewhere_is_rejected(root):
    (root / "other.md").write_text("# чужие правила", encoding="utf-8")
    (root / "CLAUDE.md").unlink()
    (root / "CLAUDE.md").symlink_to("other.md")

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
