# #258 — план: identity gate перед orphan SIGTERM

## Цель

Сохранить существующую уборку orphan CLI, но убрать numeric-PID signal boundary. Новый supervisor
на первом restart закрывает неизвестный inherited FD как сегодня, затем сигналит процесс только
если сохранённая handover-пара `(cli_pid, cli_started_at)` совпала с живой process generation и
argv имеет точный shape управляемого Codex или Grok. Проверка и сигнал принадлежат одному pidfd.

## Границы

Разрешённые production seams:

- `app/manager.py`: `sweep_orphan_fds`, `orphan_pids`, `terminate_orphan_process` и локальный
  immutable value type для пары PID/starttime;
- `app/backend_jsonrpc.py`: узкое усиление существующей `terminate_cli_process()` и маленькие
  приватные helpers её identity check;
- `tests/test_orphan_pid_identity.py` и релевантные T1 guards в `tests/test_fd_adopt.py`;
- `docs/tasks/258/`.

Не менять `app/db.py`, schema, handover/adopt/refresh lifecycle, backend command builders,
systemd или живую машину. Не использовать `sessions.backend_type`: Codex review подтвердил, что
он сохраняется независимо от PID/starttime и не является coherent identity. Не добавлять fallback
на `os.kill(pid, ...)` ни при какой ошибке pidfd или `/proc`.

`feat-hot-reload` (#237) не редактирует зарезервированные функции. Его select-fix не допускает
валидную mid-turn session до sweep; #258 остаётся последней signal boundary для настоящей unknown
session. Первый Codex/Grok activation в #237 зависит от merged #258 и зелёного T1 oracle.

## Реализация

### `app/manager.py`

1. Добавить `@dataclass(frozen=True) OrphanProcessIdentity` с полями ровно:

   ```python
   pid: int
   started_at: int
   ```

2. Сохранить имя `orphan_pids()`, но изменить результат на
   `dict[int, OrphanProcessIdentity]`. Одна query читает только `id, cli_pid, cli_started_at`.
   Нулевой/NULL PID не попадает в mapping; нулевой starttime попадает и затем громко
   отвергается общим identity helper. `backend_type` не читать.
3. `sweep_orphan_fds()` продолжает текущий порядок: fail-closed при пустом registry, закрыть FD
   неизвестной session id, обработать соответствующую identity, залогировать закрытый FD,
   продолжить цикл. Ошибка проверки одного PID не должна прервать последующие candidates.
4. `terminate_orphan_process(identity)` только вызывает общий
   `backend_jsonrpc.terminate_cli_process(identity.pid, None, identity.started_at)`; `None`
   означает «любой один из точных managed Codex/Grok shapes». Numeric fallback удалить.

### `app/backend_jsonrpc.py`

1. Сохранить совместимый вызов `terminate_cli_process(pid, label, started_at=0)`; расширить
   `label` до `str | None`. Existing adopted teardown передаёт concrete `RUNTIME_LABEL` и тем
   самым разрешает только свой runtime; orphan wrapper передаёт `None` и разрешает один из двух
   известных managed shapes.
2. До чтения `/proc` открыть `os.pidfd_open(pid)`. `started_at == 0` можно отвергнуть до syscall,
   но если `/proc` читается, pidfd уже обязан существовать. Закрыть pidfd в `finally` на каждом
   исходе.
3. Читать `/proc/<pid>/cmdline` как NUL-separated argv; пустой argv — отказ. Читать field 22
   через существующий `process_start_time()`. `actual_start == 0`, `ValueError`, recorded/actual
   mismatch и любая другая ошибка доказательства — `logger.error` с PID, no signal.
4. Exact predicates:

   - Codex: argv заканчивается ровно `("app-server", "--stdio")`; executable token — `argv[0]`
     для direct binary либо `argv[1]`, когда basename `argv[0]` ровно `node`/`nodejs`;
     `Path(token).resolve(strict=True)` равен так же нормализованному текущему `CODEX_BIN`.
   - Grok: executable token — `argv[0]` для native binary либо `argv[1]`, когда basename
     `argv[0]` ровно `node`/`nodejs`; normalized token равен `GROK_BIN`, следующий token ровно
     `"agent"`, argv заканчивается ровно `("--always-approve", "stdio")`. Установленный
     `/usr/bin/grok` — Node shebang, поэтому wrapper-плечо обязательно.
   - Текущие configured paths получать ленивым импортом constants внутри helper, чтобы не
     создать import cycle `backend_codex/backend_grok → backend_jsonrpc`.

5. После всех checks вызвать только
   `signal.pidfd_send_signal(pidfd, signal.SIGTERM)`. `ProcessLookupError`/`ESRCH` означает
   обычное «исходная process generation уже вышла»; другие `OSError` логируются. Ошибка закрытия
   pidfd логируется отдельно и не маскирует исход identity check.

## RED oracle и freeze

Финальный замороженный oracle — commit `21ee9e33`. Предыдущие snapshots `8114bf6b`,
`5384b07b` и `cdda427e` **superseded/excluded**: до production implementation replay их уточнили,
чтобы malformed `/proc` проверял локализацию ошибки, missing-start mutation не маскировалась
неподготовленным pidfd, а Grok positive control воспроизводил его реальный Node wrapper. Phase 3
не меняет ни один T1 test, fixture или test helper относительно `21ee9e33`.

Phase 3 начинается только с побайтно неизменного frozen oracle; любое расхождение останавливает
implementation до нового plan-гейта.

Команда:

```bash
uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -k 'test_t1_' -q
```

Текущее доказанное RED: `exit 1`, `4 failed, 1 passed, 28 deselected`. Первая missing-behaviour
строка:

```text
AssertionError: the first-restart sweep signalled a foreign process through a stale/reused PID
```

Текущий код физически завершает owned test process `/usr/bin/sleep 30` с `returncode=-15`; это
не ImportError, collection error или синтетический флаг.

Пять guards в named command:

- `test_t1_first_restart_reused_foreign_pid_survives_real_sweep`: реальная DB handover identity,
  независимо изменённый `backend_type`, настоящий `_inherited_named_fds → orphan_pids → sweep →
  helper`, живой чужой process, закрытый FD, pidfd spy и громкий refusal;
- `test_t1_verified_codex_and_grok_orphans_signal_only_through_pidfd`: оба positive controls,
  exact argv, pidfd-before-`/proc`, pidfd close и запрет numeric kill;
- `test_t1_unverifiable_candidate_does_not_abort_later_orphan_cleanup`: malformed stat первого
  candidate, закрытие обоих pidfd и successful reap второго;
- `test_t1_unknown_start_time_refuses_to_signal`: valid Codex argv + available pidfd не должны
  маскировать отсутствие recorded starttime;
- `test_t1_helper_uses_pidfd_and_refuses_a_reused_pid`: matching positive, start mismatch и
  `notcodex-helper` substring false positive в одном helper-level control.

## Mutation protocol после GREEN

Каждая мутация выполняется отдельно только на зелёном T1 command. Для каждой: новый `cp` backup,
уникальный `grep -c` marker до прогона и после восстановления, восстановление через `mv`, затем
`touch` Python-файла и зелёный повтор команды.

1. **Обязательная numeric-kill mutation:** заменить только pidfd signal на
   `os.kill(pid, signal.SIGTERM)`. Ожидание: real foreign process погибает либо positive guard
   фиксирует `numeric_signals`; T1 command красный.
2. **Production wiring mutation:** убрать вызов helper из `terminate_orphan_process`. Ожидание:
   negative arm оставляет process живым, но `opened == []`; positive arms также не сигналятся.
3. **Starttime mutation:** убрать mismatch refusal. Ожидание: helper-level matching argv лишает
   остальные признаки возможности спасти мутант и reused-PID guard краснеет.
4. **Argv mutation:** заменить exact executable predicate на substring `codex`. Ожидание:
   `notcodex-helper` получает pidfd signal, guard краснеет.
5. **Unknown-start mutation:** убрать `started_at == 0` refusal. Ожидание: valid argv и fake pidfd
   доходят до signal, missing-start guard краснеет.

Результат каждой мутации, обе marker counts и финальный GREEN записать в `report.md`.

## Проверка и pre-mortem Phase 3

После named GREEN без полного suite:

```bash
uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -q
```

Проверяемые regressions:

- adopted Codex/Grok teardown продолжает сигналить matching CLI через обновлённый общий helper;
- unknown recorded start остаётся fail-closed;
- malformed `/proc` одного candidate не оставляет pidfd и не прекращает sweep;
- symlinked configured executable проходит `realpath`, похожий basename/substring — нет;
- empty registry по-прежнему не закрывает и не сигналит ничего;
- positive controls доказывают, что true orphan cleanup не был выключен.

Полный suite не запускать: оркестратор запретил брать глобальный test lock для этой фазы.

## Tickets

### T1 — Reap only the exact handover process generation

- Files: `app/manager.py`, `app/backend_jsonrpc.py`, `tests/test_orphan_pid_identity.py`,
  `tests/test_fd_adopt.py`, `docs/tasks/258/report.md`
- Test: `tests/test_orphan_pid_identity.py::test_t1_first_restart_reused_foreign_pid_survives_real_sweep`
  и остальные `test_t1_*` из named command — committed RED in `21ee9e33`
- AC: `uv run python -m pytest tests/test_orphan_pid_identity.py tests/test_fd_adopt.py -k 'test_t1_' -q`
  is green; exact focused regression command выше is green; все пять mutation runs красные,
  каждый откатан с `touch` и финальным GREEN; `git diff 21ee9e33 -- tests/test_orphan_pid_identity.py
  tests/test_fd_adopt.py` показывает ноль изменений acceptance oracle; ни один production signal
  path не содержит `os.kill(pid, ...)`; `backend_type` не участвует в orphan identity; никаких
  system changes/restart/deploy.
- blocked-by: none
