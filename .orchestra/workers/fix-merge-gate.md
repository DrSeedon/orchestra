# fix-merge-gate — личная память

## Археология merge-gate: смотреть в БД, а не реконструировать

`merge_operations.result_json` в живой `data/orchestra.db` содержит `test_gate` целиком —
точный список отображённых файлов, `status`, `reason` и **сохранённый выход pytest**, а
`started_at`/`finished_at` дают настоящий wall-clock. Это на порядок лучше, чем восстанавливать
набор через `select_tests` по смерженному коммиту (squash показывает итог, а не то, что видел гейт).

```bash
python - <<'EOF'
import sqlite3, json
c=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro",uri=True)
c.row_factory=sqlite3.Row
for r in c.execute("select * from merge_operations where result_json like '%test_gate%'"):
    tg=(json.loads(r["result_json"]).get("test_gate") or {})
EOF
```

Читать только `mode=ro` через URI. 178 операций за ~3 дня — выборка достаточная для процентов.

## Замер времени на этом VPS

Wall-clock здесь **непригоден без записи нагрузки рядом**. Один и тот же тест-файл дал
14.3 → 149.5 с (10.5×), один и тот же набор — 456 / 465 / 593 с. Причина — чужие полные сьюты
(`feat-hot-reload` гонял три параллельно, load average 15–17 на 8 ядрах).
Всегда писать `cut -d' ' -f1-3 /proc/loadavg` до и после прогона в тот же файл с результатом,
иначе число нечем интерпретировать и нельзя сравнить со вчерашним.

Свои `--collect-only` по всему `tests/` (3214 тестов, ~17 с) сами поднимают load — не запускать
их параллельно с собственным замером.

## pytest: флаги, на которых легко ошибиться

- `-q` = verbosity −1, `-v` = +1, `-vv` = +2, **суммируются**. `-q -v` даёт 0 (точки, НЕ потестовые
  строки) — ловушка при «упрощении». Нужны потестовые строки при сохранённом `-q` → `-q -vv`.
- При убийстве по таймауту `subprocess.run(text=True)` отдаёт `TimeoutExpired.stdout`
  **в bytes**, не в str. Всегда нормализовать.
- `-q` убитый в фазе сбора отдаёт **0 символов** — пустой выход не значит «ничего не было».
- `addopts` в `pyproject.toml` перебивается CLI для опций одного значения: `-m` на командной
  строке **заменяет** `-m` из `addopts`, а не складывается с ним (проверено: `pytest -m live_probe`
  собирает пробы даже при `addopts = ["-m", "not live_probe"]`).
- `pytest-timeout` прерывает и `time.sleep`, и блокирующий `subprocess.run`, превращая зависание
  в именованный FAILED, **и прогон продолжается**.

## Заморозка бюджета тестами

`tests/test_merge_test_gate.py::test_large_mapped_subset_runs_all_files_in_bounded_batches`
вшивает `DEFAULT_TIMEOUT_SECONDS = 180` литералами (строки ~149–151: `[60.0, 60.0, 60.0]`,
`36.82 + 240.0 > DEFAULT_TIMEOUT_SECONDS`). Поднять бюджет батч-пути нельзя без правки этих строк,
то есть без явного разрешения оркестратора. Путь одного вызова (≤12 файлов) от этих литералов
не зависит — там бюджет берётся внутри `run_pytest` при `timeout=None`.
