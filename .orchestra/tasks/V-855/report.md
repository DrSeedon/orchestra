# V-855 — изоляция pytest в чужих worktree

## Причина и выбранный вариант

Корневой `pyproject.toml` Orchestra задавал `addopts = ["-m", "not live_probe", "-n", "2", "--dist=loadscope"]`. Для чужого вложенного worktree без локального pytest-конфига pytest поднимался к `/home/kesha/orchestra/pyproject.toml`; интерпретатор проекта без xdist завершался с `unrecognized arguments: -n --dist=loadscope`. Это подтверждено bug-inbox записью `20261014T123936.749078Z-a6213d44871b4bd1a01ec56a61719f27.md` и мутацией регрессионного теста.

Выбран составной вариант. Общие pytest-настройки удалены из Orchestra `pyproject.toml`; локальный полный runner `scripts/run_tests.py` и CI явно задают `-n 2 --dist=loadscope`, а merge-gate включает xdist и Orchestra-маркеры только для worktree с тем же Git common-dir, что и Orchestra. Гейт всегда задаёт `--rootdir` и `-c` из корня целевого проекта. Если проектного конфига нет, на время запуска создаётся пустой `pytest.ini` в изолированном временном каталоге. Один `--rootdir` проблему не решал: pytest всё равно выбрал родительский Orchestra `pyproject.toml`; явный `-c` остановил это наследование.

Так локальный и CI полный прогон сохраняют измеренный в V-847 xdist-режим, а bare pytest и gate чужого проекта не получают флаги Orchestra. `tests/conftest.py` регистрирует локальные маркеры после удаления их конфигурации из pyproject.

## Проверки

- `uv run --frozen python -m pytest --rootdir=. -c pyproject.toml -q tests/test_merge_test_gate.py` — **52 passed in 34.93s**. Проверены обнаружение Orchestra worktree, отсутствие xdist-флагов у чужого проекта, отдельный rootdir/inifile и существующие сценарии гейта.
- Мутация после коммита регрессионного теста принудительно включала `orchestra_project=True` для любого worktree. `test_foreign_nested_worktree_gets_no_orchestra_pytest_options` покраснел: fake-интерпретатор без xdist получил `unrecognized arguments: -n --dist=loadscope`. Мутация отменена; тест проходит в полном модуле.
- Живой worktree `/home/kesha/orchestra/worktrees/home-kesha-projects-kesha-tg-bot/feat-bg-listener` проверен своим интерпретатором `/home/kesha/projects/kesha-tg-bot/.venv/bin/python` на `tests/test_activity_ingress.py`, `tests/test_background_turns.py`, `tests/test_mid_turn_steer.py`, `tests/test_preventive_compact.py`: **40 passed in 8.70s**. Запуск без Orchestra-флагов выбрал `rootdir` worktree и его `pytest.ini`; в списке плагинов xdist отсутствовал, usage error не возник. Для этого набора нужен `PYTHONPATH=.`: без него две коллекции не находили `tests.sdk_echo`/`tests.test_background_turns`; повтор с корнем проекта в `PYTHONPATH` прошёл. Ни один файл в репозитории kesha-tg-bot не менялся; его worktree остался чистым.
- `git diff --check` прошёл.

## Изменённые файлы

`pyproject.toml`, `scripts/run_tests.py`, `.github/workflows/ci.yml`, `app/merge_test_gate.py`, `tests/conftest.py`, `tests/test_merge_test_gate.py`, `AGENTS.md`, `CHANGELOG.md`.

Изменение `app/merge_test_gate.py` — Python-код живого процесса; после слияния нужен рестарт, инициированный владельцем.
