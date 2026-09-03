# #113 — кто съедает память машины

Дата измерений: 2026-08-01, Asia/Krasnoyarsk. Только read-only диагностика: процессы не останавливались, сервис и машина не перезапускались.

## Вопрос

- **Контекст:** ноутбук с 15.36 GiB RAM и 31.68 GiB swap, Orchestra под systemd, агентские CLI и отдельные stdio-MCP на сессию.
- **Изменение под проверкой:** считать не сумму RSS, а resident `PSS` + proportional swapped `SwapPss`; отдельно проверить main PID, session trees, MCP, desktop apps и динамику swap.
- **Baseline:** стартовая RSS-разбивка из задачи и гипотеза «main Orchestra течёт неделями».
- **Решающие метрики:** GiB `PSS`, private resident, proportional shared resident, `SwapPss`, `PSS+SwapPss`; для недоступных sandboxed desktop-процессов — только явно помеченный cgroup-v2 charge (`memory.current + memory.swap.current`).

`PSS` делит shared page между всеми отображающими её процессами; `SwapPss` делает то же для swapped pages. Поэтому рабочая метрика retained process footprint здесь — **`PSS + SwapPss`**, а не RSS и не сумма `VmSwap` [1]. Для whole-cgroup контроля использованы `memory.current` и `memory.swap.current`; они дополнительно включают page cache и kernel memory, поэтому cgroup charge нельзя молча называть PSS [2].

## Гипотезы и falsifiers

1. **H1: main PID растёт из-за 80–100 объектов сессий/логов.** Неверно, если stored payload сессий занимает мегабайты, а main footprint сосредоточен в больших anonymous mappings и совпадает с измеренным ONNX/RAG footprint.
2. **H2: давление создают деревья живых агентов и их MCP.** Неверно, если process-tree `PSS+SwapPss` мал или основная память находится вне `orchestra.service`.
3. **H3: виноваты главным образом браузер/Telegram/desktop.** Неверно, если изолированный cgroup Orchestra существенно больше user desktop cgroups.
4. **H4: swap — старый мусор после недель uptime.** Неверно, если машина только что загрузилась, а swap быстро набрался вместе с новыми agent/review trees.

## Методика и ограничения

- Каждый доступный PID снимался из `/proc/<pid>/smaps_rollup`: `Pss`, `Private_Clean+Private_Dirty`, `SwapPss`. Shared proportional resident вычислялся как `Pss - private`.
- Дерево сессии — все descendants прямого CLI-child main PID 1543. Статус (`idle/running/waiting`) сопоставлялся с read-only `data/orchestra.db`.
- `orchestra.service` перепроверялся через cgroup v2: `memory.current`, `memory.swap.current`, `memory.stat`, `memory.peak`, `memory.swap.peak`.
- Opera/Chromium запрещают чтение `smaps_rollup` даже тому же UID. Для desktop-приложений показан **cgroup charge**, не фальшивый PSS. Cgroup-строки не складываются с process-PSS без оговорки.
- Система активно менялась во время исследования: число live workers/reviews росло и падало. Основная таблица — snapshot 14:21:58; диапазоны и второй snapshot указаны отдельно.
- `tracemalloc` не был включён при запуске PID 1543; безопасно подключить его к уже работающему Python 3.12 без инъекции/рестарта нельзя (`ptrace_scope=1`). Граница задачи запрещает рестарт и вмешательство, поэтому Python allocation stacks не снимались. Вместо этого использованы page-level `smaps`, lifetime high-water mark, динамический trace и ранее воспроизведённый изолированный RAG benchmark [3].

## Честная картина: Orchestra по PSS + SwapPss

Локальные строки сняты в 14:21:58. Serena вместе с её wrappers/language servers заменена готовым числом #112, как потребовал orchestrator; она не пересчитывается [4]. Строка Serena получена другим воркером в другой момент и включает четыре temporary review instances, тогда как локальный snapshot застал три reviews. Поэтому таблица даёт **составной бюджет классов, а не атомарный snapshot**, и итог нельзя вычитать из одновременного cgroup charge как точную разницу.

| Класс | Процессов | PSS resident, GiB | private resident, GiB | shared proportional, GiB | SwapPss, GiB | retained, GiB |
|---|---:|---:|---:|---:|---:|---:|
| Serena + её language servers | 79 в деревьях #112 | см. #112 | см. #112 | см. #112 | см. #112 | **4.09** |
| Обычные agent CLI (Claude/Codex), без review | 40 | 1.801 | 1.599 | 0.202 | 0.829 | **2.630** |
| Main Orchestra, PID 1543 | 1 | 1.028 | 1.027 | ~0.000 | 0.574 | **1.602** |
| Обычные `app/mcp_stdio.py` | 23 instances | 0.399 | 0.386 | 0.012 | 0.709 | **1.107** |
| Прочие MCP, без Serena и review | 27 processes | 0.366 | 0.354 | 0.012 | 0.665 | **1.031** |
| Другие descendants Orchestra | 47 | 0.236 | 0.193 | 0.044 | 0.539 | **0.776** |
| 3 одновременных `codex_review`, **без Serena** | 30 | 0.496 | 0.466 | 0.031 | 0.000 | **0.496** |
| **Локальный subtotal без Serena** | — | — | — | — | — | **7.64** |
| **Composite estimate с Serena #112** | — | — | — | — | — | **≈11.73** |

Контроль локального cgroup в тот же интервал: `memory.current=7.87 GiB`, `memory.swap.current=7.54 GiB`, итого **15.41 GiB charged retained**. Это отдельная whole-unit метрика, не сверка `15.41 - 11.73`: cgroup также считает file cache/kernel memory, shared pages заряжаются иначе, а Serena взята из другого snapshot. Lifetime peaks с boot: resident **9.35 GiB**, swap **9.65 GiB**. Process table отвечает «каким классам атрибутированы страницы», cgroup — «сколько всего заряжено unit» [M1].

### Дубли прочих MCP

Отдельный executable-level snapshot дал [M2]:

| MCP | Instances | PSS+SwapPss, MiB | Среднее на instance |
|---|---:|---:|---:|
| KWin MCP | **17** | **681.0** | 40.1 |
| websearch node | 6 | 124.6 | 20.8 |
| workspace-mcp | 1 | 94.8 | 94.8 |
| mailru-mcp | 1 | 62.2 | 62.2 |
| yougile-mcp | 1 | 54.1 | 54.1 |

Главный не-Serena дубль — KWin: desktop-control MCP поднят 17 раз, хотя большинству агентов он не нужен. У Codex причина видна в `/home/maxim/.codex/config.toml`: глобально включены Serena, Orchestra, OpenAI docs и KWin; managed Codex и прямой `codex_review` наследуют native config. `CodexBackend._mcp_config_args()` добавляет обязательный per-worker Orchestra, но не выключает остальные global servers (`app/backend_codex.py:1244-1274`).

## Посторонние приложения

У Opera `smaps_rollup` закрыт sandbox policy, поэтому здесь **не PSS**, а leaf cgroup-v2 `resident charge + swap charge` в 14:17. Эти значения не имеют RSS double-count и дают честный отдельный бюджет desktop cgroups, но включают file/kernel charge [M3].

| Desktop cgroup | resident charge, GiB | swap charge, GiB | retained charge, GiB |
|---|---:|---:|---:|
| Opera + Chromium scope | 1.538 | 2.624 | **4.161** |
| Steam | 0.126 | 1.037 | **1.163** |
| Plasma shell + KWin | 0.451 | 0.428 | **0.877** |
| Telegram Desktop | 0.075 | 0.731 | **0.806** |
| Slack (2 scopes) | 0.136 | 0.453 | **0.589** |
| Остаток user session | 0.270 | 0.612 | **0.885** |
| **user@1000.service total** | **2.596** | **5.885** | **8.481** |

H3 **REFUTED как единственное объяснение**, но desktop не безобиден: browser retained charge 4.16 GiB сопоставим с Serena. При этом `orchestra.service` удерживал 15.41 GiB cgroup charge — платформа всё же крупнейший единый потребитель.

## Main Orchestra PID 1543

### Растёт ли он во времени

Стартовая предпосылка «процесс живёт неделями» сейчас неверна: `ActiveEnterTimestamp=10:52:37`, и журнал показывает полный `LINUX RESTART` в 10:52. На момент замера PID жил 3 ч 32 мин. Поэтому **рост за недели этим процессом проверить невозможно**; старый PID исчез при boot [M4].

За короткий trace найден не monotonic leak, а обратимый burst:

| Время | PSS, MiB | SwapPss, MiB | PSS+SwapPss, MiB |
|---|---:|---:|---:|
| 14:14:43 | 1114.6 | 691.6 | 1806.2 |
| 14:14:48 | 1621.9 | 690.6 | 2312.4 |
| 14:14:53 | 1704.6 | 690.6 | **2395.1** |
| 14:14:58 | 984.9 | 655.7 | 1640.6 |
| 14:15:03 | 986.2 | 654.3 | 1640.6 |

За 15 секунд footprint вырос на 0.59 GiB и полностью вернулся. В 14:14:43 завершился merge `frontend`; код на каждый успешный merge запускает fire-and-forget `rag_service.backfill_scope()` (`app/routes/sessions.py:727-738`). Lifetime `VmHWM` main PID — **3.0 GiB RSS**, current `VmRSS` 1.05 GiB + `VmSwap` 0.56 GiB [M5]. Это подтверждает большие transient peaks, но не monotonic growth.

**Confidence: CONFIRMED для текущего процесса; UNCERTAIN для недельного горизонта** — исторической per-PID телеметрии нет.

### Что реально держится в main

1. **Large anonymous mappings — подтверждённый кусок; RAG/ONNX — вероятный owner.** В текущем PID 17 anonymous mappings размером ≥50 MiB удерживали **1.473 GiB PSS+SwapPss**; всего mappings ≥1 MiB — 1.613 GiB. Это не file-backed `vec.db`, но `smaps` не различает ONNX arena, Python heap и другие native allocators [M6]. Предыдущий изолированный benchmark на этой же машине измерил bge-m3 int8: **946 MiB idle**, **1.6 GiB peak при batch=16**, **2.4 GiB peak при batch=64** [3]. Текущий default — `EMBED_BATCH=64` (`app/rag.py:46`), а live peak 2.395 GiB совпал с диапазоном benchmark. Совокупность делает RAG/ONNX **LIKELY**, но не даёт allocation-level доказательства.
2. **Persisted session histories — не гигабайты.** В БД 80 rows подходили под auto-resume; их UTF-8 payload: prompts **1.754 MiB**, summaries **0.094 MiB**, session history **0.011 MiB**, runtime handoff 0. Даже с Python overhead именно этих полей это на два порядка меньше 1 GiB [M7]. `session_id_history` явно обрезается до 10 (`app/session.py:704-711, 1351-1358`). Live backend/native state этим SQL не измерен.
3. **Логи — в SQLite, не global list.** 81,376 rows / 146.6 MiB content находятся на диске; `_conn()` открывается на операцию, `get_logs()` закрывает собственный connection (`app/db.py:23-34, 931-947`). Текущий unindexed RAG backlog — 384 rows / **0.18 MiB**, поэтому `fetchall()` сейчас не объясняет сотни MiB [M7].
4. **Live SSE broker ограничивает queues, но не stream accumulation.** Subscriber queue имеет `maxsize=256` и удаляется при unsubscribe. Однако `_accum[session_id] += chunk` не имеет byte cap и очищается только на final `text`; error/disconnect/archive без final text оставляет строку (`app/live_broker.py:12-62`, единственный call `clear_accum` — `app/session.py:941`). Это реальная unbounded collection, но её live size без инструмента не измерен, поэтому **не приписываю ей текущие GiB**.

### Другие unbounded структуры, найденные в коде

| Структура | Верхняя граница | Фактический статус |
|---|---|---|
| `LiveBroker._accum` | **нет** по bytes/entries | Настоящий leak path при незавершённом stream; current bytes UNCERTAIN |
| `AgentSession._tool_names_by_id` | **нет**; pop только при matching result | Interrupted tool может оставить id навсегда; текущий размер UNCERTAIN |
| `AgentSession._pending_messages` | **нет** | Растёт только пока compact/race/inject failure; виден по status logs |
| `AgentSession._turn_logs` | **нет** по bytes одного turn | Reset на следующем turn, history не копится бесконечно |
| `SessionManager._session_locks` | **нет** по когда-либо увиденным IDs | Чистится только shutdown; object мал, текущие session payload всего 1.86 MiB |
| `tg_bridge._buffers` | **нет** по session IDs | Entries очищаются после flush, сами states — только shutdown |
| `RagMemory.backfill_logs().fetchall()` | **нет**; параметр `batch_size` не используется для fetch | Сейчас backlog 0.18 MiB; потенциальный peak на массовом initial backfill |

**Вывод по H1:** узкая гипотеза «1.9 GiB main = persisted histories и дисковый log cache 100 сессий» **REFUTED**. RAG/ONNX — наиболее вероятное объяснение больших anonymous mappings и batch peaks, но `smaps` не доказывает owner, а весь live heap/backend state не измерен. Unbounded Python structures существуют и должны быть bounded, но данных, что именно они сейчас держат GiB, нет.

## Idle sessions и цена гибернации #111

Стартовое «82 idle-сессии держат live CLI» не подтвердилось после свежего boot:

- DB: 81 non-archived rows, из них 64 `idle`.
- Process tree 14:22:38: **22 live CLI roots**, из них **9 idle**, 9 running, 4 waiting.
- `auto_resume_all()` создаёт `AgentSession` для resumable rows, но `AgentSession.start()` без message лишь ставит `IDLE`; backend появляется только через `_ensure_backend()` при send (`app/manager.py:1177-1231`, `app/session.py:580-588`). Поэтому DB idle ≠ live process.

Атрибутивный footprint именно текущих 9 idle live trees [M8]:

| Что атрибутировано idle trees | GiB |
|---|---:|
| resident PSS | **1.106** |
| SwapPss reservation | **2.429** |
| **retained total** | **3.535** |

Это полные trees, включая относящийся к ним кусок Serena; число **нельзя складывать** с 4.09 GiB Serena или с CLI/MCP строками как независимую экономию. Два snapshots дали близкий диапазон: 8 idle roots / 3.30 GiB retained в 14:10 и 9 roots / 3.54 GiB в 14:22. Это доказанная атрибуция страниц, но не before/after gain: после остановки изменятся proportional shares, а file cache может остаться. Поэтому **3.30–3.54 GiB — gross ceiling/приоритет #111**, фактическое немедленное освобождение нужно измерить после внедрения.

## `codex_review`: временные MCP и lifetime

Read-only выборка `bg_jobs` за текущий boot: 21 review jobs — 10 successful (`329.5 s` average, `599 s` max), 6 expired, 2 failed, 3 active на момент SQL. Hard timeout в коде — 600 s (`app/mcp_stdio.py:1060-1075`) [M9].

У одного активного review-tree стабильно поднимаются:

- 1 Serena root + её Pyright tree: около **0.168 GiB retained/review** по готовому замеру #112 (0.67 GiB / 4 temporary instances) [4];
- 1 лишний Orchestra MCP: **~0.047 GiB**;
- 1 лишний KWin MCP: **~0.040 GiB**;
- сам Codex + shell/tee/helpers: остаток.

Четыре живых review trees были измерены по 12 процессов каждый: steady non-Serena retained **0.168–0.170 GiB/review**; один только стартовавший tree — 0.139 GiB. Полный steady tree с Serena — примерно **0.33 GiB**, из них **~0.255 GiB — MCP/language servers**. При 3 одновременных reviews это около **1.0 GiB retained**, при 4 — **1.3 GiB** [M10].

После завершения job постоянных orphan MCP в snapshot не найдено: все cgroup PIDs имели живого ancestor внутри `orchestra.service`. Код ждёт pipe EOF 2 s, затем `SIGTERM` process group, ещё 2 s и `SIGKILL`, **только если inherited stdout остаётся открытым** (`app/bg_jobs.py:676-706`). Descendant, закрывший stdout до EOF, может пережить leader, потому что финальный `_kill_proc()` возвращает при завершившемся leader (`app/bg_jobs.py:114-133`). Поэтому измерение подтверждает «orphans сейчас не найдены», но кодовой верхней границы lifetime нет.

Вывод: измеренный review overhead живёт весь **5.5–10-минутный job** и работает как concurrency multiplier. В текущем snapshot недельных orphan trees нет, но cleanup-path не даёт гарантии, что они невозможны. Прямому file/diff review Serena, Pyright, KWin и Orchestra MCP не нужны.

## Swap: что туда вытеснено и почему

Машина загрузилась в 10:52. `sar` показывает [M11]:

| Время | swap used, GiB |
|---|---:|
| 11:10 | 2.08 |
| 13:10 | 1.43 |
| 13:20 | 3.99 |
| 13:30 | 9.90 |
| 14:10 | 12.46 |
| 14:20 | **14.39** |

Первый RAG search был в 13:16:28; с 13:22 началась серия merge→backfill, одновременно стартовали новые agent/review trees. Свежий boot и резкий рост после 13:10 **REFUTE H4**: это не swap, оставшийся от недельного uptime. Какую долю роста создал каждый новый tree/RAG burst, временной ряд сам по себе не устанавливает.

Состав swap виден в двух **пересекающихся проекциях**, которые нельзя складывать:

- По взаимно исключающим process classes локального snapshot без Serena: main 0.57 GiB; regular agent CLI 0.83; Orchestra MCP 0.71; other MCP 0.67; other descendants 0.54; non-Serena review overhead 0.00 GiB. Для Serena #112 передал только итоговый `PSS+SwapPss=4.09 GiB`, поэтому её resident/swap split здесь намеренно не реконструируется.
- По status trees: idle trees 2.43 GiB SwapPss. Эта строка включает относящиеся к ним Serena, CLI и MCP и нужна для цены #111, а не для partition общего swap.
- Отдельно desktop cgroups: browser 2.62 GiB, Steam 1.04, Telegram 0.73, Slack 0.45, Plasma 0.43 GiB.

Swap двухуровневый: 7.7 GiB zram (priority 5) + 24 GiB `/mnt/data/swapfile` на SSD (priority -2). В момент замера zram хранил 6.16 GiB logical data в **2.47 GiB реальной RAM**, disk swap — около 6.25 GiB. `vm.swappiness=10` уже низкий. Retained cgroup state (~15.4 GiB Orchestra + 8.5 GiB desktop) больше RAM и объясняет capacity pressure, но retained не равен active working set; отдельно измеренный fault/churn trace доказывает, что **часть** swapped pages остаётся активной [M12][M13]. Причинная доля RAG/reviews против других процессов — **LIKELY**, не измерена напрямую.

В 10-секундном окне измерено: system `pswpin +11,882 pages` = **46.4 MiB**, 9,728 major faults; из них Orchestra 11,610 pages и 9,542 faults. `vmstat` показывал до 20–21 MiB/s swap-in и 5–7% iowait. То есть часть swap действительно холодная, но активные agent pages регулярно fault back — это измеренный механизм лагов при низком CPU load [M13].

С boot cgroup Orchestra сделал 21.20 GiB page swap-out и 7.70 GiB page swap-in; system-wide — 30.25/11.26 GiB. Это churn, не просто пассивно занятый swap.

### Рестарт сервиса или reboot

- **Reboot не нужен как fix:** exit процессов удалит их private memory и swap entries, но нынешний boot при наблюдавшейся нагрузке за ~3.5 часа уже набрал 13–15 GiB swap. Один boot не гарантирует тот же профиль после следующего запуска, но доказывает, что reboot сам источник не устраняет.
- **Restart `orchestra.service`** удалит private memory/swap entries unit, но **11.7 GiB process footprint и 15.4 GiB cgroup charge — ceilings, не измеренный gain**: shared shares перераспределятся, cache может остаться. Restart прервёт running turns; running/waiting sessions снова поднимутся, а RAG загрузится на первом search. Это аварийная мера, не fix.
- **Selective idle hibernation** адресует 3.3–3.5 GiB gross attributable footprint без desktop/reboot и без убийства active trees; фактический gain требует before/after замера после завершения #111.
- `swapoff` сейчас опасен: logical swap больше `MemAvailable`; он спровоцирует OOM/ещё больший thrash. Не применять.

## Меры по ожидаемому выигрышу

Без разрешённого before/after эксперимента здесь можно честно дать только **gross attributable footprint/ceiling**. Это оценка порядка выигрыша, не обещание столько же немедленно увидеть в `MemAvailable`. Значения не аддитивны; колонка marginal явно показывает известные пересечения.

| Rank по gross GiB | Мера | Зона | Цена | Риск | Gross footprint / ожидаемый потолок | Известное пересечение / marginal |
|---:|---|---|---|---|---:|---|
| 1 | Закрыть/перезапустить browser с ненужными tabs | привычка, вне Orchestra | low | потеря tab state/cache warmth | **до 4.16 GiB cgroup charge** | cache/shared перераспределятся; actual gain не измерен |
| 2 | Serena on-demand/hibernate/shared вместо instance-per-agent | код/config, #112 | medium/high | задержка первого tool call, изоляция workspaces | **4.09 GiB retained** в #112 | включает **0.67 GiB** четырёх review Serena и Serena внутри idle trees |
| 3 | Довести #111: hibernate только реально idle live trees | код, уже в работе | low/medium | ошибка idle guard может прервать turn | **1.11 GiB resident PSS + 2.43 GiB SwapPss = 3.54 GiB** | включает Serena, CLI и MCP этих trees; после #112 marginal меньше |
| 4 | Отключить RAG или заменить меньшей моделью | продукт/config | low code, high product trade-off | хуже semantic recall | disable: **~0.95 GiB steady** по isolated benchmark; smaller model UNCERTAIN | включает batch peak #5; live owner остаётся LIKELY |
| 5 | `RAG_EMBED_BATCH=16` вместо current default 64 | config + restart | trivial | backfill batches мельче; прошлый benchmark не показал throughput gain от 64 | **~0.8 GiB меньше transient peak**, steady 0 | не складывать с полным отключением RAG |
| 6 | Не наследовать global Serena/KWin/Orchestra в `codex_review` | код/config | low | review лишится ненужных tools; проверить file access | **~0.255 GiB MCP/review**; ~0.76 GiB при concurrency=3 | из них ~0.168 Serena + ~0.040 KWin + ~0.047 Orchestra; после #112 marginal **~0.087 GiB/review**, после #112+#7 — ~0.047 |
| 7 | KWin MCP только роли `computer-use`, не всем Codex | config | low | забытый opt-in для GUI-задачи | **0.665 GiB regular KWin** (17 instances, review trees исключены из M2) | review KWin ~0.040/review уже входит в #6 |
| 8 | Cap/cleanup `_accum`, clear per-turn maps, реальный batched DB fetch | код | low/medium | regression streaming/backfill | current GiB gain **не доказан** | профилактика недельного роста, не текущий rescue |
| 9 | Reboot | привычка/операция | high disruption | всё останавливается | очищает process swap entries, но free-RAM gain не измерен | источник cardinality/RAG остаётся; при этой нагрузке swap вернулся за часы |

Закрытие Steam/Telegram/Slack тоже может вернуть до 2.56 GiB cgroup retained, но это внешние приложения, не платформа.

## Что чинится чем

### Код/config Orchestra

1. Закончить #111, но считать эффект по live process roots, не DB idle rows.
2. Убрать native global MCP inheritance у managed Codex и особенно у `codex_review`; дать review изолированный config с нулём local MCP.
3. Сделать KWin/Serena opt-in по роли.
4. Снизить RAG batch до 16; отдельно решить, стоит ли 946 MiB steady footprint качества bge-m3.
5. Поставить byte cap + lifecycle cleanup на `LiveBroker._accum`; очищать `_tool_names_by_id` на terminal turn; `backfill_logs` действительно читать batches.
6. Добавить дешёвую telemetry main PID: `PSS`, `SwapPss`, `_accum bytes/keys`, session count, RAG state/active backfills каждые 5–10 минут. Без этого недельный leak снова будет недоказуем.

### Привычки

- Не держать live backend у десятков давно законченных workers; archive/hibernate, а не просто оставлять DB status idle.
- Не запускать 3–4 Codex reviews одновременно до изоляции MCP: это почти 1.0–1.3 GiB temporary retained.
- Закрывать тяжёлые browser/Steam/Telegram процессы, если машина используется как 20+ agent host.

### Не решение

- Суммировать RSS.
- Уменьшать `swappiness` ниже 10 при retained state существенно больше RAM и измеренном swap churn.
- Периодически reboot вместо ограничения process cardinality.
- Выносить RAG в отдельный daemon ради «экономии»: это изолирует crash/peak, но не уменьшает machine footprint само по себе.

## Итог и confidence

- **CONFIRMED:** крупнейший измеренный управляемый класс — per-agent Serena/language-server trees (4.09 GiB в #112); локальные live CLI/MCP тоже удерживают гигабайты. Serena и локальные строки не являются одним атомарным snapshot.
- **CONFIRMED:** main PID держал 1.60 GiB retained baseline и делал обратимый transient peak до 2.40 GiB (lifetime RSS HWM 3.0 GiB). Связь burst с merge→RAG backfill сильная по времени, но allocation owner не измерен.
- **CONFIRMED:** persisted main session payload (1.86 MiB) и disk-backed log store сами не объясняют GiB; весь live backend heap этим не исключён.
- **CONFIRMED:** текущим 8–9 idle trees атрибутировано 3.3–3.5 GiB retained. Фактическое освобождение после hibernation не измерено.
- **CONFIRMED:** swap набрался после свежего boot и даёт measurable major faults/I/O stalls; reboot не устраняет обнаруженные источники cardinality, хотя повторный профиль не гарантирован.
- **LIKELY:** RAG/ONNX — dominant contributor к большим anonymous mappings main. Основание: 1.47 GiB в 17 large mappings + independent 0.946/2.4 GiB RAG benchmark + совпавший live peak; allocation-stack snapshot недоступен без restart/injection.
- **UNCERTAIN:** текущий объём unbounded Python collections. Пути роста доказаны кодом, но численный current payload не наблюдаем; приписывать им остаток памяти нельзя.

## Counter-evidence

- Desktop приложения сами удерживают 8.48 GiB cgroup footprint; утверждение «виновата только Orchestra» неверно.
- Composite process estimate 11.73 GiB смешивает Serena #112 с локальным snapshot; он не годится для точного вычитания из 15.41 GiB cgroup charge.
- Короткий main trace вернулся с 2.40 до 1.64 GiB; это аргумент против monotonic leak, но не доказательство отсутствия медленного недельного роста.
- `codex_review` действительно множит MCP; постоянные orphan reviews в snapshot не найдены, но current cleanup code не гарантирует верхнюю границу lifetime descendant, закрывшего stdout.

## Adversarial second opinion

Codex проверил арифметику, overlaps и причинность; полный результат — `docs/tasks/113/codex-review-research.md`. Blocking findings не было. Все девять замечаний приняты: итог помечен composite, idle/restart числа — ceilings, swap показан двумя проекциями, overlaps мер раскрыты, RAG понижен до LIKELY, гарантия cleanup снята, retained отделён от active working set. Нерешённое ограничение остаётся одно: raw PID lists одноразовых snapshots не были сохранены, поэтому точную классификацию задним числом независимо не воспроизвести.

## Проверяемость измерений

- Пересчёт единиц везде один: `GiB = KiB / 1_048_576`. Для PID: `retained = Pss + SwapPss`, `private = Private_Clean + Private_Dirty`, `shared proportional = max(Pss - private, 0)` из `/proc/<pid>/smaps_rollup`.
- Локальная таблица строилась по descendants PID 1543 с взаимоисключающим приоритетом классов: active review trees → agent CLI executables → `app/mcp_stdio.py` → прочие MCP → other descendants. Serena subtrees удалялись из локального итога и заменялись ровно одной внешней строкой #112.
- Review leaders сопоставлялись с active rows `bg_jobs`; idle roots — с `sessions.status` по прямым CLI children. Поэтому idle tree — другая, намеренно пересекающаяся проекция тех же процессов.
- Raw `/proc/1543/status` в snapshot: `VmHWM=3,134,112 KiB`, `VmRSS=1,104,408 KiB`, `VmSwap=591,104 KiB`, `Threads=38`. 10-second raw delta: system `pswpin=11,882 pages`, `pswpout=0`, `pgmajfault=9,728`; Orchestra `pswpin=11,610`, `pgmajfault=9,542`.
- Не сохранены: полный PID membership M1/M2/M8/M10 и raw byte values leaf cgroups M3. Поэтому totals имеют precision до показанных snapshots, но auditability ниже повторяемого profiler dump; это явно снижает confidence composite и hibernation gain.

## Источники и измерения

`[M1]`–`[M13]` — Tier 1 direct measurements этой машины в текущем boot; ограничения воспроизводимости перечислены выше. Код и Linux docs — Tier 2 primary sources.

1. Linux kernel `/proc` documentation — PSS/Swap/SwapPss semantics (Tier 2 primary): https://docs.kernel.org/6.9/filesystems/proc.html
2. Linux kernel cgroup v2 documentation — `memory.current`, `memory.stat`, `memory.swap.current` semantics (Tier 2 primary): https://docs.kernel.org/admin-guide/cgroup-v2.html
3. `docs/tasks/rag-orchestra/research.md:83-108, 220-224` — direct isolated benchmark на этой машине: 946 MiB idle, 1.6–2.4 GiB peak (Tier 1 measurement).
4. `docs/tasks/112/` / сообщение orchestrator 2026-08-01 — 20 Serena roots / 79 processes / 4.09 GiB `PSS+SwapPss`, включая 0.67 GiB четырёх temporary review instances (Tier 1 measurement другого воркера; artifact ещё не был виден в этой worktree во время исследования).
5. **[M1]** `/proc/*/smaps_rollup` + process-tree snapshot 2026-08-01 14:21:58; cgroup files `/sys/fs/cgroup/system.slice/orchestra.service/memory.*`.
6. **[M2]** executable-level MCP census по argv[0:3] и `PSS+SwapPss`, 14:23; descendants active review leaders исключены до regular-MCP subtotal.
7. **[M3]** leaf user cgroups: recursive `memory.current`, `memory.swap.current`, `memory.stat`, 14:17.
8. **[M4]** `systemctl show orchestra`, `ps -p 1543`, journal boot markers.
9. **[M5]** `/proc/1543/status`: `VmHWM`, `VmRSS`, `VmSwap`.
10. **[M6]** `/proc/1543/smaps`, aggregation of anonymous mappings by retained size.
11. **[M7]** read-only SQLite queries over `sessions`, `logs`, attached `vec.db`; source audit `app/db.py`, `app/session.py`.
12. **[M8]** direct-child CLI trees mapped to live DB status, snapshots 14:10 and 14:22.
13. **[M9]** read-only `bg_jobs` query + `app/mcp_stdio.py:903-1080`.
14. **[M10]** four active codex-review process-group trees, per-process `smaps_rollup`.
15. **[M11]** `sar -r -S` 10-minute samples since 10:52 boot.
16. **[M12]** `/proc/swaps`, `/sys/block/zram0/mm_stat`, `/proc/sys/vm/swappiness`, `findmnt /mnt/data`.
17. **[M13]** 10-second `/proc/vmstat` + cgroup `memory.stat` delta and `vmstat -w 1 10`.
