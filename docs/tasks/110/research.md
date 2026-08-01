# #110 — Ouroboros: проверка benchmark-заявки и точечные заимствования для Orchestra

Дата проверки: 2026-08-01. Исследованный upstream: `razzant/ouroboros` commit
`ca76d76ca2f645c25b528575869e2dff132a75ea` (v6.87.5). Это только Phase 1:
код Orchestra не менялся, реализация и планирование не начинались.

## Короткий вердикт

Опубликованные прогоны **не выдуманы**: публичные Harbor/Hugging Face артефакты
содержат сотни score-bearing trials и полные траектории, в том числе ошибки и
провалы. Код, benchmark-скрипты и MIT-лицензия также опубликованы [4][37]. Но заголовок
«SOTA на Terminal-Bench, OSWorld и CL-Bench» на дату проверки **не подтверждён ни
одним из трёх официальных лидербордов**: Terminal-Bench и CL-Bench submissions
остаются open, Ouroboros отсутствует на OSWorld-Verified workbook. Это не доказывает,
что результат неверен; это меняет статус с «независимо подтверждённый SOTA» на
«публичный авторский кандидат» [1][3][4][6][19][23].

Из четырёх сравнений Terminal-Bench только Grok имеет неперекрывающиеся
приблизительные 95%-интервалы и `p≈0.0024` **в sensitivity analysis**, где
опубликованные SE считаются независимыми normal errors. Однако там различаются reasoning effort (`medium` против
`high`) и процедура reward-hack-аудита; поэтому даже этот разрыв не изолирует
эффект harness. Три остальные разницы (`+3.17`, `+1.32`, `+1.20`) незначимы при
`α=.05`; мощность обнаружить именно наблюдённые эффекты — лишь 35%, 13% и 11%.

Архитектурно Ouroboros интересен, но это не «простой Python loop»: один
`loop.py` занимает 5.9k строк, а context/tool/LLM seams — ещё несколько тысяч.
Лучшее точечное заимствование — не рой и не полная память, а lifecycle скиллов:
канонический источник, content hash, provenance, atomic swap и rollback. Следом —
generation/watermark для свежести памяти и структурированные tool errors на MCP-границе.
семантической памяти. «Синтез патчей» не является автоматическим разрешением
конфликтов: это проверенный patch artifact + выбор/`git apply --3way` родителем;
Orchestra уже имеет более сильный branch/lock/merge/rollback-контур.

| Проверяемый тезис | Вердикт | Уверенность |
|---|---|---|
| Код/скрипты/трейсы реально опубликованы | **Подтверждено** | CONFIRMED — первичные артефакты и открытые реальные траектории |
| Результаты полностью воспроизводимы третьей стороной | **Пока нет** | UNCERTAIN — seed/manifests есть, но независимого полного повтора нет; часть settings не раскрыта публичной job config |
| Ouroboros — официальный SOTA на трёх досках | **Не подтверждено** | REFUTED для формулировки «официальный» на 2026-08-01; submissions open/absent |
| Harness доказанно лучше Codex CLI / Claude Code / Cursor | **Нет** | REFUTED как причинный вывод: модели/effort/audit различаются, 3/4 TB-разрывов в шуме |
| «Чистый Python» | **Да** | CONFIRMED — прямой аудит исходников; но loop крупный и многослойный |
| 500 агентов / depth 5 — доказанный рабочий масштаб | **Нет** | UNCERTAIN — это допустимая конфигурация/жёсткий cap, не опубликованный нагрузочный прогон |

## 1. Вопрос, гипотезы и критерий решения

**Контекст:** Orchestra уже управляет CLI-агентами в git worktree, использует
squash merge, persistent sessions, MCP, RAG-память и копируемые при spawn скиллы.

**Изменение под проверкой:** Ouroboros как альтернативный harness и его отдельные
механизмы: loop/context, patch integration, subagent fan-out, memory и skill hubs.

**Baseline:** официальные Terminal-Bench/OSWorld/CL-Bench записи и текущие
механизмы Orchestra, а не рекламные подписи на графике.

**Измеримый исход:** (1) provenance и независимая проверка benchmark-результатов;
(2) статистически различимый эффект при сопоставимой модели/config; (3) механизм,
который закрывает конкретную дыру Orchestra дешевле и безопаснее миграции.

Рассматривались три конкурирующие гипотезы:

1. **H1: Ouroboros действительно даёт воспроизводимый harness-effect.**
   Фальсификатор: отсутствуют score-bearing traces, сравниваются разные модели или
   сопоставимый model/config не даёт значимого разрыва.
2. **H2: headline в основном объясняется шумом, stale baselines и различиями
   методологии.** Фальсификатор: accepted independent submissions, matched configs,
   predeclared audit и значимые разрывы на нескольких досках.
3. **H3: отдельные механизмы полезны Orchestra без миграции.** Фальсификатор:
   механизм уже эквивалентно реализован либо требует новую архитектуру/стоимость,
   несоразмерную нашей нагрузке.

Итог: H1 не доказана; H2 хорошо объясняет headline, но не опровергает, что сам
harness конкурентоспособен; H3 подтверждается для 2–3 узких механизмов.

## 2. Часть 1 — проверка цифр

### 2.1 Terminal-Bench 2.1: интервалы и статистическая мощность

Terminal-Bench 2.1 содержит 89 задач; официальный протокол использует `k=5`, то
есть 445 trials [5][6]. График Ouroboros подписан как `±SE`, не как 95% CI [4].
Поэтому сначала проверены буквально нарисованные интервалы, затем построены
приблизительные 95%-интервалы `score ± 1.96·SE`.

| Сравнение | Δ, п.п. | Интервалы ±1 SE | Пересечение ±1 SE | Прибл. 95% интервалы | Пересечение 95% |
|---|---:|---|---|---|---|
| Opus 5: 86.97±1.6 vs Fable 5: 83.80±1.2 | +3.17 | `[85.37,88.57]` vs `[82.60,85.00]` | нет, gap 0.37 | `[83.83,90.11]` vs `[81.45,86.15]` | **да**, 2.32 п.п. |
| Opus 4.8: 80.22±1.0 vs Claude Code: 78.90±1.3 | +1.32 | `[79.22,81.22]` vs `[77.60,80.20]` | **да**, 0.98 | `[78.26,82.18]` vs `[76.35,81.45]` | **да**, 3.19 |
| GPT-5.5: 84.30±1.2 vs Codex: 83.10±1.1 | +1.20 | `[83.10,85.50]` vs `[82.00,84.20]` | **да**, 1.10 | `[81.95,86.65]` vs `[80.94,85.26]` | **да**, 3.31 |
| Grok 4.5: 84.94±1.1 vs Cursor: 79.30±1.5 | +5.64 | `[83.84,86.04]` vs `[77.80,80.80]` | нет, gap 3.04 | `[82.78,87.10]` vs `[76.36,82.24]` | **нет**, gap 0.54 |

То есть «усы не пересекаются» верно при ±1 SE только для 1-го и 4-го графиков.
При стандартной приблизительной 95%-интерпретации остаётся только Grok.

Поскольку SE в самом графике имеют смешанное происхождение, а matched covariance
недоступна, из публикации нельзя построить один корректный primary significance
test. Ниже — **sensitivity analysis**, буквально принимающий подписи графика за
независимые normal SE: `SEdiff = sqrt(SEouro² + SEbase²)`. Мощность для
наблюдённого эффекта post-hoc и почти является преобразованием `z/p`; она приведена
описательно по прямому запросу. Более полезная prospective величина — минимальный
разрыв (MDE), который этот дизайн обнаружил бы с мощностью 80% при `α=.05`.

| Сравнение | SEdiff, п.п. | z | p (2-sided) | 95% CI разницы, п.п. | Описательная post-hoc power | 80%-power MDE |
|---|---:|---:|---:|---|---:|---:|
| Opus 5 / Fable 5 | 2.000 | 1.585 | 0.1130 | `[-0.75,+7.09]` | **35.4%** | 5.60 п.п. |
| Opus 4.8 / Claude Code | 1.640 | 0.805 | 0.4209 | `[-1.89,+4.53]` | **12.7%** | 4.59 п.п. |
| GPT-5.5 / Codex | 1.628 | 0.737 | 0.4610 | `[-1.99,+4.39]` | **11.4%** | 4.56 п.п. |
| Grok 4.5 / Cursor | 1.860 | 3.032 | 0.0024 | `[+1.99,+9.29]` | **85.8%** | 5.21 п.п. |

При поправке Bonferroni на четыре headline-сравнения (`α=.0125`) **в этой
аппроксимации** формально остаётся только Grok; его мощность падает примерно до 70.3%. Но это сравнение не
чистое методологически (см. ниже).

#### Почему 89×5 — не 445 независимых задач

Официальная метрика считает общий success rate и специальный SE из пяти повторов
**внутри каждой фиксированной задачи**:

```text
accuracy = successes / total_trials
SE = 100 * sqrt((1/n_tasks²) * Σ[p_i(1-p_i)/(k_i-1)])
```

Это подтверждается кодом leaderboard [7]. Такая ошибка оценивает stochastic
run-to-run noise на фиксированном наборе 89 задач, но не uncertainty выбора самих
задач. Пять повторов уточняют `p_i`; они не превращают benchmark в выборку из 445
независимых problem types.

На публичном Opus-5 job измерено 387/445 успехов. Распределение по 89 задачам:
`66×5/5, 11×4/5, 3×3/5, 1×2/5, 2×1/5, 6×0/5`. По официальной формуле это
`86.9663% ± 0.9795 SE`, а не `±1.6` на графике. `1.596` получается из наивного
Bernoulli SE `sqrt(p(1-p)/445)`, словно все 445 trials независимы. При этом
task-level sample SE для среднего из 89 долей равен `3.000` п.п. Значит, в
публикации смешаны разные estimands uncertainty [4][7][9].

Если в качестве ещё одной sensitivity-проверки заменить только Ouroboros `1.6`
на официальный fixed-task `0.9795`, гибридное сравнение даёт
`z=2.046`, `p=0.0407`, CI разницы `[+0.13,+6.21]` и мощность 53.4%. Оно всё равно
не переживает поправку на четыре сравнения. Это **не исправленный primary test**:
у baseline остаётся SE другого/неполностью раскрытого происхождения. Для обобщения на новые классы задач
точный paired cluster test требует per-task результатов обоих harnesses; публичный
leaderboard submission baseline содержит trial IDs, но source jobs закрыты, поэтому
ковариация пар недоступна. **Точная «реальная» мощность для generalization не
идентифицируема из опубликованных данных.** Прозрачный независимый task-binomial
sanity check с `n=89` даёт лишь 9.2%, 5.5%, 5.5%, 16.6% мощности соответственно
(80% MDE ≈ 14.8–16.9 п.п.); paired design может быть лучше при положительной
корреляции, но эту корреляцию нельзя придумать после результата.

**Вывод:** для fixed-suite stochasticity пять прогонов полезны; для широкого
тезиса «лучший coding harness» 89 task clusters и отсутствие matched raw baseline
делают headline сильно underpowered.

### 2.2 Что именно сравнивали и кто гонял baseline

| Пара | Модель/config Ouroboros | Baseline и provenance | Сопоставимость |
|---|---|---|---|
| 86.97 vs 83.80 | **Claude Opus 5**, high по PR; один model slot, subagents/web/browser выключены, default Harbor resources/timeouts; 445 trials [8][9] | **Fable 5 + Claude Code**, xhigh; официальный Terminal-Bench team run, merged PR, default constraints [6] | **Не та же модель**. Сравнение систем, не harness-effect |
| 80.22 vs 78.90 | Ouroboros + **Opus 4.8**; public job даёт модель и default constraints, но не раскрывает settings-файл/effort [11] | Claude Code 2.1.205 + **Opus 4.8 high**, официальный team run, merged PR #92 [10] | Модель совпадает; effort Ouroboros независимо не подтверждён. Разрыв 1.32 в шуме |
| 84.30 vs 83.10 | Ouroboros + **GPT-5.5**; reasoning effort не виден в public job [13] | Codex 0.125 + **GPT-5.5 xhigh**, официальный team run; один reward hack zeroed [12] | Модель совпадает, effort не подтверждён. Разрыв 1.2 в шуме |
| 84.94 vs 79.30 | Ouroboros + **Grok 4.5 medium**, open PR #146 [15] | Cursor CLI + **Grok 4.5 high**, официальный team run; 40 reward-hacking successes zeroed [14] | Effort различается; audit асимметричен |
| 84.94 vs Hermes 77.53 | авторский Ouroboros run | Hermes run сделан самим автором статьи [3][4] | Не официальный baseline; недостаточно для независимого сравнения |

Baseline-цифры Claude Code/Codex/Cursor не были перепрогнаны автором: они взяты из
официальных submissions, которые запускала и проверяла команда Terminal-Bench.
Это плюс. Но «одинаковая модель у всех» неверно для Opus-5/Fable и Hermes; exact
effort не подтверждён для Ouroboros Opus-4.8/GPT-5.5; Grok — явно `medium` vs
`high`. Следовательно, ни одна из четырёх пар не является одновременно
model/config-matched, независимо adjudicated и статистически убедительной.

Есть ещё две численные несогласованности:

- public GPT-5.5 job содержит 374 scored successes, один `VerifierTimeout` и один
  `AgentTimeout`. Официальный zero-errors denominator даёт `374/445=84.0449%`;
  Harbor UI, исключая один unscored trial, даёт `374/444=84.2342%`. Ни одно число
  не равно опубликованным `84.30%` [4][13];
- Opus-5 graph показывает `±1.6`, тогда как официальный per-task formula и raw
  distribution дают `±0.98`; сам PR commit message также заявляет `±0.98` [7][8].

Это небольшие расхождения, не доказательство фальсификации, но они запрещают
считать график готовым audited leaderboard artifact.

### 2.3 Reward-hack audit

Cursor/Grok baseline официально снизили с 88.31% до 79.33%, независимо обнулив 40
подозрительных trials [14]. Ouroboros/Grok сначала сообщил 383/445 = 86.07%; judge
выделил 19 подозрительных случаев, после чего автор признал одну задачу ×5 и сам
пересчитал 378/445 = 84.94%. PR остаётся open и окончательного независимого verdict
нет [15]. Для Opus-5 автор также сам указал один reward-hack и просит его обнулить;
PR #175 пока не reviewed/merged [8].

Само раскрытие спорных trials — хороший сигнал прозрачности. Но сравнивать
независимо audited 40 zeros baseline с self-adjudicated 5 zeros candidate и затем
приписывать разницу harness нельзя до единой процедуры модерации.

### 2.4 Реальны ли прогоны и трейсы

Да. Проверены не только итоговые JSON:

- `polyglot-rust-c` success: ATIF v1.7, 8 шагов, 6 tool calls, реальные записи,
  компиляция и проверка, reward 1 [16];
- `configure-git-webserver` failure: 23 шага, 21 tool call, установка/config
  ssh/nginx, reward 0 [17];
- `db-wal-recovery` runtime error: prompt присутствует, финального ответа и
  траектории исполнения нет, job фиксирует runtime error [18].

Public Opus-5 Harbor job содержит 445/445 trials, один error, `$1428.96` reported
cost и 886,050,744 tokens [9]. Opus-4.8 содержит 445 trials, 0 errors, `$1074.28`
[11]; GPT-5.5 — 445, 2 errors, `$664.67` [13]. Это убедительное доказательство
реальных платных прогонов. Оно не заменяет независимую adjudication или matched
comparison.

### 2.5 Официальный статус Terminal-Bench

На 2026-08-01 официальный Terminal-Bench 2.1 leaderboard содержит 17 записей и не
содержит Ouroboros [6]. PR #175 (Opus 5) и #146 (Grok 4.5) открыты, без итогового
review/merge [8][15]. В #175 static-analysis step завершился, но workflow упал на
публикации комментария (`Either message or path required`); это не независимая
верификация результата.

Repo добавил benchmark evidence только в v6.87.4 от 2026-07-31, за день до этой
проверки [4]. Поэтому отсутствие на доске может быть обычным review lag. Корректная
формулировка сегодня: **public candidate score, official verification pending**.

### 2.6 OSWorld-Verified

Автор заявляет 90.69% = 327.39/361 на Opus 5, screenshot-only, один rollout,
100 steps, двумя batches 103+258 [22]. Hugging Face dataset содержит 361 result/task
outcome и полные task traces; это не пустая витрина [21]. Проверены два reward=1
trial и один reward=0 trial, где агент сам заявил успех, а evaluator поставил ноль.
Значит, score-bearing failures сохранены, а не вычищены.

Но официальный OSWorld-Verified workbook на дату проверки Ouroboros не содержит;
официальная страница пишет, что public submissions проходят evaluation/monitoring
команды [19][20]. Текущий top в workbook — 90.19% (325.59/361), то есть номинальная
разница лишь +0.50 п.п.

Наивная независимая биномиальная проверка одного rollout на 361 task даёт:

```text
SE(90.69%) = 1.529 п.п.
SE(90.19%) = 1.566 п.п.
SEdiff      = 2.189 п.п.
z           = 0.228
p           = 0.819
95% CI Δ    = [-3.79,+4.79] п.п.
```

Это заведомо грубая оценка без paired raw top baseline, но её достаточно, чтобы
показать: `+0.50` полностью внутри sampling noise. Формулировка «highest reported
author-run score» допустима; «доказанный OSWorld SOTA» — нет.

### 2.7 CL-Bench

Ouroboros PR #10 заявляет reward 0.2301 / gain 0.1985 по официальным metric
definitions [24] на Sonnet 4.6: шесть задач,
пять permuted rollouts плюс baseline, native file memory, subagents/evolution/web/
vision выключены [26]. Трейсы настоящие: например, `blind_spectrum_monitoring`
run-0 содержит 90 interactions, fresh conversation на каждый question, но
персистентную native memory; score 0.4168, baseline 0.21955, reported run cost
`$75.60` [27]. Полный campaign cost в PR — `$2486.47`, 315 isolated servers.

Однако PR открыт и без review. Автор отдельно раскрывает спор scoring convention
на `cohort_studies`: headline 0.2301 против 0.2325 при all-bits convention [26].
Текущий официальный leaderboard уже показывает ICL Sonnet 4.6 = 0.223 reward,
а не stale `previous top 0.1960` из README; номинальный разрыв сократился до
0.0071 [4][23]. Официальный default submission требует пять runs на задачу, но
leaderboard не публикует uncertainty для этого сравнения [25]. При всего шести
task families точную significance/power без per-task covariance заявить нельзя.

CL-Bench здесь доказывает способность пользоваться **явной персистентной файловой
памятью** между вопросами. Он не доказывает превосходство над semantic retrieval
Orchestra: это другой memory contract и гораздо больший test-time compute.

### 2.8 Итог проверки заявки

**Чему можно верить:** Ouroboros — реальный, активный MIT Python project; author-run
jobs и traces реальны; score 86.97 на fixed TB suite воспроизводится из 387/445;
архитектура содержит рабочие механизмы context fit, memory, subagents, patch
artifacts и skill lifecycle.

**Чему пока нельзя верить как установленному факту:** официальный SOTA на любой из
трёх досок; причинный вывод «harness обходит Codex/Claude Code/Cursor»; широкое
обобщение «лучший агент в research/computer-use/coding»; доказанный production
scale 500 agents/depth 5; полная reproducibility exact model settings.

## 3. Часть 2 — архитектура против Orchestra

### 3.1 Основной loop, контекст и tool errors

#### Ouroboros

`ouroboros/loop.py` — 5,917 строк; `context.py` — 1,520,
`loop_tool_execution.py` — 1,247, `loop_llm_call.py` — 1,015. Это pure Python, но
не минимальный loop. На каждом ходе он:

1. выбирает route/model и строит cache-stable context;
2. вызывает LLM с retry/fallback;
3. нормализует tool calls;
4. параллельно запускает read-only/enqueue операции (cap 8), мутации —
   последовательно;
5. сохраняет tool result/error в durable event stream;
6. проверяет cost/deadline/round budgets, checkpoints и compaction;
7. при отсутствии tools проходит final review/acceptance.

Context раскладывается на стабильное ядро (`SYSTEM`, `BIBLE`, identity/world/
knowledge) и volatile scratch/dialogue/tools/events/reviews. `ContextFitPlan`
детерминированно строит Max/Low projection под точное окно модели; low использует
navigation map вместо полного architecture payload. Overflow вызывает один
контролируемый low retry, а не молчаливое обрезание [28][31].

Provider errors классифицируются как auth/quota/context/transient, tool timeout/
exception/structured `ok=false` превращаются в видимый `is_error` result и
сохраняются с полным artifact, хотя prompt получает bounded preview [28]. Это
сильнее строки «failed» без code/retryability.

#### Orchestra

Orchestra уже разделяет current/aggregate/deferred/unknown context и запрещает
unknown-triggered compaction; Claude и Codex backends уже испускают `tool_result`
с `tool_use_id/is_error`, а session collector связывает их с tool name. Поэтому
глобальный перенос Max/Low loop — дублирование с риском сломать provider cache.

Реальная дыра находится на Orchestra MCP HTTP boundary:
[`app/mcp_stdio.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/mcp_stdio.py:76)
схлопывает status/body в `{"error": string}`, а wrappers возвращают обычную
строку вроде `Merge failed`. Для модели это часто успешный tool result без
`code/http_status/retryable/request_id`.

**Вывод:** не переносить loop; заимствовать единый typed error envelope и
fail-loud MCP `isError`. Небольшой кандидат отдельно — tiered provider-neutral
handoff (objective/decisions/next actions раньше последних 120 логов), но это ниже
приоритета.

### 3.2 «Синтез патчей»

Ouroboros создаёт self-worktree child от immutable `base_sha`. На завершении
`write_workspace_patch_artifacts` делает binary-capable `git diff`, добавляет
untracked файлы, исключает scratch/build/lock/sensitive/large payloads и пишет
manifest: base/current HEAD, SHA-256 patch, diffstat, files, errors. Если HEAD
сдвинулся относительно authority, artifact не строится [29].

Родитель:

- проверяет direct-child lineage, manifest SHA и protected-path grant;
- может только посмотреть bounded previews нескольких кандидатов через
  `compare_subagent_patches`;
- сам выбирает один patch и применяет `git apply --3way --index` под mutation lock;
- остаётся единственным committer; конфликт возвращается как ошибка, после чего
  модель должна разрешить его/abort [30].

То есть название «синтез» преувеличивает автоматизацию. `compare` не объединяет
семантически несколько патчей; `integrate` не решает конфликт. Оно обеспечивает
**immutable transport + provenance + parent authorization**, а синтез делает LLM.
Последовательное применение нескольких patches имеет те же содержательные
конфликты, что merge.

Orchestra уже сильнее в другой части: child commit является immutable artifact,
merge держит repo lock, проверяет чистоту child/target, делает `merge-tree`
preflight, squash commit и rollback. Заменять это raw patch transport невыгодно.
Чего нет: caller→child authorization и manifest со
`base/head/target/diff/touched_paths`, повторно проверяемый под тем же lock.

**Вывод:** не заменять squash merge. При необходимости добавить лёгкий
server-generated merge manifest и parent-only permission. Это снижает риск
разъехавшейся nested lineage, но само по себе не устраняет text conflicts.

### 3.3 Вложенность, 500 агентов, стоимость и зацикливание

Публичные defaults существенно скромнее анонса:

| Guard | Default | Hard/configurable bound |
|---|---:|---:|
| worker process pool | 10 | config |
| active subagents per root | 6 | hard cap 500 |
| nested depth | 2 | hard max 10 |
| capability depth for heavy/main | 1 | глубже — принудительно Light |
| model concurrency | 3 | config |
| default total budget | `$10` | task/global reservations |
| loop rounds | 200 | config |

Дополнительно есть reservation accounting, per-root/task/global cost fences,
queue caps, `may_delegate/may_mutate/may_fan_out`, `depth_remaining/max_children`,
semantic duplicate filter и deadline/budget wrap-up [28][31]. То есть стоимость
контролируется, а не полностью отпущена.

Но hard cap 500 — это не evidence реального прогона. Architecture doc прямо
признаёт, что около 500 children `wait_tasks` projection может упереться в 15k
truncation, а O(n²) active-tree scans приняты без performance work [28]. Публичных
load traces на 500 agents не найдено. Анонс говорит depth 5, тогда как current
default 2; до 5 надо сознательно поднять config [2][28].

Для Orchestra при нашей квоте и известном `$2230` research fan-out эти limits не
дают выигрыша: default 6/depth2 уже близок к практическому потолку, а 500 — новый
класс scheduler/observability/cost blast radius.

**Вывод:** не заимствовать scale/depth. Можно лишь сверить уже существующие
delegation budget/capability semantics; отдельной фичи ради этого не нужно.

### 3.4 Персистентная память и CL-Bench

Ouroboros хранит file-backed `identity`, `world`, `knowledge`, `patterns`,
`projects`, `dialogue` и scratchpad. `scratchpad_blocks.json` — до 10 append blocks
с atomic lock/FIFO eviction; из него строится `scratchpad.md`. После задач LLM
может консолидировать факты/улучшения. Существенная часть памяти **всегда
инъектируется** в context, а не извлекается RAG-запросом [28][32]. Project views
уменьшают leakage, но не устраняют context bloat/interference.

Orchestra хранит `CLAUDE.md`, docs/tasks, agent logs и semantic index, выбирая
релевантные chunks через `search_memory`. Для одного разработчика и нескольких
проектов retrieval дешевле полного постоянно растущего state. Ouroboros лучше в
двух свойствах: явная структура durable memory и немедленная доступность native
memory в следующем question. Orchestra лучше в bounded context и поиске по
истории.

У Orchestra обнаружена конкретная operational gap: после merge RAG backfill
стартует fire-and-forget, а `search_memory` параллельно читает старый RO index.
API не возвращает `indexed_head/generation`, поэтому агент не знает, устарел ли
ответ. Связанные места:
[`app/routes/sessions.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/routes/sessions.py:732),
[`app/rag_service.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/rag_service.py:79),
[`app/rag.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/rag.py:675),
[`app/routes/memory.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/routes/memory.py:30).

**Вывод:** не переносить full-injection memory. Заимствовать принцип
content-bound derived state: индекс должен отдавать generation/indexed target
HEAD и явно говорить `stale/indexing`, пока backfill не догнал merge.

### 3.5 Skill hubs, распространение и versioning

Ouroboros хранит канонические payloads вне worktree:
`data/skills/{native,clawhub,external,ouroboroshub}` плюс optional live
`OUROBOROS_SKILLS_REPO_PATH`. Self-worktree получает git checkout кода, но не
копию hub skills, поэтому Orchestra-style stale snapshot не возникает [33].

ClawHub lifecycle: resolve latest/explicit version → скачать ZIP → bounded
text-only validation (50 MB, 200 files, 8 MB/file, path/symlink/secret/binary
guards) → private stage → manifest adaptation → atomic directory swap →
provenance → review → isolated dependencies [34]. Update определяется при
browse/search простой строковой `latest_version != installed_version`; semver,
background polling и pin history нет. Registry не подписывает archive SHA:
локальный hash фиксирует полученные bytes, но TLS/registry остаются trust anchor.

OuroborosHub — mutable `main/catalog.json`, один version string без history/pin.
Каждый catalog-listed file проверяется SHA-256, записываются version/files/catalog
URL, затем atomic swap. Update rollback-ит старый payload, если review/deps сделали
новый non-executable [35]. Review/grants bound к полному `content_hash`: локальная
правка немедленно делает cached verdict stale [33]. Это сильный механизм, хотя
mutable catalog main + TLS остаются supply-chain authority.

Есть и собственная грабля Ouroboros: native launcher resync зависит от manifest
version, поэтому same-version byte change может оставить stale native copy;
удалённый seed теряет ownership marker, но payload остаётся [36]. Этот кусок
копировать нельзя.

В Orchestra Claude skills копируются только при spawn:
[`app/manager.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/manager.py:515) →
[`app/prompting.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/prompting.py:138).
Reconnect обновляет лишь `CLAUDE.md → AGENTS.md`; ownership manifest/hash/prune у
skills отсутствует. Codex, напротив, строит index по живым canonical paths при
backend construction, поэтому текущий stale-copy bug в основном Claude-specific.

**Вывод:** это наиболее прямое и выгодное заимствование: либо shared canonical
skills + references, либо content-hash sync на spawn/reconnect с ownership
manifest, atomic replace и rollback. Удалять можно только ранее Orchestra-owned
entries; project-owned `.claude/skills` трогать нельзя.

## 4. Часть 3 — что точечно заимствовать

Сортировка — `(ожидаемый выигрыш × уверенность) / (цена × риск)`. Оценки времени
и величины выигрыша — инженерные суждения, не измерения и не Phase 2 plan;
уверенность в benefit для первых трёх пунктов **medium**, потому что проблема в
текущем коде подтверждена, но эффект изменения ещё не измерялся.

### 1. Content-hash skill sync + ownership manifest — брать

**Механизм.** Канонический payload не считается свежим по имени/version. Manifest
хранит `skill name, source path/kind, source sha256, installed sha256/version`.
На spawn **и reconnect** вычисляется content hash; новая версия staging-ится,
валидируется и атомарно заменяет старую. Ошибка оставляет предыдущую рабочую
версию. Prune удаляет только manifest-owned orphan. Review/enable state, если он
появится, тоже bound к content hash.

**Куда ложится.** Изменения потребовались бы в
[`app/prompting.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/prompting.py:117),
[`app/manager.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/manager.py:515),
[`app/session.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/session.py:764),
[`app/workspace.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/workspace.py:262),
`tests/test_manager.py`, `tests/test_prompting.py`, `tests/test_session.py`.

**Цена / выигрыш.** 1–2 дня; ожидаемый выигрыш high, confidence medium: исправляет
уже известное протухание skills и делает происхождение bytes проверяемым.

**Риск.** Low–medium. Опасность — удалить tracked/project-owned skill или оставить
полукопию. Ownership manifest + path/symlink guards + atomic rename ограничивают
риск. Не копировать version-only native sync Ouroboros.

### 2. RAG freshness generation/watermark — брать узко

**Механизм.** Как Ouroboros привязывает review/grants к content hash, Orchestra
должна привязать поисковый snapshot к `indexed_head/generation`. `search_memory`
возвращает `fresh`, `stale: target_head=<sha>, indexed_head=<sha>` или `indexing`.
Merge не обязан синхронно ждать полный embedding; агент обязан видеть состояние.
Это адаптация принципа content-bound state, а не буквальный перенос Ouroboros RAG.

**Куда ложится.** `app/rag.py`, `app/rag_service.py`, `app/routes/memory.py`,
послемержевый trigger в `app/routes/sessions.py`; `tests/test_rag.py` и route tests.

**Цена / выигрыш.** 1–2 дня; ожидаемый выигрыш high, confidence medium, потому что
сейчас silent stale read неотличим от свежего. Это лучше полного Ouroboros memory
injection.

**Риск.** Low–medium: schema metadata/migration и races между несколькими backfill.
Fail-visible status безопаснее блокировки всех merges.

### 3. Typed MCP tool errors — брать

**Механизм.** Один envelope:
`{code,message,http_status,retryable,details,request_id}`, который FastMCP отдаёт
как `isError`, а logs сохраняют без потери machine-readable полей. Timeout,
non-JSON, 4xx/5xx и domain conflict различимы; retry разрешён только по полю, а
не по догадке модели.

**Куда ложится.** Центр —
[`app/mcp_stdio.py`](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-ouroboros/app/mcp_stdio.py:76)
и стабильные route envelopes; collector в `app/backend_claude.py`,
`app/backend_codex.py`, `app/session.py`, `app/db.py` уже есть и должен быть
переиспользован. Тесты: `tests/test_mcp_stdio.py` плюс существующие backend/session
error tests.

**Цена / выигрыш.** 2–4 дня; ожидаемый выигрыш high, confidence medium: это улучшит
детерминированный recovery, наблюдаемость и прекратит ложные «successful tool
result».

**Риск.** Medium: меняется контракт всех MCP wrappers. Нужен совместимый human
message и центральная миграция, не 30 ad-hoc parsers.

### 4. Merge manifest + parent-only authorization — брать только lightweight часть

**Механизм.** Под существующим repo lock сервер создаёт/проверяет
`{child_session_id,parent_name,repo_common_dir,base_sha,head_sha,target_sha,
diff_sha256,touched_paths}`; caller обязан быть `child.parent_name`, root exception
явно задан. Перед merge SHAs и touched paths сверяются ещё раз. Commit/branch
остаётся artifact; raw `workspace.patch` не вводится.

**Куда ложится.** `app/workspace.py`, `app/routes/sessions.py`, caller identity в
MCP/session path, `tests/test_workspace.py` и route auth tests.

**Цена / выигрыш.** 3–5 дней при уже доступной trustworthy session identity;
1–2 недели, если её придётся протащить через shared internal token. Ожидаемый
выигрыш medium (high только для nested DAG integrity), confidence low–medium:
частота caller/lineage incidents пока не измерена.

**Риск.** Medium–high: auth migration, rebases, binary/submodule diffs. Нельзя
сломать текущие clean-tree/merge-tree/rollback гарантии.

### 5. Tiered provider-neutral handoff — отложить

**Механизм.** При cross-runtime handoff сначала objective/decisions/open blockers/
next actions, затем bounded recency, вместо «последние 120 logs до 32k chars».

**Куда ложится.** `app/session.py` handoff builder и его tests.

**Цена / выигрыш / риск.** 2–3 дня, low–medium benefit, medium risk нарушить cache
continuity или потерять нестандартный контекст. Сначала нужны измерения текущих
failed handoffs.

### Что не брать

- **500 agents / depth 5.** Нет load evidence, defaults 6/depth2, upstream сам
  допускает truncation и O(n²). Для Orchestra это повторяет уже измеренный дорогой
  research fan-out.
- **Полную always-injected memory.** Увеличит context/cross-project interference;
  наш retrieval соответствует масштабу лучше.
- **Raw patch transport вместо git branches.** Не решает semantic conflicts и
  дублирует более сильный Orchestra merge transaction.
- **Полный Ouroboros loop/review/evolution stack.** Тысячи строк, второй способ
  исполнения и регрессионный риск без доказанного причинного benchmark-effect.
- **Marketplace UI, три-модельный review и executable extensions.** Для ~10
  пользователей supply-chain/runtime attack surface и стоимость выше выигрыша.

## 5. Коротко для seedon

Для SEO-платформы полезны те же три механизма, но приоритет немного другой:

1. **Structured external-tool errors** для CMS/GSC/Semrush/парсеров:
   `code/status/retryable/request_id` не дают агенту повторять permanent 4xx или
   считать частичную публикацию успехом.
2. **Client-scoped memory freshness watermark.** SEO-факты быстро стареют;
   `indexed_at/source/target_generation` важнее always-injected «вечной памяти».
   Добавить provenance/TTL для внешних метрик, не переносить Ouroboros memory dump.
3. **Hash/provenance/rollback для skills и шаблонов**, чтобы воркеры одного
   оркестратора не выполняли разные версии SEO workflow после обновления.

Parent-only patch manifest полезен лишь там, где несколько агентов параллельно
правят одну группу страниц/templates. Рой 500/depth5 и self-evolution для Seedon
не нужны: они масштабируют стоимость и риск массовой публикации быстрее, чем
качество.

## 6. Контрдоказательства, ограничения и риски интерпретации

- Репозиторий и benchmark evidence обновлены за день до проверки; официальные
  boards могут отставать. Поэтому «не accepted сейчас» не равно «будет rejected».
- Все полные candidate runs оплачивал/запускал автор. Public traces снижают риск
  выдуманных результатов, но не устраняют selection/config/adjudication bias.
- Для exact paired Terminal-Bench test нужны per-task outcomes candidate и official
  baseline после одинаковой reward-hack moderation. Candidate raw доступен,
  baseline source jobs закрыты; опубликованные aggregate SE не восстанавливают
  covariance.
- OSWorld и CL-Bench comparisons имеют по одному candidate campaign; leaderboard
  не даёт сопоставимых uncertainty/raw pairs.
- Architecture docs очень подробны, но быстро меняются. Load-bearing выводы выше
  сверялись по direct code paths, а не только по README/Habr.
- Оценки effort для Orchestra — engineering estimate; до Phase 2 они не являются
  обязательством или планом.

## 7. Затрагиваемые файлы Orchestra, если Phase 2 когда-либо одобрят

Исследование ничего из этого не меняло.

| Область | Потенциальные файлы | Главный риск |
|---|---|---|
| Skill sync | `app/prompting.py`, `app/manager.py`, `app/session.py`, `app/workspace.py`, skill tests | ownership/prune чужих skills, partial copy |
| MCP errors | `app/mcp_stdio.py`, route envelopes, `tests/test_mcp_stdio.py` | совместимость wrappers/clients |
| RAG watermark | `app/rag.py`, `app/rag_service.py`, `app/routes/memory.py`, `app/routes/sessions.py`, `tests/test_rag.py` | migration/race нескольких backfill |
| Merge manifest/auth | `app/workspace.py`, `app/routes/sessions.py`, session/MCP caller identity, workspace tests | nested lineage, shared-token auth, binaries/submodules |
| Handoff tiering | `app/session.py`, session tests | потеря cache/context при runtime switch |

## 8. Источники и уровень доказательства

1. [Telegram: авторский SOTA-анонс, 2026-07-31](https://t.me/abstractDL/432) — **tier 2, primary author claim**.
2. [Telegram: mini-app, hubs, 500/depth 5 и patch synthesis](https://t.me/abstractDL/433) — **tier 2, primary author claim**.
3. [Хабр: «Мой агент Ouroboros побил Codex…»](https://habr.com/ru/companies/airi/articles/1065428/) — **tier 2 для заявленной методологии, self-report**.
4. [Ouroboros README @ ca76d76](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/README.md#L72-L90) — **tier 2, code-adjacent self-report**.
5. [Terminal-Bench 2.1 release: 89 tasks](https://www.tbench.ai/news/terminal-bench-2-1) — **tier 2, official benchmark**.
6. [Official Terminal-Bench 2.1 leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.1) — **tier 2, official board**.
7. [Official TB metric implementation @ 5c8eadf](https://github.com/harbor-framework/terminal-bench-2-1/blob/5c8eadf1f393183288fa08b8f73ca9a469cc5e00/leaderboard/src/leaderboard/core/metrics.py#L29-L48) — **tier 2, primary code**.
8. [Ouroboros Opus-5 submission PR #175](https://github.com/harbor-framework/terminal-bench-2-1/pull/175) — **tier 2, primary submission; open**.
9. [Ouroboros Opus-5 public Harbor job](https://hub.harborframework.com/jobs/2b145543-edeb-4a3b-b46f-4800310f1182) — **tier 1-like direct published measurements, author-run**.
10. [Official Claude Code / Opus-4.8 PR #92](https://github.com/harbor-framework/terminal-bench-2-1/pull/92) — **tier 2, official reviewed submission**.
11. [Ouroboros Opus-4.8 public job](https://hub.harborframework.com/jobs/4b8e244f-8ab0-4d28-8218-7cf346282faa) — **tier 1-like direct published measurements, author-run**.
12. [Official Codex / GPT-5.5 PR #45](https://github.com/harbor-framework/terminal-bench-2-1/pull/45) — **tier 2, official reviewed submission**.
13. [Ouroboros GPT-5.5 public job](https://hub.harborframework.com/jobs/f02fd019-23e1-495f-af0a-ebd9a65f3079) — **tier 1-like direct published measurements, author-run**.
14. [Official Cursor / Grok-4.5 PR #86](https://github.com/harbor-framework/terminal-bench-2-1/pull/86) — **tier 2, official reviewed hack audit**.
15. [Ouroboros Grok-4.5 PR #146](https://github.com/harbor-framework/terminal-bench-2-1/pull/146) — **tier 2, primary submission; open**.
16. [TB success trajectory: polyglot-rust-c](https://hub.harborframework.com/jobs/2b145543-edeb-4a3b-b46f-4800310f1182/trials/0004f503-38ef-4d2f-9e8f-b93bf0ac1a2a) — **tier 1-like direct trace**.
17. [TB failure trajectory: configure-git-webserver](https://hub.harborframework.com/jobs/2b145543-edeb-4a3b-b46f-4800310f1182/trials/0d664c31-ae8f-4502-aaf5-a3a97f2b56c9) — **tier 1-like direct trace**.
18. [TB runtime-error trial: db-wal-recovery](https://hub.harborframework.com/jobs/2b145543-edeb-4a3b-b46f-4800310f1182/trials/94ab1330-4c61-4afc-a6d6-cbe71a3081de) — **tier 1-like direct trace**.
19. [Official OSWorld leaderboard / verification policy](http://osworld-v1.xlang.ai/) — **tier 2, official benchmark**.
20. [Official OSWorld-Verified results workbook](https://github.com/OS-World/OS-World.github.io/blob/main/static/data/osworld_verified_results.xlsx) — **tier 2, primary leaderboard data**.
21. [Ouroboros OSWorld-Verified traces](https://huggingface.co/datasets/razzant/ouroboros-osworld-verified-opus5) — **tier 1-like direct published dataset, author-run**.
22. [Ouroboros OSWorld methodology](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/devtools/benchmarks/osworld/METHODOLOGY.md) — **tier 2, primary methodology**.
23. [Official CL-Bench leaderboard](https://continual-learning-bench.com/) — **tier 2, official board**.
24. [CL-Bench metric definitions](https://continual-learning-bench.com/docs/metrics/) — **tier 2, official docs**.
25. [CL-Bench submission protocol](https://continual-learning-bench.com/docs/submitting/) — **tier 2, official docs**.
26. [Ouroboros CL-Bench submission PR #10](https://github.com/pgasawa/continual-learning-bench/pull/10) — **tier 2, primary submission; open**.
27. [Ouroboros CL-Bench full traces](https://huggingface.co/datasets/razzant/ouroboros-clbench-traces) — **tier 1-like direct published dataset, author-run**.
28. [Ouroboros architecture @ ca76d76](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/docs/ARCHITECTURE.md#L532-L612) — **tier 2, primary design/code map**.
29. [`write_workspace_patch_artifacts`](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/headless.py#L823-L1010) — **tier 2, primary code**.
30. [`integrate_subagent_patch` / compare](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/tools/subagent_integration.py#L490-L837) — **tier 2, primary code**.
31. [Context fit implementation](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/context_fit.py#L41-L120) — **tier 2, primary code**.
32. [Persistent scratchpad implementation](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/memory.py#L21-L210) — **tier 2, primary code**.
33. [Skill roots/discovery](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/skill_loader.py#L922-L1075) — **tier 2, primary code**.
34. [ClawHub staged install](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/marketplace/install.py#L362-L630) — **tier 2, primary code**.
35. [OuroborosHub hash-verified install](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/marketplace/ouroboroshub.py#L260-L317) — **tier 2, primary code**.
36. [Native skill bootstrap/resync](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/ouroboros/launcher_bootstrap.py#L700-L879) — **tier 2, primary code**.
37. [MIT license](https://github.com/razzant/ouroboros/blob/ca76d76ca2f645c25b528575869e2dff132a75ea/LICENSE) — **tier 2, primary legal artifact**.

## 9. Adversarial Codex review

Первый широкий review истёк через 10 минут без verdict: reviewer нарушил bounded
scope, ушёл читать RAG-код и делать web search. Этот раунд не считается
одобрением. Повторный review получил самодостаточный bounded input, запрет на tools
и лимит 1,200 слов. Артефакты:
[`codex-review-input.md`](./codex-review-input.md) и
[`codex-review-research.md`](./codex-review-research.md).

Codex выдал **APPROVE WITH SUGGESTIONS**, без BLOCKING/HIGH, и подтвердил
арифметику/центральный verdict. Два MEDIUM замечания исправлены:

1. Graph-SE test и замена одного Opus-5 SE теперь явно названы sensitivity/hybrid
   analyses, а не primary inference; observed-effect power помечена post-hoc,
   prospective MDE выделена как полезная величина.
2. Ranking приведён к заявленному benefit/cost: RAG watermark поднят выше более
   дорогой typed-error migration; magnitude выигрыша отделена от confidence.

LOW-вопрос о том, считать ли RAG freshness «заимствованием», разрешён явно: это
адаптация Ouroboros content-bound derived-state, не заявление, что у Ouroboros
есть такой RAG механизм. Dissent сохранён в review-файле.

## 10. Confidence summary

- **CONFIRMED:** artifacts/traces exist; raw Opus-5 387/445; official-board absence
  on the stated date; loop/patch/skill mechanisms in code; skill-copy gap in Orchestra.
- **LIKELY:** Ouroboros is a competitive harness, because three heterogeneous
  author-run campaigns score near current leaders and preserve failures. Это не
  равно causal superiority.
- **UNCERTAIN:** exact reproducibility of hidden settings; matched statistical
  effect; 500-agent operating scale; future acceptance of open submissions.
- **REFUTED:** текущая формулировка «официальный SOTA на трёх досках» и вывод
  «доказанно обходит Codex/Claude Code/Cursor именно за счёт harness».
