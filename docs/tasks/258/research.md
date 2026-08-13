# #258 — безопасная идентификация процесса в orphan sweep

## Вопрос

**Контекст.** При старте Orchestra получает сохранённые systemd file descriptors и закрывает
те, чья session id отсутствует в загруженном реестре. Для такого descriptor код достаёт
`sessions.cli_pid` и посылает процессу `SIGTERM` [C1]. Запись PID сохраняется при handover,
но не обновляется при последующей замене adopted CLI [C2]. На стенде #237 уже наблюдалось
расхождение: в БД был PID `3544248`, фактически работал `3549993` [M0].

**Изменение под проверкой.** Перед сигналом надо доказать, что числовой PID всё ещё обозначает
ровно тот CLI, который Orchestra сохранила: та же жизнь процесса и тот же runtime. Сигнал должен
уйти через stable process handle, а не повторно через числовой PID.

**Baseline.** Сейчас `terminate_orphan_process(pid)` безусловно вызывает
`os.kill(pid, SIGTERM)`; существующая `terminate_cli_process()` проверяет start time и cmdline,
но всё ещё сигналит через числовой PID [C1][C3].

**Измеримый исход.** Production-путь sweep обязан закрыть orphan FD, но не послать сигнал,
если PID успел стать чужим, start time неизвестен, runtime не совпадает или `/proc` нельзя
прочесть. На положительном плече доказанный Codex/Grok orphan должен получить `SIGTERM`.
Проверка должна воспроизвести первый restart: сохранённая handover identity устарела после
next-turn refresh, а числовой PID уже принадлежит другому процессу.

## Гипотезы и фальсификаторы

### H1 — `(pid, starttime)` + точный runtime shape + pidfd даёт безопасный signal path

Гипотеза: `orphan_pids()` должен передавать сохранённые `pid + cli_started_at`; signal path
должен открыть pidfd, затем перечитать `/proc/<pid>/stat` и NUL-разделённый `cmdline`, сверить
точный известный Orchestra runtime shape и start time и послать `SIGTERM` через pidfd. Сохранённый
`backend_type` нельзя включать в identity: он меняется отдельной DB-транзакцией и может относиться
уже к следующему runtime [C6]. pidfd привязан к конкретной жизни процесса, поэтому PID reuse между
проверкой и сигналом не переадресует сигнал новому процессу [E1][E2].

Фальсификаторы:

- production kernel/Python не поддерживает pidfd;
- реальный Orchestra CLI не проходит заранее заданный runtime predicate;
- predicate требует `backend_type`, который не был сохранён атомарно с handover PID;
- после успешной проверки сигнал всё ещё уходит через numeric PID;
- неизвестный/нечитаемый start time разрешает сигнал.

### H2 — достаточно вызвать существующую `terminate_cli_process()`

Фальсификаторы: cmdline, который лишь содержит строку `codex`, проходит проверку; ошибка чтения
start time возвращает `0` и не запрещает сигнал; между проверкой и `os.kill()` остаётся PID-reuse
race.

**Результат: REFUTED.** Оба первых контрпримера воспроизведены [M2], третий следует прямо из
текущего порядка `read /proc` → `os.kill(pid, ...)` [C3]. Функцию можно переиспользовать как
единственный owner проверки, но сначала её надо узко усилить; простой вызов без изменений
не закрывает дефект.

### H3 — достаточно проверить cgroup

Фальсификатор: посторонний кандидат и настоящий CLI находятся в одном cgroup.

**Результат: REFUTED как identity.** Живой Codex wrapper и инструментальный subprocess этого
агента оба находятся в `0::/system.slice/orchestra.service` [M4]. Cgroup подтверждает общий
контур Orchestra, но не конкретный runtime и не конкретную жизнь PID. Его нельзя делать
load-bearing условием сигнала.

### H4 — не сигналить вообще, только закрывать FD

**Результат: REFUTED требованиями существующего sweep.** Комментарий production-кода фиксирует
измеренный, но негарантированный исход EOF: CLI может завершиться через BrokenPipeError, однако
это не контракт, поэтому истинные orphan процессы всё равно надо убирать [C1]. Безусловный отказ
от сигнала меняет safety-дефект на накопление orphan CLI.

## Findings

### F1. Текущий orphan sweep реально может убить посторонний процесс

**CONFIRMED — прямой прогон и чтение production-кода.** `orphan_pids()` выбирает только
`id, cli_pid`; `sweep_orphan_fds()` передаёт число в `terminate_orphan_process()`; последний
делает голый `os.kill(pid, SIGTERM)` [C1]. В контролируемой пробе PID собственного
`/usr/bin/sleep 30` был передан текущей функции и процесс завершился сигналом:

```text
orphan sweep: sent SIGTERM to unowned agent pid 3573393
baseline_unrelated pid=3573393 started=85968962 returncode=-15
```

Старый код не различает настоящий CLI и процесс, которому Linux повторно выдал тот же PID.

### F2. Stale PID возникает штатно на первом restart/refresh пути

**CONFIRMED — трассировка writer-ов и живой замер #237.** Единственный production writer
`cli_pid/cli_started_at` — `save_handover_state()`, вызванный из `_hand_over_backend()` [C2].
Adopted CLI на следующей границе хода может быть заменён новым, но этот путь handover state не
обновляет. #237 измерил stale row `3544248` при фактическом PID `3549993` [M0]. Значит дефект
особенно релевантен первому restart: новый процесс загружает handover snapshot и затем может
классифицировать сохранённые descriptors как orphan.

Смежная находка #237 уменьшает число ложных orphan: mid-turn row с `session_id=NULL` сейчас не
попадает в `resumable`, после чего его валидные inherited FD выглядят unknown. #237 исправляет
этот select вне seam #258. Это не заменяет #258: удалённая/неизвестная сессия с устаревшей
identity всё равно законно доходит до sweep, и сигнал там обязан быть безопасен.

### F3. Существующая проверка identity fail-open в двух местах

**CONFIRMED — два отрицательных прогона.** Текущая `terminate_cli_process()` ищет marker как
подстроку в декодированном cmdline и сравнивает start time только при truthy `actual_start`
[C3]. Поэтому чужое имя `notcodex-helper` и ошибка `process_start_time() → 0` оба разрешили
`os.kill`:

```text
substring_false_positive [(4242, 15)]
unreadable_start_false_allow [(4242, 15)]
```

Безопасный predicate должен разбирать `/proc/<pid>/cmdline` как NUL-разделённый argv, а
не искать подстроку. `actual_start == 0`, неизвестный `started_at`, неизвестный runtime,
ошибка pidfd или `/proc` должны завершаться громким отказом без сигнала.

### F4. Start time отличает жизнь процесса, pidfd закрывает race до сигнала

**CONFIRMED — primary docs + локальная capability-проба.** `/proc/<pid>/stat` field 22 — время
старта процесса в clock ticks после boot [E3]. Python 3.12 предоставляет `os.pidfd_open()`, а
`signal.pidfd_send_signal()` адресует процесс через pidfd [E1][E2]. man-pages прямо называет
race традиционного numeric PID API: PID может быть переработан и сигнал уйдёт другому процессу;
pidfd сохраняет ссылку на исходный процесс [E2]. На этой машине capability-проба дала:

```text
pidfd_available True True 6.8.0-136-generic
```

Следовательно, безопасный порядок такой: открыть pidfd → прочесть и сверить identity → сигналить
через тот же pidfd → закрыть fd в `finally`. Открытие pidfd после проверки оставило бы старую race.

### F5. Реальные runtime shapes требуют позиционных argv predicates

**CONFIRMED для Codex, CONFIRMED по production builder для Grok.** Живой Codex wrapper:

```text
sample_pid 3326326
exe /usr/bin/node
argv ['node', '/usr/bin/codex', '-c', 'model_reasoning_effort="xhigh"',
      '-c', 'features.multi_agent=false', '-c', 'web_search="live"',
      'app-server', '--stdio']
cgroup 0::/system.slice/orchestra.service
```

`/usr/bin/codex` — Node script (`#!/usr/bin/env node`), поэтому проверка только `/proc/PID/exe`
увидит `/usr/bin/node` и недостаточна [M4]. Production builder всегда заканчивает argv точными
токенами `app-server`, `--stdio` [C4]. Grok builder формирует `[GROK_BIN, "agent", ...,
"--always-approve", "stdio"]` [C5].

Контракт predicate:

- **Codex:** argv заканчивается ровно `app-server`, `--stdio`; executable token — либо `argv[0]`
  для native binary, либо `argv[1]` при `argv[0]` с точным basename `node`/`nodejs`; этот token
  после `realpath` совпадает с текущим `CODEX_BIN` builder-а. Одних suffix tokens недостаточно.
- **Grok:** executable token определяется так же: `argv[0]` для native binary либо `argv[1]`
  при точном `node`/`nodejs` в `argv[0]`; его `realpath` совпадает с текущим `GROK_BIN`.
  Следующий token ровно `agent`, argv заканчивается ровно `--always-approve`, `stdio`.
- Пустой argv, относительный/исчезнувший executable, другая позиция или ошибка нормализации —
  отказ без сигнала. Symlink сравнивается по `realpath`, а не по исходному написанию пути.

Для adopted teardown expected runtime уже известен из конкретного backend и predicate обязан
проверять только его. Для orphan sweep coherent runtime label в snapshot отсутствует, поэтому
проверка принимает любой **один** из двух точных известных shapes; lifetime всё равно доказывает
сохранённый start time. Это лучше, чем склеивать старый PID с независимо изменяемым
`sessions.backend_type`.

### F6. Живой DB snapshot не подтверждает постоянное наличие handover rows

**CONFIRMED, но это counter-evidence ограниченной силы.** Read-only запрос живой БД в момент
ресёрча вернул:

```text
live_rows_with_cli_pid 0
```

Это не опровергает измеренный stale interval: handover rows переходны и появляются вокруг
restart. Из этого следует только одно: калибровать фикс на текущем live row нельзя; acceptance
нужен детерминированный production-path test.

### F7. `backend_type` не является частью coherent handover snapshot

**CONFIRMED — трассировка двух независимых DB writer-ов.** `save_handover_state()` одной
транзакцией пишет `cli_pid` и `cli_started_at`, но не `backend_type` [C2]. Model/runtime switch
меняет `session.backend_type` и вызывает обычный `save_session()`; его UPSERT обновляет
`backend_type`, но вообще не касается handover PID/starttime [C6]. Поэтому строка может законно
содержать старые PID/starttime и новый backend type.

Первоначальное предложение читать три существующие колонки как одну identity было неверным.
Миграция в #258 не нужна только после сужения identity до атомарно записанной пары
`pid + cli_started_at`; runtime подтверждается текущим точным argv shape, а не mutable DB label.

## Рекомендуемый контракт фикса

1. `orphan_pids()` возвращает для inherited fd сохранённую identity с полями `pid` и
   `cli_started_at`, записанными вместе `save_handover_state()` [C2]. `backend_type` намеренно
   не используется: он не принадлежит coherent snapshot [C6].
2. `sweep_orphan_fds()` по-прежнему закрывает только FD неизвестной session id и считает его
   swept. Если identity отсутствует или не доказана, процесс остаётся жив, а лог на уровне
   error/warning говорит, какой PID и какое условие не подтверждено.
3. `terminate_cli_process()` остаётся единым owner проверки и используется и adopted teardown,
   и orphan sweep. Узкое усиление:
   - adopted teardown передаёт свой known runtime; orphan sweep разрешает ровно один из точных
     позиционных Codex/Grok shapes из F5, без mutable `backend_type`;
   - pidfd открывается до чтения `/proc`;
   - recorded и actual start time обязаны быть ненулевыми и равными;
   - cmdline разбирается по NUL и проходит точный Codex/Grok predicate;
   - `SIGTERM` отправляется только `signal.pidfd_send_signal(pidfd, ...)`;
   - при любой ошибке, включая `ValueError` разбора `/proc/PID/stat`, — fail loud, no signal;
     pidfd закрывается в `finally`;
   - ошибка одного кандидата не прерывает цикл sweep и не мешает обработать следующие FD;
     только `ESRCH` является обычным «уже вышел».
4. Никакого fallback на `os.kill(pid, ...)`: он возвращает закрытую race.
5. Cgroup можно логировать как контекст, но нельзя использовать вместо lifetime/runtime identity.

## Обязательный oracle следующей фазы

Один вертикальный production-path test должен воспроизвести первый restart:

1. handover snapshot хранит старые `cli_pid + cli_started_at`, а независимо изменённый
   `backend_type` намеренно противоречит им и не используется как доказательство;
2. next-turn refresh уже поднял новый CLI, но row ещё указывает на старый PID;
3. старый числовой PID представлен живым чужим процессом с другим start time/runtime;
4. inherited FD принадлежит действительно неизвестной/удалённой session id и доходит через
   настоящие `orphan_pids()` → `sweep_orphan_fds()` → signal helper;
5. spy на `pidfd_open`/identity helper и точный refusal reason доказывают, что отрицательное плечо
   дошло до safety boundary; sweep закрывает FD и оставляет чужой процесс живым;
6. разрешающее плечо с совпадающей Codex и Grok identity сигналится через pidfd, чтобы фикс не
   превратился в «никого не убивать».

Особая мутация из постановки: на зелёной реализации временно вернуть голый
`os.kill(identity.pid, SIGTERM)`/обойти identity, и тот же test обязан покраснеть, потому что
чужой процесс завершился. Отдельные мутации должны убрать проверку start mismatch и расширить
точный argv predicate до substring; остальные признаки в фикстуре не должны спасать мутант.

## Риски и edge cases

- Процесс может выйти между `pidfd_open` и чтением `/proc`: это штатный громкий no-op, не повод
  сигналить numeric PID.
- Процесс может выйти после проверки: `pidfd_send_signal` вернёт `ESRCH`; новый владелец того же
  числа не пострадает [E2].
- `process_start_time()` сейчас сворачивает любую ошибку в `0`; caller обязан трактовать `0` как
  отсутствие доказательства, не как разрешение [C3]. Malformed stat может также дать
  `ValueError`; он должен остаться локальной ошибкой кандидата, а не оборвать весь sweep.
- Codex PID — Node wrapper, а не native child; точный predicate обязан соответствовать wrapper,
  потому что именно `asyncio.create_subprocess_exec()` сохраняется как backend PID [C4].
- Runtime shape может измениться после обновления CLI. Fail-closed оставит orphan живым и напишет
  причину; это предпочтительнее SIGTERM постороннему процессу. Но тесты должны закреплять оба
  текущих production builder-а, чтобы drift был громким.
- `backend_type` может смениться, пока handover PID/starttime остаются в строке; использовать его
  как expected runtime запрещено без отдельной атомарной snapshot-колонки [C6].
- #237 не редактирует зарезервированные функции #258. Его fix предотвращает ошибочную
  классификацию валидной mid-turn сессии; #258 защищает signal boundary для настоящих unknown.

## Второе мнение Codex

Раунд 1 состоялся: ревьюер процитировал строку документа про cgroup и подтвердил порядок
`pidfd_open` до `/proc` validation. Вердикт `CHANGES REQUESTED` указал на несогласованный snapshot:
`backend_type` меняется отдельно от handover PID/starttime. Проверка кода подтвердила находку
[C6]; первоначальный трёхпольный контракт снят, F7 фиксирует counter-evidence.

Три suggestions также приняты в контракт: F5 задаёт позиционные argv predicates с нормализацией
configured path; ошибка одного кандидата локализована и не обрывает sweep; отрицательный oracle
доказывает достижение helper через spy/refusal reason, а не только отсутствие смерти процесса.
Повторный раунд запрошен только после этих изменений в prose, в пределах потолка skill. Раунд 2
дал `APPROVED`: все четыре пункта помечены `FIXED`, новых blocking findings нет; содержательность
вердикта подтверждена дословной строкой F7, которая присутствует в этом файле.

**Поправка Phase 2 после потолка research-review.** Дешёвая prerequisite-проверка показала, что
не только Codex, но и установленный `/usr/bin/grok` начинается с `#!/usr/bin/env node`; `file -L`
классифицирует его как Node.js script [M6]. Значит direct-only Grok shape из версии, которую видел
Codex, был REFUTED до implementation: `/proc` содержит Node wrapper и script token. F5 и
замороженный RED oracle исправлены на обе формы — Node wrapper и native binary. Новый раунд
research-прозы не запускался: безусловный потолок уже исчерпан; исправленный executable oracle
входит в отдельный Codex review Phase 2 plan.

## Затрагиваемые файлы

- `app/manager.py`: `sweep_orphan_fds`, `orphan_pids`, `terminate_orphan_process` и тип identity.
- `app/backend_jsonrpc.py`: узкое усиление существующих `terminate_cli_process` и
  `process_start_time`; без переписывания transport.
- `tests/test_fd_adopt.py`: первый-restart stale/reused-PID production-path oracle, разрешающие
  Codex/Grok плечи и мутации.
- `docs/tasks/258/`: план, Codex review, отчёт.

## Источники и измерения

- [C1] Код проекта: `app/manager.py:1997-2031,2301-2332` — текущий sweep, DB mapping и голый kill.
  Evidence tier 2: primary source.
- [C2] Код проекта: `app/manager.py:2169-2232`, `app/db.py:2782-2796`; `rg` нашёл единственный
  production writer `save_handover_state()`. Evidence tier 2: primary source.
- [C3] Код проекта: `app/backend_jsonrpc.py:338-391` — substring marker, условное сравнение
  start time и `os.kill`. Evidence tier 2: primary source.
- [C4] Код проекта и live `/proc`: `app/backend_codex.py:1688-1702`; измерение PID `3326326`.
  Evidence tier 1.
- [C5] Код проекта: `app/backend_grok.py:282-303`. Evidence tier 2: primary source.
- [C6] Код проекта: `app/session.py:2822-2875,2932-2965`, `app/db.py:1114-1220` — runtime switch
  сохраняет `backend_type` независимо, UPSERT не очищает `cli_pid/cli_started_at`. Evidence tier 2:
  primary source.
- [M0] Прямая стендовая фиксация #237: DB PID `3544248`, фактический PID `3549993`, переданная
  автором аудита. Evidence tier 1, внешний для этой сессии замер с точными числами.
- [M1] Контролируемая проба текущего `terminate_orphan_process()` на собственном
  `/usr/bin/sleep 30`: PID `3573393`, start `85968962`, return code `-15`. Evidence tier 1.
- [M2] Контролируемые monkeypatch-пробы текущего `terminate_cli_process()`:
  `notcodex-helper` и `actual_start=0` оба вызвали `(4242, SIGTERM)`. Evidence tier 1.
- [M3] Capability-проба: Python exposes pidfd APIs; kernel `6.8.0-136-generic`. Evidence tier 1.
- [M4] Live `/proc` Codex PID `3326326` и `/proc/self/cgroup`. Evidence tier 1.
- [M5] Read-only query `/home/kesha/orchestra/data/orchestra.db`: `0` rows with nonzero
  `cli_pid` at measurement time. Evidence tier 1.
- [M6] Локальная prerequisite-проверка Phase 2: `head -1 /usr/bin/grok` →
  `#!/usr/bin/env node`; `file -L /usr/bin/grok` → `Node.js script executable`. Evidence tier 1.
- [E1] Python 3.12 docs, [`os.pidfd_open`](https://docs.python.org/3.12/library/os.html#os.pidfd_open).
  Evidence tier 2: primary documentation.
- [E2] Linux man-pages, [`pidfd_send_signal(2)`](https://www.man7.org/linux/man-pages/man2/pidfd_send_signal.2.html),
  and Python 3.12 [`signal.pidfd_send_signal`](https://docs.python.org/3.12/library/signal.html#signal.pidfd_send_signal).
  Evidence tier 2: primary documentation.
- [E3] Linux man-pages, [`proc_pid_stat(5)`](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html).
  Evidence tier 2: primary documentation.
