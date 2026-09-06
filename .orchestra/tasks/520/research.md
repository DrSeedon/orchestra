# #520 — воркеры на gpt-6-astra не доходят до запуска CLI

## Вопрос

Почему создание треда Codex для `gpt-6-astra` не доходит до запуска процесса?
Контекст: сессия остаётся `status=running`, `session_id = NULL`, процесса CLI нет,
в логах только первое `user_message`. Baseline: прямой `codex exec -m gpt-6-astra`
работает (RC=0). Измеримый исход: живой воркер на Astra, который ответил.

## Гипотезы

1. **Процесс сервера старше коммита, добавившего Astra** (гипотеза владельца).
   Фальсификатор: `ExecMainStartTimestamp` позже даты коммита, и mtime/`.pyc`
   загруженного модуля не расходятся с диском. → **ОТВЕРГНУТА**, см. ниже.
2. **Справочник, ключованный по id модели, роняет путь до `exec`**.
   Фальсификатор: путь запуска не принимает model как параметр. → **ОТВЕРГНУТА**.
3. **Путь запуска блокируется без исключения (тихое зависание)**.
   Фальсификатор: в стеке живого процесса нет заблокированных потоков. → **ПОДТВЕРЖДЕНА**.

## Установленная причина

`connect()` для codex-бэкенда проходит стадии до `project_doc_sync` и **зависает
внутри `_select_managed_codex_state_source`**. Исключения нет, таймаута нет,
процесс CLI не порождается — поэтому в журнале нет ни `cli_spawn`, ни
`backend connect failed`.

Дамп живого процесса (pid 450656, `py-spy dump`, 06.09.2026 17:31) — пять потоков,
ровно четыре воркера comfy + `astra-smoke`:

```
Thread 456863 (idle): "ThreadPoolExecutor-0_0"
    _inspect_codex_state (app/backend_codex.py:516)
    _select_managed_codex_state_source (app/backend_codex.py:614)
```

Механизм из двух звеньев:

1. Коммит `3f8bffbf` (05.09.2026 11:40 CEST) добавил строкой-мутацией
   `_CODEX_STATE_MIGRATIONS_BY_CLI["0.153.4"] = ...` (`app/backend_codex.py:372`,
   **после** литерала словаря на строке 313). До него CLI 0.153.4 был неизвестен,
   срабатывала ветка пропуска на `backend_codex.py:1034`, и посев состояния не
   выполнялся вовсе. После него свежий воркер уходит в ветку посева.
2. `_select_managed_codex_state_source` проверяет **каждый** managed home:
   `_inspect_codex_state(candidate, check_integrity=True)` → `PRAGMA quick_check`
   по всей базе, и только потом берёт `max` по `thread_count`.

Замер стоимости (06.09.2026, эта машина, 8 CPU, 23 GiB RAM):

| величина | значение |
|---|---|
| managed homes | 289 (273 с `state_5.sqlite`) |
| суммарный объём | 72 GiB (`~/.orchestra/codex-home`) |
| `quick_check` одной БД | 2.4 с в среднем (3 случайных home), 3.1 с база |
| кандидатов на спавн | 278 |
| проекция полного скана | 663 с ≈ **11 мин на один спавн**, последовательно |

Пять воркеров сканировали одновременно и делили I/O: к 17:31 (спавн 17:04–17:16)
они всё ещё были в скане, последний завершился около 18:00 — то есть порядка часа.
Каждый новый воркер добавляет свой home, поэтому скан удлиняется с каждым спавном.

## Почему это выглядело как дефект Astra

Путь **не зависит от модели**: `_select_managed_codex_state_source(target_home,
cli_version)` не принимает model, и никакой справочник по id модели в нём не
участвует. Ломается любой **свежий** codex-воркер: у него нет `state_5.sqlite`,
поэтому `_managed_codex_state_needs_seed` возвращает True. Уже существующие
воркеры переподключаются мимо скана — их состояние на месте.

С момента коммита `3f8bffbf` в проекте не создавалось ни одного codex-воркера,
кроме пяти Astra (проверено по `sessions`), поэтому контрольного плеча на Luna
в наблюдениях не было. **ОСТАТОЧНАЯ НЕОПРЕДЕЛЁННОСТЬ, названная явно:** свежий
Luna-воркер под старым кодом не запускался, вывод о независимости от модели
сделан по чтению кода, а не по замеру.

## Отвергнутые гипотезы

- **Устаревший процесс.** `ExecMainStartTimestamp = 06.09 16:58:53`, коммиты Astra
  от 04–05.09 — процесс новее. `app/backend_codex.py` mtime 05.09 13:58:31;
  `app/__pycache__/backend_codex.cpython-312.pyc` — timestamp-invalidation
  (flags=0), записанные mtime и size **совпадают** с файлом на диске
  (1788609511 / 131808). Байткод соответствует исходнику, подмены нет.
- **Справочник по id модели.** В `_codex_command()` и на пути посева нет ветвления
  по модели; `CODEX_CONTEXT_LIMITS.get(model, 258400)` имеет дефолт и не бросает.
- **Собственная ошибка в моей проверке (записана как урок):** первый разбор словаря
  через AST дал ключи `['0.150.1']` и я заключил, что 0.153.4 неизвестен и ветка
  пропуска срабатывает. Это противоречило дампу py-spy. Причина расхождения —
  ключ добавляется **мутацией на строке 372**, а не литералом. Литерал словаря
  не является полным списком его ключей.

## Правка

`app/backend_codex.py` — выбор источника возвращает **первый здоровый** кандидат
вместо ранжирования всех. База (`~/.codex/state_5.sqlite`) стоит первой и здорова
(`status=complete`, `last_success_at=1785740237`, 793 треда, 52 миграции —
валидны для 0.153.4). Managed homes остаются запасным путём и сортируются по
mtime по убыванию: это `stat`, а не чтение базы.

Компромисс назван явно: прежний порядок брал самый «полный» индекс по
`thread_count`, что требовало прочитать все базы. mtime — дешёвая замена ранжиру.
При здоровой базе запасной путь не читается вообще.

Замер после правки (тот же процесс, тот же набор home):

| | до | после |
|---|---|---|
| вызовов `quick_check` | 278 | **1** |
| время выбора источника | ≈663 с (проекция) | **3.06 с** (замер) |

## Доказательство живым прогоном

`.orchestra/tasks/520/astra_live_proof.py` — настоящий `CodexBackend`,
свежий managed home (`exists=False`, то есть именно тот случай, что зависал),
`model="gpt-6-astra"`:

```
fresh home: /home/kesha/.orchestra/codex-home/astra-proof-7e528386 (exists=False)
Codex managed state seeded: source=/home/kesha/.codex/state_5.sqlite threads=793
codex_connect_stage stage=cli_spawn duration=0.002s
codex_connect_stage stage=cli_initialize duration=0.945s
codex_connect_stage stage=cli_thread_start duration=0.762s
CONNECTED in 8.2s  thread_id=01a07759-095f-7ea1-850c-b39bcd5363b1  launcher_pid=469815

468497 node /usr/bin/codex ... app-server --stdio
468509 .../codex-linux-x64/vendor/.../bin/codex ... app-server --stdio

  event: tool_use: Bash: {"command": "/bin/bash -lc 'echo ASTRA_LIVE_OK'"}
  event: tool_result: ASTRA_LIVE_OK
  event: text: ASTRA_LIVE_OK
  event: turn_end: stop_reason=end_turn
ANSWER after 12.4s: ASTRA_LIVE_OK
```

Появился процесс CLI, Astra выполнила команду и ответила. `mcp orchestra: failed`
в этом прогоне — заглушка `/bin/true` вместо MCP-сервера в моём стенде, не дефект.

Прогон выполнен **вне** живого сервера: правка в Python, и она не действует в
процессе 450656 до рестарта, который инициирует только владелец.

## Тесты

`python -m pytest tests/test_codex_managed_state.py -q` → `23 passed`.
Импортированный модуль:
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-astra-runtime/app/backend_codex.py`.

- `test_source_selection_prefers_fullest_healthy_matching_index` заменён на
  `test_source_selection_stops_at_first_healthy_source`: он считает вызовы
  `_inspect_codex_state` и требует ровно один. Старый тест закреплял контракт
  «выбрать самый полный», который и требовал исчерпывающего скана.
- Добавлен `test_source_selection_prefers_freshest_managed_state_when_base_is_corrupt`
  на порядок запасного пути; прежний тест на порчу базы сохранён.
- **Мутация:** возврат исчерпывающего скана (`found.append` + `found[-1]` вместо
  раннего `return`) → оба новых теста краснеют, 21 passed / 2 failed. Тесты входят
  в этот коммит.

## Находки, не входящие в правку

1. **Мёртвая сессия показывается как `running`.** Ни таймаута, ни отбоя: поток
   в пуле продолжает скан даже после архивации воркера. Четыре comfy-воркера были
   заархивированы в 17:15, но их потоки крутились ещё ~45 минут и позже вернули
   сессии в `idle`. Пять потоков из пула на 12 были заняты — при большем числе
   спавнов пул исчерпается и заблокирует остальной `to_thread`-код.
2. **`~/.orchestra/codex-home` не чистится:** 289 home, 72 GiB, диск `/` занят на
   89% (257 G из 290 G). Каждый спавн копирует ~224 MiB. Правка убирает стоимость
   *чтения* всех баз, но не рост их числа.
3. **`ImportError: cannot import name '_fire_sync' from 'app.tm'`** — повторяется
   на каждом `publish` в журнале живого сервера (`app/manager.py`, «task sync after
   publish failed»). Это действующий дефект текущего main, а не следствие #520.
</content>
</invoke>
