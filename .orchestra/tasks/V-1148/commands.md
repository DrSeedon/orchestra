# V-1148 — выполненные офлайн-проверки

Команды запускались из корня worker copy. Исходники исследовались командами
`rg --files`, `rg -n` и `sed -n`; это статическое чтение, не тестовые прогоны.
Ниже точные команды проверок. Их выводы сохранены отдельно, без редактирования.
`TMPDIR` намеренно внутри task directory: conftest создаёт временный каталог уже
на collection. Все ожидания probe ограничены, polling/sleep loops не использованы.

## 1. Штатные регрессии

Вывод: `offline-tests.txt`.

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1148/tmp"
{ command -v uv
uv --version
uv run --frozen python -m pytest tests/test_codex_compact_state.py tests/test_backend_codex.py -q
result=$?
printf 'PYTEST_EXIT=%s\n' "$result"
} > .orchestra/tasks/V-1148/offline-tests.txt 2>&1
cat .orchestra/tasks/V-1148/offline-tests.txt
```

Результат pytest — exit 2. Shell wrapper завершился с 0, потому что последняя
команда `cat`; код **проверки**, а не wrapper-а — `PYTEST_EXIT=2` в выводе.

## 2. Вспомогательный синтетический probe

Первая версия (вывод теперь `synthetic-initial-failure.txt`) и исправленная версия
с шестью сценариями (теперь `synthetic-six-scenarios.txt`) запускались одинаково:

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1148/tmp"
{ uv run --frozen python .orchestra/tasks/V-1148/synthetic_probe.py
result=$?
printf 'PROBE_EXIT=%s\n' "$result"
} > .orchestra/tasks/V-1148/synthetic-output.txt 2>&1
cat .orchestra/tasks/V-1148/synthetic-output.txt
```

Перед вторым запуском исходный вывод сохранён командой:

```bash
mv .orchestra/tasks/V-1148/synthetic-output.txt .orchestra/tasks/V-1148/synthetic-initial-failure.txt
```

После добавления седьмого сценария выполнено:

```bash
mv .orchestra/tasks/V-1148/synthetic-output.txt .orchestra/tasks/V-1148/synthetic-six-scenarios.txt
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1148/tmp"
{ uv run --frozen python .orchestra/tasks/V-1148/synthetic_probe.py
result=$?
printf 'PROBE_EXIT=%s\n' "$result"
} > .orchestra/tasks/V-1148/synthetic-output.txt 2>&1
cat .orchestra/tasks/V-1148/synthetic-output.txt
```

Исполнялся только текущий исходник и task harness, без импорта `app.backend_codex`.
AST extraction не выполняет imports исходного файла или его полный constructor.
Фикстура задаёт минимальное backend state, а request заменён coroutine в памяти.
ACK observer оборачивает настоящий `_finish_compact_if_ready`, чтобы фиксировать
переход acknowledged, не меняя результат метода. Настоящие JSONL reader,
`JsonRpcStdioTransport._request`, event conversion, session и UI здесь не выполняются.
Никаких результатов штатных тестов на основании этого probe не заявляется.

## 3. Идентичность и синтаксис переданной копии

Вывод: `source-identity.txt`.

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1148/tmp"
uv run --frozen python - <<'PY' > .orchestra/tasks/V-1148/source-identity.txt 2>&1
import ast
import hashlib
from pathlib import Path
import app
root = Path.cwd()
print('HEAD=UNAVAILABLE: .git is absent in supplied worker copy' if not (root / '.git').exists() else 'HEAD=not inspected')
print('APP_FILE=' + repr(getattr(app, '__file__', None)))
print('APP_NAMESPACE_PATH=' + repr(list(app.__path__)))
for relative in ('app/__init__.py', 'app/runtime_process_group.py', 'app/backend_jsonrpc.py', 'app/events.py', 'app/runtime_history.py', 'app/usage_contract.py', 'app/session_state.py', 'app/db.py', 'scripts/run_tests.py'):
    print('PRESENT ' + relative + '=' + str((root / relative).exists()))
paths = sorted([*Path('app').rglob('*.py'), *Path('tests').rglob('*.py')])
for path in paths:
    raw = path.read_bytes()
    ast.parse(raw, filename=str(path))
    print('SHA256 ' + path.as_posix() + '=' + hashlib.sha256(raw).hexdigest())
print('PARSE_OK=' + str(len(paths)))
PY
cat .orchestra/tasks/V-1148/source-identity.txt
```

## 4. Финальная проверка артефактов

Первый запуск validator ошибочно захватил заголовок следующей таблицы при
проверке числа колонок. Его неизменённый вывод сохранён в
`validation-initial-failure.txt`. Исправлен только task validator: диапазон
первой таблицы ограничен пустой строкой. Повторный вывод — `validation-output.txt`.

Оба запуска использовали:

```bash
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1148/tmp"
{ uv run --frozen python .orchestra/tasks/V-1148/validate_artifacts.py
result=$?
printf 'VALIDATION_EXIT=%s\n' "$result"
} > .orchestra/tasks/V-1148/validation-output.txt 2>&1
cat .orchestra/tasks/V-1148/validation-output.txt
```

Перед повтором выполнено:

```bash
mv .orchestra/tasks/V-1148/validation-output.txt .orchestra/tasks/V-1148/validation-initial-failure.txt
```

Итог: девять хешей исходников/существующих тестов совпали; синтаксис task Python
и требуемые восемь колонок/семь строк таблицы проверены; распространённых форм
секретов в task artifacts не найдено. Это ограниченный shape scan, не доказательство
отсутствия любых возможных секретов. Проверка не читала внешние файлы или журналы.
