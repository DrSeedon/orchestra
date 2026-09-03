# #170 — forensic-аудит latency `feat-groom-demo`

Срез: `2026-08-09T07:31:21Z`–`13:54:49Z`; финальный analyzer run —
`2026-08-09T14:39:35Z` (environment snapshot — `14:16:50Z`). Исследовался authoritative worker
`feat-groom-demo`, а не отсутствующее имя `feat-bot-demo`. Seedon, его
worktree, сессия, БД и runtime не изменялись.

## Вопрос

- **Контекст:** Codex worker Seedon выполнял #101 в Orchestra на
  `gpt-5.6-sol`, `xhigh`, с несколькими phase gates, Codex reviews и поздними
  расширениями scope.
- **Изменение под проверкой:** последние изменения Codex/Orchestra могли
  внести delivery/MCP/compaction/quota regression.
- **Baseline:** тот же тип операции до изменения (а не другая задача) и
  исправный путь внутри этой же сессии.
- **Решающий результат:** wall-time каждого turn и доли queue/TTFT/tool/MCP/
  subprocess/context; отсутствие потерянных turns; matched outcomes до/после.

## Гипотезы и falsifiers

1. **H1:** Orchestra delivery или MCP стал главным источником задержки.
   **Опровергается**, если очередь и MCP быстры, а длительность следует за
   model output/workload.
2. **H2:** основное время — нормальная работа `xhigh` Sol над большим и
   меняющимся scope. **Опровергается**, если в длинных turns преобладают
   Orchestra/tool waits, повторы или потерянный lifecycle.
3. **H3:** исправленный compact lifecycle снова теряет/задерживает turns.
   **Опровергается**, если каждый native compact продолжается в том же turn,
   terminal events относятся к верному turn и второй message не нужен.
4. **H4:** quota/readiness или bwrap блокируют полезную работу. **Опровергается
   частично:** реальная модель завершает все turns, но `codex_review` ломается
   на отдельном hot-version-skew; standalone bwrap даёт один воспроизводимый
   отказ.

## Источник истины и способ измерения

Сессия найдена по `(scope, name)` в read-only SQLite и подтверждена rollout:

- session id `313c5206-05fe-4a02-b9ba-0928eed88a98`;
- scope `/home/kesha/projects/seedon`;
- cwd до архивирования
  `/home/kesha/orchestra/worktrees/home-kesha-projects-seedon/feat-groom-demo`;
- branch `adhoc-1786266809-4/feat-groom-demo`;
- Codex CLI `0.146.0`, context window `258,400`, system prompt `39,607`
  символов [1][12].

Скрипт [13] читает SQLite через URI `mode=ro` и rollout JSONL, соединяет
Codex `task_started/task_complete`, DB lifecycle, MCP begin/end, tool calls,
background jobs и user-message delivery. Он не сохраняет prompts, команды,
аргументы, результаты или credentials. Команды воспроизведения и определения
метрик — в [14]. Percentile p95 — nearest-rank; TTFT берётся из
`task_complete.time_to_first_token_ms`. Все времена ниже UTC.

## Итог

**Общего latency regression у turn delivery, MCP или compact нет.** Из 6 ч
23 мин end-to-end active turns занимают 5 ч 12 мин (81.4%). Семь turns
дольше 10 минут дают 87.45% всего active wall и 347,938 output tokens.
Корреляция `duration ↔ output_tokens` равна `0.944`; TTFT p50/p95/max —
`5.86/23.23/52.15 с`, а effective tool wait — только `971.51 с` (`5.19%`)
active wall. Это подтверждает H2: длительность в основном соответствует
реальному `xhigh` workload, генерации/рассуждению и расширению scope, а не
застрявшей доставке [1][2]. Residual `94.81%` нельзя строго назвать одним
provider compute: туда также входят model-side planning и внутренний web
search.

**Один отдельный shared-runtime regression доказан:** после merge `8369737`
новый per-call MCP client требует readiness policy `worker-weekly-v1`, а
старый FastAPI process, не перезапущенный с 7 августа, отвечает legacy JSON
без `policy`. До cutover `codex_review` стартовал `14/14`, после — заблокирован
`5/5` у трёх workers; у `feat-groom-demo` — трижды. Модель при этом была
доступна и все 26 её turns завершились `ok`; это contract/version skew, а не
исчерпание квоты [9][10][12].

## Полный timeline turns

`queue` — от записи нового сообщения до DB `turn_start`; `tool` — union
интервалов tools с продолжением yielded commands через соответствующий wait;
`steer` — сообщения, доставленные уже в active turn. Каждая строка закончилась
`end_turn`; `wait` означает `waiting_for_bg`, `idle` — настоящий gate/finish.
Полные ids, input/cache/cost/quota и timestamps находятся в [2].

| # | Start | Phase | Wall | TTFT | Output | Tools / tool wall | Queue | Steer | End |
|---:|:---:|---|---:|---:|---:|---:|---:|---:|:---:|
| 1 | 07:31:22 | research + review submit; compact 128.5 s | 1433.3 s | 11.5 s | 38,147 | 74 / 66.8 s | 1696 ms cold | 0 | wait |
| 2 | 07:56:29 | failed review path, fallback retry | 30.8 s | 7.3 s | 1,302 | 2 / 0.9 s | 68 ms | 0 | wait |
| 3 | 07:58:22 | research review fix R2 | 408.6 s | 1.7 s | 14,320 | 22 / 4.0 s | 63 ms | 0 | wait |
| 4 | 08:06:02 | research review fix R3 | 489.0 s | 7.1 s | 5,752 | 15 / 2.3 s | 84 ms | 0 | wait |
| 5 | 08:15:05 | research review fix R4 | 75.5 s | 5.0 s | 2,315 | 6 / 1.2 s | 55 ms | 0 | wait |
| 6 | 08:16:39 | research PASS + gate | 75.8 s | 3.3 s | 2,415 | 6 / 9.3 s | 39 ms | 0 | idle |
| 7 | 08:19:25 | plan build + review R1 | 1175.4 s | 10.4 s | 35,197 | 18 / 19.0 s | 94 ms | 0 | wait |
| 8 | 08:39:57 | plan fix R2; compact 48.6 s | 235.7 s | 4.0 s | 6,567 | 17 / 8.0 s | 50 ms | 0 | wait |
| 9 | 08:44:10 | plan fix R3 | 72.9 s | 2.2 s | 2,802 | 5 / 6.5 s | 42 ms | 0 | wait |
| 10 | 08:45:38 | plan PASS + gate | 71.3 s | 4.9 s | 2,706 | 6 / 1.0 s | 36 ms | 0 | idle |
| 11 | 09:13:30 | expanded plan/delta D1 | 2284.5 s | 52.1 s | 53,083 | 61 / 22.3 s | 94 ms | 1 | wait |
| 12 | 09:52:22 | plan delta fix D2 | 137.1 s | 5.7 s | 4,537 | 7 / 1.5 s | 47 ms | 0 | wait |
| 13 | 09:55:13 | plan delta fix D3 | 90.8 s | 23.2 s | 2,778 | 3 / 1.1 s | 50 ms | 0 | wait |
| 14 | 09:57:12 | plan delta fix D4 | 66.1 s | 13.3 s | 2,334 | 3 / 0.9 s | 44 ms | 0 | wait |
| 15 | 09:58:48 | plan delta fix D5 | 92.0 s | 21.5 s | 3,326 | 6 / 1.5 s | 32 ms | 0 | wait |
| 16 | 10:00:54 | plan delta fix D6 | 47.6 s | 4.1 s | 1,681 | 4 / 0.8 s | 38 ms | 0 | wait |
| 17 | 10:01:58 | plan delta fix D7 | 31.4 s | 4.8 s | 972 | 2 / 0.5 s | 74 ms | 0 | wait |
| 18 | 10:02:42 | delta PASS → Phase 3 build/R1; compact 38.0 s | 3009.5 s | 5.9 s | 85,666 | 72 / 113.3 s | 59 ms | 3 | wait |
| 19 | 10:54:09 | impl review retry + R2 submit | 28.1 s | 11.2 s | 885 | 1 / 0.3 s | 48 ms | 0 | wait |
| 20 | 11:02:44 | status during review | 40.0 s | 7.5 s | 1,143 | 3 / 0.5 s | 40 ms | 0 | wait |
| 21 | 11:03:34 | credential instruction during review | 7.5 s | 5.9 s | 212 | 0 / 0 s | 39 ms | 0 | wait |
| 22 | 11:07:19 | dashboard scope expansion | 113.9 s | 18.4 s | 4,011 | 6 / 1.1 s | 49 ms | 0 | wait |
| 23 | 11:09:48 | R2 fixes, subagents, tests, R3; compacts 81.7 + 105.2 s | 5207.2 s | 4.6 s | 107,845 | 194 / 461.4 s | 69 ms | 1 | wait |
| 24 | 12:52:12 | R3 fixes/tests/R4 + late freeze | 2636.8 s | 5.2 s | 20,143 | 35 / 82.0 s | 86 ms | 2 | wait |
| 25 | 13:39:15 | R4 fix + R5 | 237.4 s | 3.5 s | 3,265 | 13 / 84.6 s | 74 ms | 0 | wait |
| 26 | 13:44:10 | R5 PASS + deployment preparation | 638.7 s | 12.9 s | 7,857 | 17 / 80.9 s | 51 ms | 1 | idle |

В turn 11 TTFT 52.1 s — единственный большой model-start outlier, но сам
turn продолжался 38 минут и произвёл 53k output tokens; он не объясняет общую
длительность. В turns 18, 23, 24 in-flight сообщения расширяли или замораживали
scope. Orchestra записал `message_steered` и HTTP success в ту же секунду;
`7.3–295.6 с` до следующего model event — latency внимания занятой модели, а
не транспортная очередь [6][7].

## Разложение latency

| Компонент | n | p50 | p95 | max | Сумма / доля | Вывод |
|---|---:|---:|---:|---:|---:|---|
| Turn wall | 26 | 102.92 s | 3009.47 s | 5207.22 s | 18,736.80 s | workload сильно неоднороден |
| Model TTFT | 26 | 5.86 s | 23.23 s | 52.15 s | 257.22 s | не основной источник |
| Effective tool union | 598 calls | — | — | — | 971.51 s / 5.19% active | shell/browser/MCP вместе вторичны |
| Residual model/workload | 26 | — | — | — | 17,765.30 s / 94.81% active | reasoning/generation + native activity |
| MCP transport | 42 | 0.222 s | 0.977 s | 1.942 s | 14.30 s | не bottleneck |
| New bg wake → start | 20 | 50 ms | 84 ms | 86 ms | 1.11 s | исправный resume |
| New orchestrator msg → start | 6 | 72 ms | 1696 ms | 1696 ms | 2.01 s | max — initial cold start; warmed max 94 ms |
| Native compact | 5 | 81.67 s | 128.51 s | 128.51 s | 401.91 s / 2.15% active | дорого, но корректно и ожидаемо при context pressure |
| Standalone reviews | 20 complete | 54.50 s | 918.95 s | 1012.15 s | 2917.47 s | 48.6 мин subprocess wall; не всё является overhead |

От первого start до последнего end прошло `23,006.46 с`. Active turns —
`18,736.80 с`; completed reviews — `2,917.47 с`, из них `338.74 с`
пересекались с active turns, а `2,578.73 с` (43.0 мин) лежали между turns.
Остаток inactive wall — human approvals/messages и короткие orchestration gaps.
Нельзя приписывать все 48.6 минут regression: независимый review всё равно
делает model work; доказана поломка штатного маршрута, а не counterfactual
экономия всей длительности [2][5].

Raw tool-duration categories (они не аддитивны после union): tests `366.60 с`,
wait/resume `193.77 с`, read/search/git `82.49 с`, browser `43.95 с`, file
changes `37.69 с`, explicit test polls `31.06 с`, shell-other `29.23 с`, MCP
wrapper `24.65 с`, network `1.26 с` [1][3]. Ни shell, ни сеть не дают
многоминутный скрытый stall.

| Tool class | n | p50 | p95 | max | sum |
|---|---:|---:|---:|---:|---:|
| tests | 48 | 10.823 s | 11.094 s | 11.099 s | 366.598 s |
| wait/resume | 25 | 7.507 s | 16.668 s | 17.017 s | 193.767 s |
| read/search/git | 189 | 0.176 s | 0.477 s | 10.246 s | 82.485 s |
| browser | 15 | 1.408 s | 7.224 s | 7.224 s | 43.949 s |
| test poll | 11 | 0.219 s | 11.100 s | 11.100 s | 31.055 s |
| shell-other | 28 | 0.276 s | 4.617 s | 4.705 s | 29.231 s |
| network | 3 | 0.318 s | 0.688 s | 0.688 s | 1.260 s |

## Доказанные проблемы и неэффективности

### B1 — BLOCKING: hot-version-skew сломал `codex_review`

**CONFIRMED — tier 1 direct matched measurement + tier 2 source.**

- FastAPI process стартовал `2026-08-07 14:13:27 CEST`, до merge `8369737`
  (`2026-08-08 14:54:46 CEST`). Его live `/api/usage/readiness` отвечает
  `{provider, state, reason, reset_at}` без `policy` [12].
- Per-call MCP subprocess читает текущий `app/mcp_stdio.py:567` и fail-closed
  требует `policy == "worker-weekly-v1"`; новый route возвращал бы policy в
  `app/routes/system.py:1206` [10].
- Результат на одной операции: до cutover `14/14 job_started`; после cutover
  `5/5 blocked_legacy_readiness`, у target worker в `07:54:31`, `08:38:42`,
  `10:51:42` [9]. Exact tool error:
  `weekly_quota_unknown: New Codex worker turn blocked: weekly quota status for gpt-5.6-sol is unavailable or stale (missing or legacy readiness policy).`
- Это не настоящий quota denial: live legacy route говорит `available`, Codex
  quota в успешных turns вырос `4%→33%`, все 26 turns `ok/end_turn`, provider
  retry/error отсутствует [1][2][12].

Impact: обязательный cross-review route не работает минимум у трёх workers.
Target worker перешёл на 21 fresh `codex exec` background job. Это позволило
закончить работу, но убрало persistent review session и внесло один лишний
invalid-option запуск и один sandbox failure. Величину дополнительной model
работы без A/B измерить нельзя.

### S1 — повторные fresh reviews и отсутствующий skill contract

**CONFIRMED факт; LIKELY причинная связь — direct measurements, но нет A/B.**

Target создал `21` standalone review jobs, все как fresh sessions, ни одного
`codex exec resume`: research 5, plan 3, plan-delta 7, implementation 6.
Завершились 20, один упал exit 2 [5]. Артефакты прошли много содержательных
blocking rounds, поэтому считать все раунды пустым loop нельзя. Но семь
plan-delta reviews и пять implementation reviews превышают ожидаемый
трёхраундовый debate budget и каждый раз заново создают context.

Worker не получил тело `codex-debate`: в Seedon worktree `.codex` оказался
tracked empty file, а injector записал `exists and is not a directory — skill
injection skipped`. `AGENTS.md` имел `155,284` bytes при
`project_doc_max_bytes=65,536`; полученный project-instruction payload был
`68,043` bytes [12]. Поэтому поздние project rules и трёхраундовый skill
contract могли быть недоступны. Это вероятное объяснение, не доказанный
counterfactual.

### S2 — oversized/repeated retrieval увеличил context pressure

**CONFIRMED — tier 1 direct measurement.**

DB logs: `1,381` rows / `3.71 MB`; tool results `2.34 MB`. `39` results ≥16 KiB
дали `1.295 MB` (55.3% всех result bytes), `14` были ≥32 KiB, два ≥64 KiB;
max `87,948` bytes [1][8]. Выполнено `193` read actions по 67 paths: plan
читался 27 раз, HTML 20, `client.py` 20, `handlers.py` 18, `CLAUDE.md` 8 [8].
Часть повторов оправдана правками/reviews, но первоначальное чтение CLAUDE
вернуло 87.9 KiB и затем повторялось перекрывающимися кусками; один self-log
result был 61.5 KiB. Это не отдельный stall, но ускорило пять compactions и
увеличило cached-input work.

Сессия накопила `92.52M` input tokens, из них `90.35M` cache reads (97.65%), и
`411,261` output tokens; после последнего turn оставалось 213,661/258,400
context tokens (82%) [1]. Cache hit смягчил стоимость, но не устранил
compaction/model processing.

### S3 — bounded polling после потерянного nested exec handle

**CONFIRMED, низкий вклад.**

Было 25 `functions.wait` resumes — обычно один на yielded command, без
долгого sleep. Но 11 отдельных test-poll commands использовали
`pgrep`/`kill -0`/`sleep 1`: outer cell иногда завершался с пустым output и
`exit_code=undefined`, пока pytest child ещё жил. Прямой poll wall — `31.06 с`
[3]. Это реальный tool-call churn и нарушение injected `Never poll`, но не
объяснение часов работы; сами test calls дали `366.60 с`.

### S4 — один standalone bwrap failure; startup fallback исправен

**CONFIRMED — tier 1 direct event measurement.**

При старте app-server один раз сообщил, что system bubblewrap отсутствует и
будет bundled fallback, затем один `codex mcp orchestra: cancelled`. После
этого прошло 42 MCP calls без transport errors, поэтому этот startup incident
не создал latency loop [4][7][12].

Отдельный standalone implementation review длился `80.89 с` и при попытке
read-only sandbox вернул
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`; следующий
review был запущен с bypass sandbox [5][12]. Это доказанный разовый failure,
не проблема основного worker app-server. Внутри тех 80.89 с review успел дать
и содержательный verdict, поэтому чистый потерянный wall строго меньше этой
верхней границы и отдельно не измерим.

### S5 — runtime-неверная quota строка в turn-end logs

**CONFIRMED кодом и расходящимся измерением; latency impact не доказан.**

`app/session_turns.py:68-110` `_format_limits()` всегда читает глобальный
Anthropic-style `_usage_cache`, а caller не передаёт runtime. Поэтому Codex
turn-end показывал `5h/7d` вплоть до `7d:100%`, хотя native Codex quota в тех
же turns была `4%→33%` и все запросы проходили [2][10]. Это misleading
telemetry и риск ложной диагностики, но stale gate не задержал саму модель.

### S6 — unmanaged native subagents доступны worker

**CONFIRMED факт; REFUTED как причина текущей медлительности.**

После прямого разрешения пользователя на параллельных workers в 11:23 target
создал четыре native Codex subagents; DB содержит 5 `subagent_progress`
events [8]. `app/backend_codex.py:351-352` выключает
`features.multi_agent=false` только для orchestrator, не managed worker [10].
Это расходится с platform contract про tracked Orchestra workers и делает
исполнителей невидимыми Orchestra. Но они были user-authorized и работали
параллельно; данных, что они замедлили turn, нет.

## Проверки, которые НЕ нашли regression

### Delivery/MCP/retry

**CONFIRMED исправно.** Background completion запускал новый turn за
50/84/86 ms p50/p95/max. После первого cold start остальные orchestrator
messages стартовали максимум за 94.5 ms. MCP p50/p95/max —
0.222/0.977/1.942 s, total 14.30 s; ошибок транспорта нет [1][4][6]. Все 26
turns имеют ровно один `task_complete`, `ok=1`, `stop_reason=end_turn`; provider
retry/usage-limit events в rollout и OOM/kill events в journal за интервал нет
[1][2][7][12].

### Compact before/after #97

**CONFIRMED fix работает на этой сессии.** До `060c19a` исследование #97
нашло восемь native-compact incidents: false terminal через 2–56 ms, семь
выдали работу лишь после следующего message через 474–990 s, один оставался
stuck [11]. В target после fix прошло пять native compactions:

`245174→41935`, `226180→44332`, `212226→51519`, `218385→55527`,
`230949→56257` input tokens [7]. Все пять продолжили тот же turn, ни один из
26 turns не имел `$0`/stale compact terminal, replay или second-message wake.
Compaction стоил 401.91 s, но это нормальная цена context pressure, не
возврат #97.

### Background resume / precompact

20 background completions породили новый turn максимум через 86 ms [6]. Было
20 precompact schedules и 19 cancellations при новой активности; это
lifecycle logging churn, не sleep. Последний schedule остался после финального
turn до архивирования [7]. Потерянных resumes и незавершённых turns нет.

## Counter-evidence и ограничения

- Задача менялась между research, двумя версиями plan, implementation,
  dashboard и deploy preparation. Поэтому сравнивать wall-time этих phases
  между собой или с другим worker как regression некорректно. Сильный вывод
  сделан только на одинаковых операциях `codex_review` и native compact.
- `94.81% residual` — верхняя граница model/workload, не packet-level provider
  timing. В rollout нет server-side decomposition reasoning versus generation.
- 48.6 мин standalone reviews — реально измеренный subprocess wall, но не
  полностью устранимый overhead: cross-review был требованием и находил
  substantive issues.
- Поздний user scope freeze попадал в уже active turn. Промежуток до следующего
  model event не доказывает очередь Orchestra, поскольку delivery/steering был
  записан сразу.
- Current load snapshot не доказывает отсутствие кратких исторических CPU/I/O
  spikes; зато rollout/DB не содержат OOM, crash или retry signatures.

## Риск и возможные affected files для Phase 2

Phase 1 ничего не меняет. Если план будет утверждён, приоритеты такие:

1. **Совместимость shared runtime (blocking):** `app/mcp_stdio.py` +
   `app/routes/system.py`; контракт readiness должен быть atomic либо явно
   backward-compatible при hot-loaded MCP. Риск высокий: queue/quota gate общий
   для всех workers, fail-open недопустим.
2. **Runtime-specific telemetry:** `app/session_turns.py`; Codex не должен
   отображать Anthropic quota. Риск средний, поведение turns не менять.
3. **Managed-worker tool isolation:** `app/backend_codex.py`; определить один
   разрешённый путь delegation и закрыть invisible native agents. Риск средний:
   нельзя сломать user-authorized parallelism.
4. **Skill/worktree guard:** `app/prompting.py` и Seedon tracked `.codex` path;
   fail loud до task execution либо корректная non-overwrite стратегия. Риск
   средний: нельзя писать поверх tracked project files.
5. **Output/context hygiene:** точечные изменения prompts/tool wrappers только
   после отдельного A/B; compact path сейчас исправен, трогать его по #170 не
   нужно.

## Источники

Все локальные источники были открыты в этой сессии.

1. [Tier 1 — aggregate](measurements/aggregate.json).
2. [Tier 1 — all turns](measurements/turns.csv).
3. [Tier 1 — tool calls](measurements/tool_calls.csv).
4. [Tier 1 — MCP calls](measurements/mcp_calls.csv).
5. [Tier 1 — background reviews](measurements/background_jobs.csv).
6. [Tier 1 — message delivery](measurements/messages.csv).
7. [Tier 1 — lifecycle and compactions](measurements/context_events.csv) and
   [compact token deltas](measurements/compactions.csv).
8. [Tier 1 — payload/read evidence](measurements/payload_sizes.csv),
   [heavy results](measurements/heavy_results.csv),
   [read counts](measurements/read_counts.csv), and
   [tool errors](measurements/tool_errors.csv).
9. [Tier 1 — matched review cutover](measurements/codex_review_cutover.csv).
10. Tier 2 — current source:
    `app/mcp_stdio.py:541-568`, `app/routes/system.py:1197-1206`,
    `app/backend_codex.py:339-352`, `app/session_turns.py:68-110,394`.
11. Tier 1 prior measurement + tier 2 source reconstruction:
    `docs/tasks/97/research.md:129-141,168-179,217-242`; fix commit
    `060c19a307f187f2bd9a5f8585b81774489360de`.
12. [Tier 1 — environment/version snapshot](measurements/environment.json).
13. [Analyzer](measurements/analyze_session.py).
14. [Reproduction and redaction notes](measurements/README.md).
