# #211 — предохранитель от runaway `ugrep`

Дата: 2026-08-12. Фаза 1: только чтение, безопасные короткие пробы и проектирование.
Системная конфигурация не менялась, `orchestra` не рестартовал.

**Отдельного штатного выключателя подмены `grep`/`find` в Claude Code 2.1.197 не
найдено: его нет ни в опубликованных настройках и schema, ни рядом с кодом генерации
snapshot. Есть поддерживаемый общий механизм `CLAUDE_ENV_FILE`, который в этой версии
исполняется после snapshot и позволяет сделать `unset -f grep find`; это рабочая
компенсация, но не обещанный Anthropic opt-out и после обновления требует регрессионной
пробы. Первый постоянный предохранитель — отдельная маленькая systemd-служба вне cgroup
`orchestra`: она сверяет cgroup + `/proc/PID/exe` + NUL-поле `argv[0]`, kernel-freeze'ит
`orchestra.service`, подтверждает `cgroup.events frozen=1` и identity, и только затем через
pidfd убивает совпавший embedded `ugrep`; причина остаётся в journal. Точные armed-пороги
должны быть получены из суточного direct observation, а не из косвенных Bash durations. `MemoryHigh=8G`
после включения guard следует снять; `MemoryMax=12G` пока оставить неизменным как
неселективный последний fail-safe. Узкий reporter Orchestra после восстановления доставляет
готовый OS-event в TG, но не имеет policy или права сигналить.**

## Question

**Контекст.** Claude Code подменяет shell-функции `grep` и `find` на embedded
`ugrep`/`bfs`. Два эпизода runaway `ugrep` за 15 минут вытеснили память в swap и положили
дисковый I/O; uvicorn перестал отвечать.

**Change under test.** Поддерживаемо выключить подмену либо поставить селективный
per-process guard, который останавливает виновника и обнаруживает событие независимо от
здоровья Orchestra.

**Baseline.** Подмена включена; на всём `orchestra.service` стоят `MemoryHigh=8G` и
`MemoryMax=12G`; временный bg-сторож остаётся аварийной затычкой, но не считается
постоянным решением.

**Измеримый результат.** Виновный процесс останавливается до самого раннего наблюдённого
удушья (12 минут); нормальный `grep`, uvicorn, SQLite и обычные процессы агентов физически
не проходят предикат; событие остаётся в journal; отключение guard — одна команда.

## Hypotheses considered

- **H1:** у Claude Code есть поддерживаемый флаг или настройка, отключающая shadowing.
  *Falsifier:* полного списка env/settings недостаточно — нужен отрицательный поиск в schema,
  установленном бинарнике и поведенческая проба. Результат: **REFUTED как отдельный opt-out**;
  найден только общий hook `CLAUDE_ENV_FILE`.
- **H2:** лимит на весь `orchestra.service` защищает машину без ухудшения доступности.
  *Falsifier:* рост direct reclaim/swap/I/O и зависание uvicorn до достижения hard limit.
  Результат: **REFUTED для `MemoryHigh`; REFUTED для `MemoryMax` как селективного guard**.
- **H3:** in-process coroutine достаточно надёжна как сторож.
  *Falsifier:* event-loop thread uvicorn находится в `D` либо не обслуживает loopback во время
  инцидента. Результат: **REFUTED как primary safety boundary**.
- **H4:** внешний OS-guard может точно выделить embedded `ugrep`, не убивая остальные
  процессы. *Falsifier:* идентичность виновника неотличима от обычного Claude CLI либо PID
  нельзя безопасно перепроверить перед сигналом. Результат: **LIKELY/CONFIRMED по частям** —
  тройной предикат отличает процессы, Linux/Python поддерживает pidfd, а cgroup v2 —
  kernel freeze; полная kill-ветка ещё не реализована и поэтому остаётся Phase 2/3.

## Findings

### 1. Прямое подтверждение первопричины — CONFIRMED

В обоих снятых до убийства процессах родитель был обычным вызовом вида
`/bin/bash -c source /home/kesha/.claude/shell-snapshots/snapshot-bash-…sh`; аргументы
начинались с `ugrep -G --ignore-files --hidden -I --exclude-dir=.git …`. Это наблюдение
оркестратора до cleanup, не вывод по косвенным признакам [M1].

В текущем снимке строки 102–132 сначала делают `unalias grep/find`, затем определяют
функции, запускающие тот же executable Claude через `exec -a ugrep`/`exec -a bfs` [M2]. На
финальном чтении было 19 snapshot-файлов, два SHA-варианта; нужный блок присутствует во
всех 19. Число файлов меняется вместе с живыми сессиями, поэтому первоначальные «20» и
текущие «19» не противоречат механизму.

### 2. Отдельного поддерживаемого opt-out не найдено; `CLAUDE_ENV_FILE` работает как общий hook — CONFIRMED с оговоркой версии

В официальных списках переменных окружения, settings и полном JSON schema нет настройки с
`ugrep`, `bfs`, shell snapshot или disable-shadow семантикой [S1][S3][S4]. В строках
установленного бинарника рядом с генератором snapshot блок называется `Shadow find/grep
with embedded bfs/ugrep (ant-native only)` и не имеет видимого config-условия [M3].

Поведенческая проба реального snapshot с четырьмя окружениями — default,
`CLAUDE_CODE_SAFE_MODE=1`, `CLAUDE_CODE_SIMPLE=1`,
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` — во всех случаях дала
`type -t grep → function`, а `grep --version` показал `ugrep 7.5.0` [M4]. Это доказывает
поведение уже созданного snapshot, но не обещает семантику будущих версий.

Официальная документация описывает `CLAUDE_ENV_FILE` как путь к shell-скрипту, который
Claude Code выполняет перед каждой Bash-командой [S1]. В установленной 2.1.197 фактический
порядок такой: `source snapshot` → содержимое `CLAUDE_ENV_FILE` → пользовательская команда
[M3]. Проба `unset -f grep find` после snapshot вернула `/usr/bin/grep` 3.11 и
`/usr/bin/find` 4.9.0 [M5].

**Вывод.** В Phase 3 можно применить `CLAUDE_ENV_FILE` как defense-in-depth для новых Bash
вызовов. Называть его «штатным выключателем ugrep» нельзя: Anthropic документирует hook,
но не порядок относительно внутреннего snapshot и не этот use case. После каждого Claude
Code upgrade обязательна короткая проба порядка. Уже подключённые процессы наследуют старое
окружение, поэтому применение требует отдельно разрешённого reconnect/restart; в этой фазе
его не делали.

### 3. Матч по имени процесса (`comm`) неверен — CONFIRMED

`exec -a ugrep` меняет `argv[0]`, но не kernel `comm`. Контрольная проба

```text
Popen(['ugrep', '-G', 'NEVER_MATCH_211'], executable='/usr/bin/claude')
/proc/PID/comm       → claude
/proc/PID/status     → Name: claude
/proc/PID/cmdline[0] → ugrep
```

совпала с инцидентом, где `ps` показывал `comm=claude.exe`, а arguments начинались с
`ugrep …` [M6]. Следствия:

- `pgrep -x ugrep`, `pkill -x ugrep` и `ps … comm == "ugrep"` не являются надёжными
  проверками этого embedded режима;
- `pkill -f` запрещён как слишком широкий: он уже матчился на собственный shell;
- временный сторож был исправлен владельцем на матч по CMDLINE; это остаётся временной
  затычкой, а не частью плана постоянной защиты [M1].

Постоянный guard должен требовать одновременно:

1. точный cgroup `/system.slice/orchestra.service`;
2. точный resolved `/proc/PID/exe` установленного Claude native executable;
3. точное первое NUL-разделённое поле `/proc/PID/cmdline` = `ugrep`;
4. превышение `age` **ИЛИ** `VmRSS` из policy;
5. безопасный протокол `cgroup.freeze=1` → подтверждение `cgroup.events frozen=1` → повторная
   сверка identity/start time → pidfd `SIGKILL` только при совпадении → обязательный thaw.

Обычный агент совпадёт по cgroup/exe, но не по `argv[0]`; uvicorn не совпадёт по exe и
`argv[0]`; SQLite здесь не отдельный процесс. На хосте Python 3 имеет `os.pidfd_open` и
`signal.pidfd_send_signal`, поэтому сигнал можно послать handle процесса, а не повторно
использованному числу PID [M7].

Codex second opinion нашёл race: pidfd сохраняет identity процесса, но тот же PID
может сделать `exec` между последним чтением `/proc` и `SIGKILL`; start time при этом не
меняется [C1]. Раунд 2 показал, что `SIGSTOP → recheck` также недостаточен: внешний
`SIGCONT` может открыть новую race перед kill [C2].

Исправленный после потолка дебата дизайн использует cgroup v2 freezer. Kernel docs говорят:
запись `1` в `cgroup.freeze` останавливает все процессы cgroup и descendants; завершение
подтверждается только `frozen=1` в `cgroup.events`; процессы не выполняются до явного thaw,
но fatal signal может их убить [S13]. `SIGCONT` не thaw'ит cgroup. Последовательность:

1. открыть pidfd кандидата и проверить exact identity;
2. записать `1` в policy-defined `orchestra.service/cgroup.freeze`;
3. дождаться `cgroup.events frozen=1` в ограниченный конфигом срок; timeout → thaw, no kill;
4. под kernel freeze повторить starttime/cgroup/exe/argv0;
5. при совпадении послать pidfd `SIGKILL`, при несовпадении не сигналить;
6. в `finally` записать `0`; отдельный `ExecStopPost`/startup recovery также всегда thaw'ит.

Пока `frozen=1`, член cgroup не может выполнить same-PID `exec`, а внешний `SIGCONT` не
возобновляет его. Guard не пишет в `cgroup.kill` и не сигналит по номеру PID. Цена hard
guarantee — краткая остановка **всего** `orchestra.service` только при реальном срабатывании
threshold. Она должна быть измерена на отдельной synthetic cgroup; если freeze не
завершается в budget, guard fail-closed: thaw и journal alert, но no kill. Полное доказательство
остаётся AC реализации; финальный Codex-раунд новую схему не видел из-за потолка двух раундов.

### 4. In-process watcher не годится как основной предохранитель — CONFIRMED по механизму, LIKELY по конкретной задержке

Linux обозначает `D` как uninterruptible sleep, обычно ожидание I/O [S8][S9]. В отличие от
`TASK_INTERRUPTIBLE`, `TASK_UNINTERRUPTIBLE` не просыпается досрочно от сигнала [S10]. В
аварийном срезе leader uvicorn был `Dl`, а три loopback-запроса `/login` подряд не уложились
в 20 000 мс; после убийства ugrep тот же endpoint отвечал за 3.5 мс [M1].

Периодическая coroutine внутри Orchestra зависит от того же процесса и uvicorn event loop.
Если его event-loop thread ждёт диск в `D`, coroutine не получит слот до возврата потока.
Один `ps`-срез не доказывает, что все native threads процесса были неподвижны всю аварию,
поэтому конкретную задержку помечаю LIKELY. Но для safety boundary достаточно более слабого
и подтверждённого вывода: **in-process watcher не имеет независимого пути исполнения и не
гарантированно сработает при наблюдённом отказе**.

### 5. Выбор места: OS stopper + Orchestra reporter — LIKELY, разделённый гибрид

| Вариант | Что подтверждено | Вердикт |
|---|---|---|
| Coroutine в Orchestra | знает worker/task/TG, но разделяет event loop, cgroup и I/O fate с uvicorn | не primary guard; максимум будущий reporter |
| systemd timer + oneshot | отдельный cgroup, но на каждом тике должен стартовать и page-in новый процесс во время I/O pressure | лучше приложения, хуже уже резидентной службы |
| маленькая systemd-служба | отдельный процесс/cgroup, уже находится в памяти, читает только `/proc`, не зависит от ответа uvicorn | **единственный owner stop-policy** |
| гибрид | OS останавливает и durable-пишет event; Orchestra после восстановления только доставляет event в TG | **рекомендовано целиком** |

Stopper — stdlib-only Python daemon, без HTTP/SQLite/TG и без импорта Orchestra.
Она сканирует `/proc`, открывает pidfd только для кандидата, логирует decision и выполняет
freeze–verify–kill–thaw только после `cgroup.events frozen=1`. Для embedded search это fail-loud
и не рискует оставить запись БД наполовину: процесс только читает дерево. Сигнал не сможет
выдернуть находящийся в `D` task мгновенно, но останется pending и завершит его при выходе из
uninterruptible wait [S10].

Контрольная неэкономленная реализация полного `/proc`-скана по 242 PID заняла 7.08 с на 100
проходов, то есть 70.8 мс/проход, и 11 904 KiB peak RSS [M8]. При calibration-периоде 10 с
это около 0.71% одного CPU, при armed-периоде 60 с — 0.12%, даже до оптимизации. Сама
служба не попадает под `orchestra.service` `MemoryHigh`/`MemoryMax`.

Stopper одновременно пишет structured journal и атомарный event-файл без cmdline/env в
`/var/lib/orchestra-process-guard/events/`. После thaw/recovery узкий reporter Orchestra
подбирает event, отправляет важное TG-сообщение и помечает delivery; при недоступном TG event
остаётся для retry. До восстановления приложения journal остаётся ground truth.

Это не два владельца одной мысли. Только OS stopper читает policy, матчится, freeze'ит и
сигналит; reporter не знает thresholds, не читает `/proc` и не имеет signal/cgroup
permissions. Его контракт — `event file → TG → delivery marker`. Поэтому наблюдённое
`D`-состояние может лишь задержать объяснение до восстановления, но не остановку виновника.

### 6. Policy и значения порогов — direct armed values пока UNCERTAIN

Первый observe-only конфиг содержит как минимум:

```text
TARGET_CGROUP=/system.slice/orchestra.service
TARGET_EXE=/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe
TARGET_ARGV0=ugrep
MAX_AGE_SEC=181       # provisional, только DRY_RUN
MAX_RSS_KIB=528578    # provisional, только DRY_RUN
POLL_SEC=10           # calibration; armed interval определяется после неё
RSS_ACTION=log        # RSS kill запрещён без peak evidence
DRY_RUN=true
```

Эти числа ограничивают область калибровки, но **не разрешены как armed policy**:

- В live DB за 2026-08-05…до аварии найдено 234 завершённых Claude Bash tool calls,
  содержащих `grep`: median 0.238 с, p90 9.103 с, p95 19.718 с, p99 120.352 с,
  max 120.861 с; 0/234 были дольше 180 с. Четыре верхних около 120 с были compound-командами,
  где `grep` был лишь частью pytest/curl/edit pipeline [M9]. Это длительность Bash tool call,
  не direct lifetime embedded ugrep; скопление около 120 с также совместимо с timeout
  censoring. Поэтому `181` — только гипотеза dry-run, не статистически выведенный limit.
- Самый ранний аварийный endpoint — два процесса возрастом около 12 минут с RSS 2 114 312 и
  2 633 612 KiB. Первый эпизод дошёл до 49 минут и 3.3 GiB [M1]. Это задаёт верхнюю границу
  worst-case detection: `armed age threshold + armed poll interval` обязаны быть существенно
  меньше 720 с. Точное начало деградации не логировалось, линейность роста не предполагается.
- В 12 безопасных ограниченных пробах embedded ugrep — явные файлы, `app/`, `tests/`, 45 MiB
  `docs/` и текущая SQLite размером 181 231 616 bytes с `-I` — wall time был 0.01–0.16 с,
  max RSS 8 960 KiB [M10]. Минимальный runaway RSS был 2 114 312 KiB. RSS policy выбрана как
  `2 114 312 / 4 = 528 578 KiB`: это в 59.0 раза выше максимума безопасной пробы и в 4 раза
  ниже минимального аварийного среза. Делитель 4 — выбранный safety factor, не измеренный
  максимум легитимного recursive search, поэтому значение также только dry-run hypothesis.

Первый суточный цикл установки должен быть `DRY_RUN=true` при сохранённой временной
аварийной защите. Он записывает direct samples `(pid, starttime, age, VmRSS, VmHWM)`
exact-match `ugrep` с коротким calibration interval. `/proc/PID/status` определяет `VmHWM`
как peak RSS high-water mark, хотя man page предупреждает о неточности этого счётчика
[S14][S15]. Он не теряет уже прошедший пик увиденного процесса, в отличие от sampled
`VmRSS`; процесс, целиком проживший между двумя scans, всё равно останется невидимым [C2].

До чтения результата заранее фиксируется расчёт **age only**: геометрическое среднее между
максимальным direct lifetime завершённого легитимного exact-match процесса за цикл и
минимальным аварийным endpoint 720 с. Armed age policy разрешена только если
`age threshold + poll interval < 720 с` и controlled replay не убивает negative controls.
Иначе данных недостаточно и гейт не открыт.

RSS в первой armed версии остаётся `RSS_ACTION=log`: поле и threshold конфигурируемы, но не
могут инициировать freeze/kill. Включить `RSS_ACTION=kill` можно лишь после двух независимых
evidence paths: `VmHWM` каждого увиденного процесса за dry-run и `/usr/bin/time -v`/wait4
peak RSS на controlled worst-case searches по крупнейшим реально используемым scope/DB.
Threshold обязан быть выше каждого legitimate peak и всё ещё ниже 2 114 312 KiB; если
разделения нет, RSS-kill не включается. Это отдельный последующий гейт, не скрытая часть T3.

Один суточный цикл не доказывает недельный worst case; это сознательный остаточный риск.
Требование fail-loud означает, что недостаток direct observations нельзя маскировать точным
на вид числом из 234 косвенных Bash durations.

Лог до сигнала должен содержать: timestamp, PID/PPID, start time, cgroup, basename exe,
`argv0`, фактические age/RSS, сработавший threshold, `dry_run`, signal/result. Полную cmdline и
environment не логировать: там могут быть запросы и секреты. Утреннее доказательство:
`journalctl -u orchestra-process-guard --since yesterday`.

Экстренное отключение guard в одну команду:

```bash
sudo systemctl disable --now orchestra-process-guard.service
```

### 7. Оценка resource-limit вариантов

#### `ulimit -m` / `RLIMIT_RSS` — REFUTED

Linux man page говорит, что этот лимит имел эффект только в Linux 2.4.x до 2.4.30 и только
для `madvise(MADV_WILLNEED)` [S5]. Проба `ulimit -m 1024` позволила Python потрогать 32 MiB
и завершиться с max RSS 51 892 KiB [M11]. Как предохранитель он не работает.

#### Глобальный `ulimit -v` / `RLIMIT_AS` — REFUTED; точечный wrapper — UNCERTAIN

`RLIMIT_AS` ограничивает virtual address space и наследуется через fork/exec [S5]. На живой
машине легитимный Chrome renderer имел VSZ около 1.4 TiB при ~98 MiB RSS, Claude CLI — около
70 GiB VSS при 150–270 MiB RSS, uvicorn — 4.8 GiB VSZ при 1.46 GiB RSS; аварийный embedded
ugrep — около 10.2 GiB VSZ [M12]. Глобальный AS-limit, достаточно низкий для ugrep, убьёт
легитимные процессы; достаточно высокий для Chrome/Claude — не остановит ugrep.

Точечный `ulimit -v` внутри wrapper теоретически ограничит только ugrep. Пробы с 2 GiB
RLIMIT_AS прошли bounded repo searches, но runaway не воспроизводился [M10]. Значение,
которое гарантированно остановит дефект и не сломает редкий легитимный поиск, не измерено.
Это допустимо только как последующий defense-in-depth после наблюдения, не основной guard.

#### `timeout` wrapper — UNCERTAIN и уже не нужен после `unset -f`

Shell-функция, загруженная через `CLAUDE_ENV_FILE` после snapshot и вызывающая абсолютные
`/usr/bin/timeout` + `/usr/bin/grep`, переживёт прежний `unalias`. Но Claude Code по
официальной документации при Bash timeout по умолчанию переводит команду в background, а не
останавливает; `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` меняет это ценой запрета всех
background tasks [S2]. `CLAUDE_CODE_SHELL_PREFIX` также охватывает hooks/statusline/stdio MCP,
поэтому глобальный timeout там ломает легитимные долгоживущие команды [S1]. После возврата к
GNU grep нерекурсивный дефолт уже убирает наблюдённый механизм аварии; wrapper не нужен в v1.

#### `CPUWeight` — REFUTED для этой аварии

Все агенты и uvicorn находятся внутри одного `orchestra.service`, поэтому вес юнита не
разделяет виновника и жертву. Наблюдавшийся bottleneck — memory reclaim/swap/disk wait, а не
недостаток относительной доли CPU [M1].

### 8. `MemoryHigh=8G` снять после активации guard; `MemoryMax=12G` пока оставить

Текущее live-состояние:

```text
MemoryHigh=8589934592
MemoryMax=12884901888
MemorySwapMax=infinity
OOMPolicy=stop
OOMScoreAdjust=800
memory.events: high=30 530 052, max=0, oom=0
```

[M13]. Kernel cgroup v2 docs: `memory.high` никогда не вызывает OOM, а ограничивает cgroup
throttling и тяжёлым reclaim; `memory.max` — hard limit, который вызывает cgroup OOM, если
reclaim не может опустить потребление [S6].

Во втором эпизоде cgroup был около 8.58 GiB при `MemoryHigh=8G`, swap — 17.174 из 17.180 GiB,
memory PSI full avg10 — 74.20% (cgroup 74.74%), load — 57.34; один ugrep был `D`, а команда
с `free`/`uptime` исполнялась 51 с. `pgscan_direct` дошёл примерно до 924 687 718. После
cleanup: RAM 6 GiB, swap 2/15 GiB, PSI full avg10 0.49% [M1]. Это прямой контрпример
`MemoryHigh` как предохранителю: он размазал рост RAM в direct reclaim и disk I/O.

`MemoryMax` не селективен: внутри cgroup находятся uvicorn и все подпроцессы агентов, а
`OOMPolicy=stop` допускает остановку всей службы после OOM. Он может убить pytest/Python,
Chrome, обычного агента или uvicorn — ровно то, что требования запрещают. Кроме того,
`memory.max` и swap accounting разделены; текущий `MemorySwapMax=infinity` не препятствует
повтору swap storm [S6][M13].

**Решение:** после того как внешний selective guard прошёл dry-run и включён, удалить
`MemoryHigh=8G` из постоянного drop-in и очистить только его runtime property. Оставить
`MemoryMax=12G` и `OOMScoreAdjust=800` неизменными как последний неселективный fail-safe,
но не считать их основным предохранителем. `memory.events max=0, oom=0` подтверждает, что
`MemoryMax` не вызвал наблюдённый I/O hang; одновременно данных недостаточно, чтобы доказать
безопасность его удаления или вывести другое значение [M13][C1].

`MemoryMax` остаётся UNCERTAIN trade-off: при достижении он может остановить легитимную
работу/Orchestra, зато покрывает неизвестный runaway, отказ guard и пока незащищённый `bfs`.
Его отдельное решение требует process accounting суммарных легитимных пиков, host
`MemAvailable`, swap trajectory и controlled cgroup rehearsal. Не менять `MemoryMax` в #211
без этих измерений. До активации selective guard не снимать и `MemoryHigh`: одностороннее
удаление сейчас оставит временную защиту слабее в период гейта.

## Counter-evidence and limits

- `CLAUDE_ENV_FILE` — документированный hook и сейчас полностью убирает функции; это сильный
  довод, что OS guard не должен быть единственной мерой. Но порядок hook/snapshot не является
  публичным контрактом, а уже подключённые процессы не получают новую env без reconnect.
- Отдельная systemd-служба всё равно делит тот же физический диск/ядро: при полном kernel или
  storage stall она тоже может опоздать. Её преимущество — независимость от uvicorn event
  loop и cgroup throttling, не абсолютная realtime-гарантия.
- Cgroup freeze закрывает same-PID `exec`/`SIGCONT` race, но на время проверки приостанавливает
  весь `orchestra.service`. Это допустимо только после synthetic rehearsal с жёстким budget и
  доказанным аварийным thaw; freeze timeout обязан закончиться thaw без kill.
- Один `D`-срез не доказывает длительность блокировки всех uvicorn threads. Три 20-секундных
  loopback timeout и мгновенное восстановление после kill делают отказ in-process path
  вероятным, но не превращают его в формальную трассировку scheduler.
- RSS safe-set — 12 bounded probes, а не непрерывный process accounting. Поэтому 181 с и
  528578 KiB — только observe-only hypotheses; первая armed версия не разрешает RSS-kill.
- Guard v1 защищает только доказанный `argv0=ugrep`. Добавлять `bfs` в kill-policy без
  отдельного runaway-наблюдения и калибровки нельзя.
- Финальный допустимый Codex-раунд завершился `Request changes` до появления cgroup-freeze и
  `RSS_ACTION=log`. Потолок prose-дебата исчерпан; эти два исправления не имеют независимого
  третьего verdict и должны быть приняты либо отклонены оркестратором на гейте [C2].

## Affected files and system objects for later phases

Phase 1 ничего из списка не меняет.

- tracked: `scripts/orchestra_process_guard.py`;
- tracked: `deploy/orchestra-process-guard.service`;
- tracked: `deploy/orchestra-process-guard.conf`;
- tracked: `deploy/manage-process-guard.sh`;
- tracked: `tests/test_process_guard.py`;
- tracked reporter: `app/process_guard_events.py`, `app/main.py`, `app/tg_bridge.py`,
  `tests/test_process_guard_events.py`;
- host install: `/usr/local/libexec/orchestra-process-guard`,
  `/etc/orchestra-process-guard.conf`,
  `/etc/systemd/system/orchestra-process-guard.service`,
  `/var/lib/orchestra-process-guard/events/`;
- optional defense-in-depth: `/etc/orchestra/claude-env.sh` + systemd environment drop-in for
  `CLAUDE_ENV_FILE` (requires an explicitly approved maintenance reconnect/restart);
- existing `/etc/systemd/system/orchestra.service.d/oom.conf` and runtime `MemoryHigh`
  property — only after external guard activation; `MemoryMax=12G` remains unchanged.

## Sources and measurements

### Primary external sources opened this session

1. [S1] Claude Code, Environment variables and shell configuration:
   https://code.claude.com/docs/en/env-vars
2. [S2] Claude Code, Tools reference / Bash timeout and background behavior:
   https://code.claude.com/docs/en/tools-reference
3. [S3] Claude Code, Settings reference:
   https://code.claude.com/docs/en/settings
4. [S4] Claude Code settings JSON schema:
   https://json.schemastore.org/claude-code-settings.json
5. [S5] Linux `getrlimit(2)`:
   https://man7.org/linux/man-pages/man2/getrlimit.2.html
6. [S6] Linux kernel cgroup v2 memory controller:
   https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html
7. [S7] Linux kernel Pressure Stall Information:
   https://cdn.kernel.org/doc/html/latest/accounting/psi.html
8. [S8] Linux `ps(1)` process states:
   https://www.man7.org/linux/man-pages/man1/ps.1.html
9. [S9] Linux `/proc/PID/stat` state field:
   https://www.man7.org/linux/man-pages/man5/proc_pid_stat.5.html
10. [S10] Linux kernel task state/wakeup semantics:
    https://docs.kernel.org/5.19/driver-api/basics.html
11. [S11] Linux `signal(7)`, pidfd signals and uncatchable `SIGSTOP`:
    https://man7.org/linux/man-pages/man7/signal.7.html
12. [S12] Linux `ptrace(2)` / group-stop semantics:
    https://www.man7.org/linux/man-pages/man2/ptrace.2.html
13. [S13] Linux kernel cgroup v2 freezer (`cgroup.freeze`, `cgroup.events frozen`):
    https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html?highlight=freezer
14. [S14] Linux kernel procfs fields (`VmHWM` = peak resident set size):
    https://www.kernel.org/doc/html/v6.15/filesystems/proc.html
15. [S15] Linux `proc_pid_status(5)`, including the `VmHWM` accuracy caveat:
    https://man7.org/linux/man-pages/man5/proc_pid_status.5.html

### Direct measurements

- [M1] Task #211 incident telemetry and two live incident captures supplied by the
  orchestrator: process parents/argv, RSS/age/state, load, cgroup memory, swap, PSI,
  `pgscan_direct`, loopback latency before/after cleanup.
- [M2] Read all current `/home/kesha/.claude/shell-snapshots/snapshot-bash-*.sh`; final count
  19, block at lines 102–132 in both hashes.
- [M3] `claude --version → 2.1.197`; read strings around snapshot generator and
  `CLAUDE_ENV_FILE` assembly in installed native binary; binary SHA-256
  `f54e69d15b…cf7f83`.
- [M4] Four snapshot sourcing probes with default/safe/simple/nonessential env variants.
- [M5] Snapshot → `unset -f grep find` ordering probe and GNU tool versions.
- [M6] Controlled `exec -a`/`Popen(executable=…)` probe of `comm`, status Name and NUL cmdline.
- [M7] Local Python capability check: `pidfd_open=True`, `pidfd_send_signal=True`;
  kernel userspace is systemd 255, `CLK_TCK=100`.
- [M8] 100 full `/proc` scans over 242 PIDs: 7.08 s elapsed, 11 904 KiB max RSS.
- [M9] Read-only live SQLite query over 234 completed Claude Bash calls containing `grep`,
  2026-08-05…pre-incident; raw duration quantiles recorded above.
- [M10] 12 bounded embedded-ugrep probes, including 181 231 616-byte SQLite and 45 MiB docs;
  0.01–0.16 s, max RSS 8 960 KiB. RLIMIT_AS probe included 2 GiB.
- [M11] `RLIMIT_RSS=1024 KiB` counterexample: 32 MiB touched, max RSS 51 892 KiB, exit 0.
- [M12] Read-only `/proc` VSZ/RSS snapshot of legitimate Chrome, Claude CLI and uvicorn versus
  incident ugrep.
- [M13] `systemctl show/cat orchestra`, cgroup v2 `memory.events` and swap files; final read:
  MemoryCurrent 3 270 955 008, MemoryPeak 9 003 102 208,
  MemorySwapCurrent 1 931 300 864 bytes.
- [M14] Final `/proc` target validation: all eight live Claude executables inside
  `/system.slice/orchestra.service` resolved to
  `/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`; an unrelated service had
  a different bundled Claude path but was outside target cgroup.
- [C1] Codex adversarial second opinion, round 1:
  `docs/tasks/211/codex-review-research.md`; verdict `Request changes`, findings on same-PID
  `exec` race, unproven armed thresholds, `MemoryMax` evidence and incomplete rollback.
- [C2] Same artifact, round 2 (final prose round): `Request changes`; accepted the revised
  `MemoryMax` and rollback decisions, rejected `SIGSTOP` against external `SIGCONT`, and
  rejected sampled `VmRSS` as peak calibration. Cgroup-freeze and RSS log-only changes were
  made after the round and were not re-reviewed because the skill ceiling is two rounds.
