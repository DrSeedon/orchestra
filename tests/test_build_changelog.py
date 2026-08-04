"""#52 — сборка CHANGELOG из отчётов: ничего не переписывает, ничего не дублирует."""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build-changelog.py"


@pytest.fixture
def repo(tmp_path):
    """Мини-репозиторий с тем же расположением файлов, что у проекта."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "build-changelog.py").write_text(SCRIPT.read_text())
    (tmp_path / "docs" / "tasks").mkdir(parents=True)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.2.3 — старое\n- запись, которую вели руками\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path)
    return tmp_path


def _task(repo, task_id, first_line):
    d = repo / "docs" / "tasks" / str(task_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text(f"{first_line}\n\nтело отчёта\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", f"#{task_id}"], cwd=repo, capture_output=True)


def _run(repo, *args):
    return subprocess.run(
        [sys.executable, "scripts/build-changelog.py", *args],
        cwd=repo, capture_output=True, text=True,
    )


def test_dry_run_changes_nothing(repo):
    _task(repo, 61, "# #61 — отчёт: возврат на смерженную ветку проходит")
    before = (repo / "CHANGELOG.md").read_text()
    out = _run(repo)
    assert "Будет добавлено записей: 1" in out.stdout
    assert (repo / "CHANGELOG.md").read_text() == before, "сухой прогон не пишет"


def test_write_prepends_and_keeps_history_untouched(repo):
    _task(repo, 61, "# #61 — отчёт: возврат на смерженную ветку проходит")
    _run(repo, "--write")
    text = (repo / "CHANGELOG.md").read_text()
    print("\nПОСЛЕ СБОРКИ:\n" + text)
    assert "- запись, которую вели руками" in text, "ручную историю трогать нельзя"
    assert text.index("#61") < text.index("## v1.2.3"), "новое сверху"
    assert "ниже — велось вручную" in text


def test_second_run_does_not_duplicate(repo):
    _task(repo, 61, "# #61 — отчёт: раз")
    _run(repo, "--write")
    out = _run(repo)
    assert "Новых задач для changelog нет." in out.stdout
    # Смысл проверки — отсутствие дубля: строка записи ровно одна
    assert (repo / "CHANGELOG.md").read_text().count("- **#61**") == 1


def test_unreadable_title_is_named_not_swallowed(repo):
    _task(repo, 42, "# Implementation report")
    out = _run(repo)
    print("\nПРОПУСК:", [l for l in out.stdout.splitlines() if "42" in l])
    assert "Пропущено" in out.stdout and "#42" in out.stdout
    assert "Новых задач для changelog нет." in out.stdout


def test_seed_marks_everything_as_history(repo):
    """Отсечка при переходе: старое не дублируется, новое после неё — попадает."""
    _task(repo, 10, "# #10 — отчёт: старая задача")
    _run(repo, "--seed", "--write")
    assert "Новых задач для changelog нет." in _run(repo).stdout

    _task(repo, 11, "# #11 — отчёт: новая задача")
    out = _run(repo)
    assert "Будет добавлено записей: 1" in out.stdout and "#11" in out.stdout


def test_version_is_assigned_at_build_not_by_worker(repo):
    _task(repo, 61, "# #61 — отчёт: раз")
    _run(repo, "--write")
    assert "## v1.2.4" in (repo / "CHANGELOG.md").read_text()
    _task(repo, 62, "# #62 — отчёт: два")
    _run(repo, "--write", "--version", "v2.0.0")
    assert "## v2.0.0" in (repo / "CHANGELOG.md").read_text()
