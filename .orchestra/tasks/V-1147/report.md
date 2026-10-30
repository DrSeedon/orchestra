# V-1147 — hub_preamble: корректный JSON примера send_message

## Изменения

- `app/backend_hub.py`: изменён порядок одного выражения. Сначала разворачиваются
  двойные скобки `OUTBOX_SECTION`, затем вставляется уже сформированная f-строка
  `send`. Повторное сворачивание её конечных `}}` исключено.
- `tests/test_hub_workspace.py`: добавлен разбор настоящих JSON code spans из
  `<orchestra-link>` через `json.loads` и `parse_outbox`. Шесть сочетаний
  `has_link=False/True` и `parent_name='synthetic-parent'/''/None` проверяют точный
  набор доступных инструментов. Примеры выполняются через `ob.execute` с `_Calls`,
  который только записывает запросы в память. Проверяются тело сообщения, адресат,
  sender/scope, собственные progress/checklist и их аргументы.
- В `test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools` удалены буквальные
  assertions `goes to your orchestrator boss only`,
  `Do not run git push/clone/commit`, грамматика роли и текстовый разделитель задачи.
  Сохранены проверки идентичности/ветки, наличия outbox, точного набора инструментов,
  сборки `backend._preamble() + заданный текст`, компактности и отсутствия native MCP.
  Другие тесты и промпты не переписаны.
- Обновлён `CHANGELOG.md`. `app/hub_outbox.py`, validation и ownership не менялись.

## Среда и ограничения

Частичная копия без `.git`. В `app/` предоставлены только `backend_hub.py` и
`hub_outbox.py`; нет `app.hub_workspace`, остальных зависимостей backend, настоящего
pipeline/worker prompt и `scripts/run_tests.py`. Provisioned runner доступен:
`uv 0.11.28 (x86_64-unknown-linux-gnu)`. Все Python-команды ниже выполнены им,
с lock-файлом без изменений, в стандартной `.venv`, с `UV_OFFLINE=1`.
Сеть, модельные вызовы и настоящая отправка сообщений не использовались.

Импортированный `app` — namespace package: `app.__file__ = None`, абсолютный
`app.__path__`:
`/home/<REMOTE_IDENTIFIER>/orchestra-ws/vmi3407579/hub-f5836ca1beef480b/app`.
Обычный импорт `app.backend_hub` блокируется отсутствием `app.hub_workspace`.

Первый пробный сбор (до задания TMPDIR) запускал штатный conftest со стандартным
tempfile-каталогом. Последующие pytest-команды направляли временные файлы внутрь
каталога задачи. Это отклонение первого запуска от ограничения рабочей папки.

## Команды и результаты

В каждом тестовом shell:

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
mkdir -p .orchestra/tasks/V-1147/tmp
export TMPDIR="$PWD/.orchestra/tasks/V-1147/tmp"
```

1. Первичный штатный запуск (ещё без TMPDIR):

   ```bash
   UV_OFFLINE=1 uv run --frozen python -m pytest tests/test_hub_workspace.py -k 'hub_prompt_without_a_parent' -q
   ```

   Exit 2, collection error: `cannot import name 'hub_workspace' from 'app'`.

2. Дополнительная изолированная проверка ДО исправления:

   ```bash
   UV_OFFLINE=1 uv run --frozen python -m pytest .orchestra/tasks/V-1147/test_preamble_isolated.py --confcutdir=.orchestra/tasks/V-1147 -q > .orchestra/tasks/V-1147/original-defect.log 2>&1
   ```

   Exit 1: **2 failed, 16 passed**. Оба падения — реальный сгенерированный
   `{"tool":"send_message","args":{"message":"..."}` при synthetic-parent/link;
   `JSONDecodeError: Expecting ',' delimiter`, column 48.

3. Та же проверка ПОСЛЕ исправления:

   ```bash
   UV_OFFLINE=1 uv run --frozen python -m pytest .orchestra/tasks/V-1147/test_preamble_isolated.py --confcutdir=.orchestra/tasks/V-1147 -q > .orchestra/tasks/V-1147/fixed.log 2>&1
   ```

   Exit 0: **18 passed**. Дополнительный harness извлекает AST-определения реальных
   `hub_preamble`, parser/executor и неизменённые тестовые функции из исходников,
   включая новую регрессию и существующие проверки parser/ownership/аргументов.
   Каждый тест проходит с отсутствующим шаблоном роли и с синтетическим шаблоном.
   Отсутствующие pipeline/prompt formatter и receipt predicate заменены синтетикой;
   UV-инструкция пуста. Это проверка функций из исходников, **не замена штатному
   интеграционному прогону** и не проверка реального delivery receipt.

4. Возврат исходного дефекта в AST без изменения файла генератора и теста:

   ```bash
   UV_OFFLINE=1 V1147_ORIGINAL_DEFECT=1 uv run --frozen python -m pytest .orchestra/tasks/V-1147/test_preamble_isolated.py --confcutdir=.orchestra/tasks/V-1147 -q > .orchestra/tasks/V-1147/mutation.log 2>&1
   ```

   Exit 1: **2 failed, 16 passed** с тем же JSONDecodeError. Harness проверяет,
   что заменено ровно одно исправленное выражение на исходное. Новая регрессия,
   передаваемая брокеру для коммита, не меняется между зелёным и красным прогонами.

5. Повторный штатный запуск всего выбранного файла после исправления:

   ```bash
   UV_OFFLINE=1 uv run --frozen python -m pytest tests/test_hub_workspace.py -q > .orchestra/tasks/V-1147/required-pytest.log 2>&1
   ```

   Exit 2: та же ошибка collection. Не выполнены штатная новая регрессия,
   изменённый интеграционный trimmed-prompt test и остальные тесты этого файла.
   Полный suite также недоступен: не скопирован `scripts/run_tests.py`.

6. Проверка происхождения `app` и компиляции изменённых Python-файлов:

   ```bash
   UV_OFFLINE=1 uv run --frozen python -c 'import app; from pathlib import Path; print("app.__file__ =", app.__file__); print("app.__path__ =", [str(Path(p).resolve()) for p in app.__path__]); paths = ["app/backend_hub.py", "tests/test_hub_workspace.py", ".orchestra/tasks/V-1147/test_preamble_isolated.py"]; [compile(Path(p).read_text(), p, "exec") for p in paths]; print("compile: 3 files OK")'
   ```

   Exit 0, `compile: 3 files OK`.

## Регрессии и передача

Прежние данные outbox не переписываются: меняется только новый пример в preamble.
Существующие проверки отказа без родителя, игнорирования чужого `to`/`file_path`,
поддельного delivery_id, неверных аргументов и недоступных инструментов проходят
в дополнительном harness. Recovery/sync-back, полная сборка prompt и broker commit
остаются на проверку в полной копии оркестратора. Изменение stateless и не требует
миграции; сервисы не запускались и не перезапускались.

Исходник, тесты и артефакты просмотрены; реальных секретов в них нет. Git-команд
не выполнялось. Обязательный коммит на `task-V-1147/fix-hub-outbox-example` делает
брокер после завершения этого хода; из копии подтвердить его hash невозможно.

Parent publication normalization: forbidden remote identifiers in report/logs were replaced with `<REMOTE_IDENTIFIER>`; original evidence is retained privately. Source and tests are unchanged.
