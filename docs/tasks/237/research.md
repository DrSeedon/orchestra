# #237 / #230 — бесшовный рестарт активных агентов

Дата измерений: 2026-08-13. Фаза: research + destructive experiments на отдельной
мини-Orchestra. Боевой `orchestra.service` не перезапускался.

## Вопрос и критерий ответа

**Контекст.** FastAPI-супервизор владеет объектами сессий, а модельный ход физически исполняют
дочерние CLI Codex, Claude и Grok. В production уже включены `KillMode=process` и systemd FD
store, но рестарт посреди хода до этого не проверялся положительным конечным признаком.

**Изменение.** Сохранить процесс CLI и его stdio при смерти поколения супервизора, принять их
новым поколением, а на следующей границе хода заменить CLI, MCP, инструменты, промпт и конфиг.

**Baseline.** Текущий production-код под uvicorn/uvloop; альтернатива — закрыть admission и
дождаться завершения ходов (`bounded drain`) до сигнала.

**Измеряемый outcome.** «Бесшовно» означает одновременно:

1. задание начало исполняться до рестарта;
2. `MainPID` Orchestra изменился, а фактический PID CLI не изменился и остался жив;
3. заранее заданный результат появился после рестарта и побайтово верен;
4. новое поколение получило терминальное событие хода, сессия вышла из `running`;
5. пользовательский вход и события хода не потеряны и не продублированы;
6. следующий ход запускается уже с новым CLI/MCP, инструментами, промптом и конфигом.

Пункты 1–4 проверены здесь end-to-end. Пункт 5 проверен для наблюдавшейся JSONL-последовательности,
но не для каждого возможного места разрыва кадра. Пункт 6 уже реализован для принятого Codex через
`tools_are_stale`/turn-boundary refresh в #230; для Grok нужен тот же production-path oracle.

## Гипотезы и фальсификаторы

| Гипотеза | Что опровергает | Итог |
|---|---|---|
| H1. Текущий FD-store уже сохраняет активный Codex | полный mid-turn опыт не передаёт FD или не получает точный финал | **REFUTED**: под uvloop FD равны `None`, store пуст |
| H2. Достаточно переключить uvicorn на asyncio | CLI/ход всё равно погибает после исправления следующих звеньев | **CONFIRMED как физический путь**, но глобальная цена производительности не измерена |
| H3. uvloop можно сохранить, если Orchestra сама создаёт pipe | parent-owned FD под uvloop нельзя одновременно использовать для JSONL и сохранить числом | **CONFIRMED транспортным зондом**, runtime handover ещё требует реализации |
| H4. Codex и Grok имеют один lifecycle-класс | Grok нельзя принять без переноса Python-side состояния активного `session/prompt` | **REFUTED для первого поезда**: физический транспорт общий, но exactly-once seam Grok отдельный |
| H5. Claude можно безопасно принять тем же способом | SDK не отдаёт состояние парсера/контролов или silent-window опыт теряет ход | **Физически возможно, production-safe REFUTED**: один опыт прошёл, полный контракт SDK не переносим |
| H6. Bounded drain даёт тот же результат дешевле | рестарт не мгновенный или дедлайн всё равно обрывает ход | **REFUTED для заявленной цели**; остаётся operational fallback |

## Стенд и предрегистрация

Стенд — отдельный `git clone --no-local`, отдельная БД, HOME, workspace, transient unit и порт
18888. Полная инструкция и границы: [stand.md](stand.md). Production DB не открывалась даже на
чтение. Рестартировался только `orchestra-237.service`.[1]

До каждого подтверждающего опыта оракул требовал `STARTED`, `status=running` и фактический direct
child PID. Рестарт приходился через 40 секунд внутрь 90-секундной работы. После него требовались
новый MainPID, тот же живой CLI PID, точные байты файла, production-терминал
`type=status, content LIKE 'turn ended%'` и выход из `running`.[1]

## Результаты по рантаймам

| Runtime | MainPID | CLI PID | restart | Конечный результат | Терминал нового поколения | Итог |
|---|---:|---:|---:|---|---|---|
| Codex run9 | сменился | тот же фактический PID, PPID=1 | подтверждающий frozen oracle | `CODEX-run9-OK\n` | `status: turn ended` | **PASS** |
| Claude run4 | `3573268 → 3575304` | `3574488`, жив | 0.324 с | `CLAUDE-run4-OK\n` | `subagent_end`, `tool_result`, `DONE`, `turn ended` | **PASS прототипа** |
| Grok run5 | `3579133 → 3580742` | `3580075`, жив | 0.904 с | `GROK-run5-OK\n` | tool result, `turn ended` | **PASS прототипа; не rollout-доказательство** |

Во всех трёх успешных опытах systemd показывал два сохранённых FD. Это только диагностический
признак: успехом считалась вся колонка конечных эффектов, а не `NFileDescriptorStore=2`.[2][3][4]

### Исключённые/разведочные прогоны

- Codex run7 выполнил работу через рестарт, но тип терминального события в оракуле был изменён
  после просмотра результата; навсегда exploratory.
- Codex run8 также выполнил работу и был принят новым поколением, но оракул сравнивал устаревший
  `sessions.cli_pid`; навсегда exploratory. Run9 заранее снимал фактический PID из `/proc`.
- Claude run3 доказал физическую передачу двух FD, но новый процесс исключил строку с
  `session_id=NULL` из `resumable` и orphan sweep сам убил переживший CLI. После стендовой правки
  этого отдельного дефекта run4 прошёл.
- Первая Grok-проба под uvloop не была доказательством: CLI отсоединил долгую shell-задачу и
  ход не дошёл до терминала. Run5 держит составной положительный оракул.

## Семь звеньев, которые скрывали друг друга

### F1 — production event loop не отдаёт FD дочернего PIPE

Uvicorn выбрал uvloop. У созданных через `asyncio.create_subprocess_exec(..., stdin=PIPE,
stdout=PIPE)` `WriteUnixTransport`/`ReadUnixTransport` возвращали
`get_extra_info("pipe") is None`; `fd_in`/`fd_out` становились `None`, handover тихо возвращал
`False`, systemd store оставался пуст. Тот же probe под stdlib asyncio отдавал целые FD. Это
объясняет зелёные юнит-тесты и idle-рестарт 06:57, но не подтверждает active turn.[5]

**CONFIRMED — прямой trace production-shaped uvicorn: 3 Codex + 1 Grok отказа под uvloop;
успешные значения 8/9 и 16/17 под asyncio.**

### F2 — quiesce Codex/Grok ждал смерти процесса, который обязан выжить

После появления FD shutdown зависал: отменённый `_read_stdout` входил в `finally` и делал
`await proc.wait()`. Переживший CLI не завершался, поэтому uvicorn доходил до
`TimeoutStopSec=30`, а передача не коммитилась. Гейт по `_handover_quiescing` снял именно это
ожидание; после него store впервые получил дескрипторы.[6]

**CONFIRMED — последовательный стендовый trace до/после.**

### F3 — текущие FDNAME недопустимы для systemd

Код отправляет `agent:<uuid>:stdin|stdout`. Официальный контракт systemd запрещает `:` в
FDNAME; недопустимое имя игнорируется, а безымянный descriptor называется `stored`.[7]
Два FD поэтому приходили как `stored:stored`; `acquire_fds` правильно отказался от дубликата,
и сервис ушёл в restart-loop. Разделитель `.` дал уникальные имена через два поколения.

**CONFIRMED — прямой systemd trace + первичная документация.**

### F4 — первый оракул искал терминал, которого у Codex нет

Оракул ждал `turn_usage|turn_end`, а production сохраняет Codex-терминал как
`type=status, content='turn ended…'`. Исправный run7 был бы объявлен провалом.

**CONFIRMED — реальные DB logs; run7 исключён, run9 предзарегистрирован заново.**

### F5 — `sessions.cli_pid` между handover устаревает

После принятого хода turn-boundary refresh завершает adopted CLI и создаёт новый, но DB PID
обновляется только при следующем handover. Run8 выполнил ход, однако сравнение с DB смотрело на
предыдущий PID. Это не только дефект измерения: читатель, который сигналит по такой записи,
может попасть в переиспользованный PID. Отдельная #258 обязана перенести `(pid,starttime,runtime)`
и сигналить через pidfd только при полном совпадении; #237 не дублирует её seams.

**CONFIRMED — run8 process tree + аудит всех читателей `cli_pid`; activation hard-depends on #258.**

### F6 — активные Claude и Grok могут ещё не иметь `session_id`

`auto_resume_all` выбирает только `session_id IS NOT NULL`. В Claude run3 и Grok run5 до
рестарта native session id ещё был `NULL`, хотя живые pipes были у systemd. Без отдельного
правила `id IN adoptable` строка не загружается, а sweep считает её неизвестной, закрывает
валидные FD и сигналит CLI. Это состояние нельзя выводить из native session id: inherited pair —
более сильное положительное доказательство жизни.

**CONFIRMED — Claude run3: inherited UUID → ни одной загрузки этой строки → два SIGTERM одному
PID; run4/run5 с `adoptable`-исключением прошли.**

### F7 — Grok физически общий, но активный prompt живёт в Python

Grok наследует FD/pid/leftover/adopt-pipe primitives, однако `session/prompt` остаётся в
`_pending_requests` до конца хода; базовый quiesce обязан его отклонить. Кроме того,
`_read_stdout` читает только `self._proc.stdout`, `disconnect()` не вызывает adopted teardown,
а Grok-level `adopt` отсутствует. Stand-only adapter выделил prompt request, отменил только его
локальный waiter после успешной записи, сохранил synthetic active turn id, начал reader на
`self._out` и принял terminal response в новом поколении. Run5 прошёл.[4][8]

**CONFIRMED для одного наблюдавшегося active prompt без очереди, но exactly-once НЕ доказан.**
Между `send()` и завершением `_request.write()+drain()` остаются три разных состояния: prompt ещё
не записан, записан частично/неизвестно, полностью принят, но response не прочитан. Synthetic turn
id не коррелирует с настоящими `request_id`/`promptId`. До fault-injection oracle на всех трёх
границах Grok из первого поезда исключён; queued prompts и произвольный concurrent RPC также
должны fail-closed.

## Claude: почему зелёный run4 не едет в первый поезд

Claude SDK 0.2.114 позволяет передать custom `Transport`, но не имеет API adopt/reconnect к уже
идущему process/Query. Прототип создал новый приватный `Query` поверх inherited transport без
повторного initialize. Это физически сработало в тихом месте потока, но:

- parser `_LineFramer` и остаток частичного JSONL-кадра принадлежат старому Query и наружу не
  отдаются;
- pending control responses, incoming permission/hooks и их tasks принадлежат старому Python;
- очередь уже распарсенных SDK messages не сериализована;
- прототип зависит от приватных `_query`, `_read_task`, `_inflight_requests` и конструктора
  internal `Query`.[9]

Один разрыв посреди кадра или control-request делает исход неизвестным. Поэтому run4 —
**подтверждение жизнеспособности будущего session-host**, а не production-кандидат. Для Claude
надёжная граница — постоянный backend/session-host, который сам владеет SDK Query и переживает
смерть HTTP-супервизора; супервизор переподключается к host по сокету.

Это пока архитектурная гипотеза. Её будущая приёмка должна требовать: durable correlation каждого
input/request/terminal event; replay с dedupe после смерти HTTP-супервизора; сохранение порядка
partial/parsed frames и control callbacks; versioned host identity/upgrade handshake; identity-safe
orphan cleanup; два поколения reconnect; и следующий настоящий ход на новом MCP/prompt без
повтора предыдущего input. До этих проверок слово «надёжный» к host не применяется.

## Сравнение четырёх путей

| Путь | Цена | Что сохраняет | Что остаётся сломанным | Вердикт |
|---|---|---|---|---|
| `uvicorn --loop asyncio` | одна unit-правка + уже написанный handover | весь наблюдавшийся ход; E2E доказан | меняет loop всего HTTP-сервера; perf до/после не измерен | рабочий аварийный путь, не первый выбор |
| Parent-owned pipe FD под uvloop | точечная переделка spawn/stream ownership | uvloop и явные FD одновременно | ownership/systemd/rollback доказаны только transport-зондом | **prototype inference; кандидат Codex-поезда** |
| Persistent session-host | отдельный daemon/RPC/registry, самый большой объём | CLI + Python parser/control state; естественный путь для Claude | новая точка отказа, orphan/upgrade протокол | отдельный Claude/#230 трек |
| Bounded drain | код уже есть, deadline 900 с | завершившиеся до дедлайна ходы | рестарт не мгновенный; долгий/зависший ход всё равно режется | operational fallback, не safety для invariant |

Parent-owned transport был прогнан под реальным uvloop: Orchestra создала две пары `os.pipe`,
передала child ends в subprocess, parent ends 14/15 подключила через `connect_*_pipe`; round-trip
вернул `b'ACK:probe-237\n'`, оба FD оставались доступны числом, process завершился rc=0.[10]
Значит отказ от uvloop не является физически необходимым. В отличие от смены loop этот вариант
локализован в двух прямых subprocess runtime; Claude SDK всё равно требует session-host.

Исторический drain на успешно завершившихся ходах: p50 1.2 мин, p90 25.2 мин, максимум 87.6
мин; только 79.8% этой уже смещённой выборки укладывались в 15 минут, то есть deadline порезал бы
не менее 20.2%, не считая зависших/убитых ходов. Production deadline равен 900 с.[11]
Следовательно, drain дешевле по коду, но не даёт ни
«мгновенно», ни «ни одного обрыва». Его надо оставить как preflight первого активационного
рестарта и operational fallback при fail-closed handover, а не выдавать за бесшовность. Любой
`cut_turns > 0` блокирует заявленную rollout-приёмку.

## Точный первый поезд: только Codex, production-required

Ни одна строка ниже ещё не реализуется в этой фазе. Это граница будущего плана.

1. **`app/backend_jsonrpc.py` + direct spawn Codex:** Orchestra создаёт parent-owned pipe
   pairs до subprocess, хранит parent FD как канонический `fd_in/fd_out`, подключает их к текущему
   uvloop и закрывает каждую сторону ровно одним владельцем. Без этого production снова получает
   `None` и тихо деградирует в stop.
2. **`app/backend_codex.py`:** quiesce не ждёт `proc.wait()` и не сочиняет process-exit во время
   handover; уже существующие fail-closed pending-request и leftover contracts сохраняются.
   Без этого shutdown висит до timeout и хода не передаёт.
3. **`app/manager.py` + `app/fdstore.py`:** FDNAME становится допустимым и однозначным
   (`agent.<uuid>.stdin|stdout` или эквивалент без `:`), parser проверяет полное отображение;
   `resumable` включает каждый DB row, для которого у systemd есть полная пара, даже при
   `session_id=NULL`. Без первого сервис получает `stored:stored`; без второго sweep убивает
   корректного survivor.
4. **`app/routes/system.py`:** активационный workflow сначала атомарно закрывает глобальный
   agent-turn admission через `manager.begin_drain()` и mutating HTTP admission, затем ждёт
   одновременно `is_busy == false` у всех сессий **и** ноль уже допущенных mutating HTTP
   handlers, повторно проверяет оба условия непосредственно перед сигналом и держит оба gate
   закрытыми до смерти процесса. Timeout или ненулевой счётчик отменяет рестарт и открывает gate,
   а не продолжает shutdown. Текущий порядок (`restart_preflight`, затем 0.5 с, затем
   `begin_drain`) оставляет окно нового agent/auto-report хода; без исправления первый rollout
   небезопасен.
5. **#258 как hard dependency:** sweep закрывает неизвестный FD, но сигналит только по
   подтверждённым runtime + `/proc` starttime + pidfd. Stale/reused PID oracle обязателен до
   активации. #237 не меняет зарезервированные #258 функции.
6. **Delivery/systemd tests:** unit-level mapping + mutation tests и отдельный transient-unit
   rehearsal под uvloop для Codex. Помимо обычного mid-turn результата нужны управляемые
   cut-points: (a) частичный JSONL-кадр; (b) terminal уже распарсен, но ещё в очереди; (c) байты
   одновременно в `StreamReader._buffer` и kernel pipe; (d) два последовательных поколения.
   Каждый сценарий считает точную последовательность input/tool/terminal events, отсутствие
   дубля и тот же CLI PID. `NFileDescriptorStore=2` отдельно успехом не считается.
7. **Existing systemd settings остаются:** `KillMode=process`, socket activation,
   `FileDescriptorStoreMax=256`, `FileDescriptorStorePreserve=restart`. `--loop asyncio` в
   production не добавляется, если parent-owned E2E проходит.

### Второй поезд Grok: два независимых blocker

Первый blocker — exactly-once prompt seam из F7: нужны fault injection до записи, во время
неопределённой записи и после полной записи до response; для каждого — один side effect, один
`turn_end`, отсутствие вечного synthetic active turn. Только после этого Grok-level adopt/reader/
teardown из прототипа можно планировать в production.

Второй blocker: Grok CLI 1.0.3 присылает пустой `mcpServers`, а затем ready/tool count без полной launch identity.
Production `_verify_mcp_isolation` законно fail-closed; стенд ослабил только этот gate, чтобы
измерить lifecycle. #251 не меняет identity contract. До разрешения этого расхождения нельзя
говорить, что Grok production-ready, даже при зелёном run5.[8]

## Первый, ещё прерывающий рестарт

Старый процесс работает под uvloop и передаёт ноль FD, поэтому первый рестарт по определению
не может сохранить его текущие ходы. Безопасная процедура оператора:

1. атомарно закрыть agent-turn admission (`manager.begin_drain`) и mutating HTTP admission;
2. после закрытия gate дождаться одновременно `is_busy == false` у всех сессий и нуля уже
   допущенных mutating HTTP handlers; повторить оба условия сразу перед сигналом; timeout или
   ненулевой остаток отменяет рестарт, прямой `systemctl restart` в обход workflow запрещён;
3. убедиться, что `NFileDescriptorStore=0` до рестарта;
4. активировать только после merge #258 и зелёного production orphan-sweep oracle, который
   проходит весь путь и доказывает отсутствие любого raw-PID signal bypass;
5. снять список старых CLI PID/starttime; после рестарта проверить, что старые процессы не
   остались сиротами, новые сессии загрузились, Codex/Grok spawn и bridge работают;
6. только затем открыть admission.

При штатном graceful shutdown старый код вызывает `session.stop()/disconnect()` для backend,
который не смог handover, поэтому direct CLI должны завершиться. Timeout/kill остаётся причиной
обязательной post-check и зависимости от #258.

## Stand-only, не переносить в production

- диагностический подробный log transport types/FD;
- `ORCHESTRA_URL`/`WORKSPACE_DIR` из env для изоляции стенда (полезные отдельные улучшения, но не
  часть lifecycle acceptance);
- ослабление Grok 1.0.3 MCP identity gate;
- Claude private-Query prototype;
- runner и marker paths `/home/kesha/orchestra-scratch/237/**`.

Стенд оставлен живым для Phase 2/3; команды запуска и остановки находятся в [stand.md](stand.md).

## Контрдоказательства и открытые границы

- Codex имеет один подтверждающий frozen run9, Grok — один run5; это доказывает механизм на
  наблюдавшихся ходах, не статистическую частоту всех races.
- Реальный restart использовался, но FD adoption происходит между Python-процессами на одной
  машине; reboot/full stop по контракту store не переживает и не входит в цель.
- Explicit parent-owned FD доказан транспортным round-trip, ещё не полным Codex/Grok handover.
  Поэтому Phase 2 должна начинаться красным transient-unit oracle, а не реализацией.
- Grok write-boundary exactly-once, queued prompts и concurrent control RPC не проверялись;
  поэтому Grok исключён из первого поезда, а не только загейчен runtime-предикатом.
- In-flight mutating MCP HTTP handler должен завершиться до shutdown по уже существующему 120-с
  drain; FD-store не переносит установленное HTTP-соединение.
- `teardown_adopted` целиком независимо не ревьюился в #230; shared-runtime Codex review обязателен.
- Claude partial-frame/control state остаются недоступными; run4 не повышает их confidence.

## Вывод

**CONFIRMED:** немедленный рестарт без обрыва активного хода достижим для direct-child JSON-RPC
runtime. Codex run9 и Grok run5 дали полный положительный конечный эффект. Механизм #230 никогда
не работал в production целиком: первый тихий `None` скрывал следующие дефекты.

**Рекомендация:** первый поезд — только Codex lifecycle на parent-owned FD под сохранённым uvloop,
после transient-unit cut-point coverage и с #258 hard gate. Это пока prototype inference, а не
подтверждённый production design. Grok — второй поезд после exactly-once fault injection и
MCP-identity gate. Claude — persistent session-host track; private SDK adoption не выкатывать.
Bounded drain оставить для первого активационного окна как operational fallback, но он не заменяет
handover: дедлайн 900 с по построению допускает обрыв.

## Независимое второе мнение

Codex провёл два допустимых для prose-артефакта раунда. В первом он заблокировал небезопасный
порядок activation gate, включение Grok по одному happy-path, недостаточное Codex cut-point
coverage и слишком сильную формулировку parent-owned FD. Все четыре вывода приняты и изменили
рекомендацию: первый поезд сужен до Codex, а design остаётся prototype inference.

Во втором раунде Codex подтвердил эти исправления и нашёл последний blocker: условие перед
сигналом должно включать не только `session.is_busy == false`, но и ноль уже допущенных mutating
HTTP handlers. Замечание принято и внесено выше; третий раунд для prose запрещён потолком skill,
поэтому именно эта последняя редакция независимо не перепроверена. Последний формальный verdict
в [codex-review-research.md](codex-review-research.md) остаётся `NEEDS WORK`, а не `APPROVED`.

## Источники

1. [Tier 1 — direct measurement] `docs/tasks/237/stand.md`; изолированный clone/unit/DB и
   предрегистрация.
2. [Tier 1] `/home/kesha/orchestra-scratch/237/codex-run9.log`.
3. [Tier 1] `/home/kesha/orchestra-scratch/237/claude-run4.log`.
4. [Tier 1] `/home/kesha/orchestra-scratch/237/grok-run5.log`.
5. [Tier 1 + primary source] traces `journalctl -u orchestra-237.service`; production
   `app/backend_jsonrpc.py:66-87`.
6. [Tier 1 + primary source] failed run6/stand journal; `app/backend_codex.py:_read_stdout`,
   `app/backend_grok.py:_read_stdout`.
7. [Tier 2 — official systemd documentation]
   [sd_pid_notify_with_fds](https://www.freedesktop.org/software/systemd/man/latest/sd_pid_notify_with_fds.html),
   section `FDSTORE=1` / `FDNAME=` (fetched 2026-08-13 through the text proxy because the
   primary page rejected direct fetch).
8. [Tier 1 + primary source] run5 and current `app/backend_grok.py`; independent source inventory
   from `inv237-grok` and current-main cross-check from `bench-grok`.
9. [Tier 2 — installed primary source] `claude-agent-sdk==0.2.114`:
   `client.py`, `_internal/query.py`, `_internal/transport/subprocess_cli.py`; inventory
   `inv237-claude`.
10. [Tier 1] `/home/kesha/orchestra-scratch/237/uvloop-owned-fd-confirm.txt`.
11. [Tier 1, historical completed-turn sample] `docs/tasks/220/research.md:183-264` and
   implementation `docs/tasks/220/report.md:55-63`.
