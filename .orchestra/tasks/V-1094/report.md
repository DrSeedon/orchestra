# V-1094 — Hub finish marker noise

Производная публикационная копия (sanitized): приватный runtime prefix заменён
на `<HUB_WORKSPACE>`. Оригиналы всех четырёх артефактов сохранены root приватно
с побайтной/SHA-проверкой; `app-import.log` также является производным sanitized-логом.

Исправлен только error-watch: `collect_db_events` сохраняет `type` и `tool_name`.
Общая событийная классификация для aggregate и post_fix_verdict считает шумом
строго `source=logs`, `type=tool_result`, `tool_name=hub`, сырой текст `(not finished)`.
Классификация одной лишь текстовой сигнатуры этот текст по-прежнему не исключает.
Агрегация разделяет шум и реальные ошибки до проверки порога.

Производственный вред, названный до тестов: ложные тревоги на служебное закрытие
Hub и риск скрыть настоящие ошибки команд/ходов агента с тем же текстом.
Регрессии используют синтетическую SQLite и реальный локальный HubActivityStream
для получения маркера. Проверены граница 9/10 настоящих ошибок рядом с 10 маркерами,
noise reporting, post-fix и повторный scan с сохранённым состоянием, завершение окна,
ошибки Bash, failed Hub turn, отсутствие/неполнота provenance, иной тип/инструмент,
варианты пробелов и дополнительный текст. Существующий тест unfinished tools не изменён.
В старой scope-фикстуре добавлена существующая в production колонка tool_name;
её assertions сохранены.

Нетривиальная деталь: normalize_signature схлопывает пробелы и переводы строк.
Поэтому точность маркера проверяется по сырому message до объединения групп;
варианты с пробелом/переводом строки остаются настоящими кандидатами даже при
одинаковой нормализованной сигнатуре. События прежних вызывающих без новых полей
тоже остаются кандидатами. State-файл и DB-схема не менялись.

## Фактическая проверка

В каждом shell использован provisioned runner, без другого интерпретатора:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1094/tmp"
uv --version
uv run --frozen python -m pytest tests/test_error_watch.py tests/test_hub_workspace.py::test_activity_stream_ignores_other_runs_and_closes_unfinished_tools -q > .orchestra/tasks/V-1094/pytest.log 2>&1
uv run --frozen python scripts/check_instruction_contract.py > .orchestra/tasks/V-1094/instruction-contract.log 2>&1
uv run --frozen python -c 'import app; print(app.__file__)' > .orchestra/tasks/V-1094/app-import.log 2>&1
```

- uv: 0.11.28; default `.venv`, frozen lock, без замены зависимостей.
- Полный `tests/test_error_watch.py` + существующий HubActivityStream regression:
  **69 passed**, итоговый прогон 3.41 s (первый прогон также 69 passed).
- Импорт app (производный sanitized-путь; оригинал сохранён root приватно):
  `<HUB_WORKSPACE>/app/__init__.py`.
- Instruction contract: exit 1, точный blocker:
  `CLAUDE.md must be a symlink to AGENTS.md, not a copy: a copy drifts and then one client silently runs on stale rules`.
  В hub-копии `CLAUDE.md` отсутствует; его не создавал и контракт не ослаблял.
  Полная native-проверка контракта остаётся root.

Изменены `app/error_watch.py`, `tests/test_error_watch.py`, handwritten CHANGELOG
и артефакты этой задачи. HubActivityStream, исходные логи, DB-схема, квоты,
privacy/guards не менялись. Внешние вызовы, live provider turns, боевую БД,
рестарты и record-fix не запускал. Тесты выполнялись на синтетических данных;
каноническая приёмка и mutant остаются root. В копии нет `.git`: коммит/перенос
делает платформа, merge/push — root. Проверены изменённые участки исходников;
Git diff здесь недоступен. Временные тестовые данные удалены после проверки.
