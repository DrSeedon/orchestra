# #454 — единый конвейер «сырьё → знание»

**Главный результат: 134 из 141 (95.0%) исторических `done`-задач с непустой matching
`.orchestra/tasks/<par>/` не имеют ни одной KB-строки с `` `fact:` ``, связанной exact task path
либо `#<par>`; знаменатель содержит только `tm_tasks.project_id='orchestra' AND status='done'` с
matching source directory, `.orchestra/tasks/454/` исключена как артефакт текущего замера [15].**

Дата среза: 2026-09-03. Реализация и Phase 2 не выполнялись.

## Question

**Контекст.** В одном project-local репозитории есть три входа: lifecycle-артефакты задачи и
воркера; произвольный Markdown-корпус, который оркестратор разбирает по требованию; диалог/compact,
из которого рождаются правила. У первых двух knowledge sink — `.orchestra/kb/`, у третьего —
правила и prompt owners.

**Change under test.** Проверить выбранную пользователем форму: на `task closed`, `worker killed`
и `compact completed` фоном стартует отдельный дешёвый Luna extractor; layout KB уже выбран как
тематические Markdown-паки. Нужно измерить prompt, storage predicate и fan-out для project-wide
skill, а не выбирать другого исполнителя.

**Baseline.** Task/worker-артефакты и SQLite-логи сохраняются бессрочно; task completion,
`kill_worker` и compact не требуют knowledge/rule receipt; перенос выполняется вручную и
выборочно.

**Измеримый outcome.** Исследование пригодно для архитектурного выбора, если оно:

1. считает текущий объём обоих файловых корпусов и promotion coverage;
2. задаёт один исполнимый `DELETE_OK(source, snapshot)` и показывает его результат на реальных
   файлах;
3. разделяет доказуемую transport/storage полноту и недоказуемую машиной semantic полноту;
4. даёт три extractor-ветки с измеренной либо честно неизвестной ценой;
5. сохраняет общий ledger, но не подменяет KB sink правилом и Git-proof SQLite-proof'ом;
6. запрещает mutation чужого репозитория до content-bound approval receipt.

## Зафиксированный вход #429 — не переисследовался

Принимаются как constraints: единица знания — self-contained Markdown fact line; task gate живёт
на state transition; факт коммитится раньше task event; машина доказывает только доставку
объявленных candidates; semantic completeness требует внешнего oracle; Git-raw удаляется только
после non-shallow + commit existence + `main` reachability + path/blob/SHA parity; rejected и
superseded остаются searchable [1][2].

## Hypotheses considered

### H1 — один ledger покрывает все три части, если adapters являются частью контракта

`source_id`, snapshot digest, candidate IDs, resolutions, required sinks и release receipt общие;
различаются способ snapshot, sink validator и release proof.

**Фальсификатор:** хотя бы один вход требует другого порядка состояний либо удаление одним sink
может лишить сырья другой обязательный sink.

### H2 — один одинаковый pipeline можно применить буквально

Task Markdown, worker memory и compact summary якобы достаточно прочитать одной моделью, записать
одинаковой fact line и удалить одинаковой Git-проверкой.

**Фальсификатор:** текущий consumer требует source bytes по HEAD, источник не является Git blob
или целевой sink не `.orchestra/kb/`.

### H3 — task/worker corpus уже достаточно promoted для массовой уборки

Если большинство директорий связано с KB и точные bytes уже имеют reachable evidence receipts,
cleanup может быть преимущественно механическим.

**Фальсификатор:** большинство task owners не имеет strict promoted fact или exact source receipt.

### H4 — compact summary является lossless source для самоулучшения

Если summary эквивалентен диалогу для rule mining, Part 3 не должен читать raw logs.

**Фальсификатор:** production summary детерминированно исключает часть типов/ходов либо остаётся
current runtime input, который нельзя удалить.

## Method and frozen definitions

Инвентаризация выполнена одним read-only script на Git HEAD
`0f415e840b09a35968c022f55dd37863fa2242a9`; `.orchestra/tasks/454/` исключена, потому что это
сам артефакт измерения и до среза директории не было [3]. Интерпретатор — заданный пользователем
`/mnt/data/Projects/Python/orchestra/.venv/bin/python`.

```bash
/mnt/data/Projects/Python/orchestra/.venv/bin/python \
  .orchestra/tasks/454/measure_inventory.py
```

Скрипт считает regular files, apparent bytes и `st_blocks*512`; парсит bullets только из
`## Установлено` и `## Отвергнуто`; current/rejected/superseded knowledge считается живым, потому
что отрицательное знание не удаляется. Даны две promotion-метрики:

- **legacy upper bound:** bullet связан с task key точным task path либо `#N`;
- **strict forward contract:** тот же link находится в строке с `` `fact:...` ``.

Это не взаимозаменяемые estimands: первая не доказывает stable identity, вторая не засчитывает
legacy facts.

Storage-предикат заморожен до запуска:

```text
STORAGE_DELETE_OK(f, S) :=
    (owner(f) terminal OR exact human approval covers f@sha256)
AND no live consumer outside deletion set resolves f by current HEAD path
AND exists receipt r such that
      r.git_commit exists
  AND r.git_commit is ancestor of protected main
  AND r.git_commit:r.source_path == r.git_blob
  AND sha256(blob(r.git_blob)) == r.source_sha256 == sha256(current bytes(f))
```

Полный release требует ещё два conjuncts из #429:

```text
DELETE_OK(source, S) :=
    external_semantic_oracle_approved(candidate_manifest@digest)
AND every declared candidate has exactly one committed sink resolution
AND every required sink lane for source is committed
AND STORAGE_DELETE_OK(every source member, S)
```

`no live consumer` означает set equality по явному registry обязательных consumer checks; unknown,
unregistered или неисполненный check возвращает false. Syntactic `rg` — только один consumer
adapter, а не доказательство отсутствия динамического reader.

**Проверяемый предикат невыводимого:** файл нельзя удалить из current tree тогда и только тогда,
когда `DELETE_OK=false`. Формулировка не пытается угадать «ценность» текста: неповторимость
операционализирована как отсутствие доказанного replacement/recovery path либо наличие live
HEAD-consumer. Диагностические причины ниже пересекаются; решение принимает одна boolean formula.

SQLite читалась read-only одной snapshot transaction; watermark файлового среза логов —
`max_id=575886`, `max_ts=2026-09-03T08:36:21.592560+00:00`. Git evidence проверено по всем
matching current candidates группировкой по commit tree и batch `git cat-file`; path-only запись
не засчитывалась [3].

## Findings

### F1. Файловое сырьё — 4 203 файла / 90 454 775 apparent bytes

Дословный основной вывод [3]:

```text
.orchestra/tasks: 4 040 files; 89 867 548 apparent B; 99 393 536 allocated B;
                    1 486 Markdown files; 19 834 760 Markdown B; 464 non-empty task dirs
.orchestra/workers: 163 files; 587 227 apparent B; 1 024 000 allocated B;
                      163 Markdown files; 587 227 Markdown B
TOTAL: 4 203 files; 90 454 775 apparent B (86.264 MiB)
```

Следовательно, требование «на done прочитать все `.md`» касается 1 486 файлов / 19 834 760 B в
task corpus, а worker source уже целиком Markdown. Остальные 2 554 task files — tests, raw JSON,
JSONL, images, logs и scripts; удаление всей task directory требует release receipt и для них,
даже если extractor читает только `.md`.

**Confidence: CONFIRMED — direct filesystem measurement, exact script and raw JSON retained.**

### F2. Текущий KB связывает малую долю raw; strict coverage почти отсутствует

В 578 living current/rejected bullets только 75 строк имеют forward `` `fact:` `` key [3].

```text
exact current-path references from living KB facts:
  task files 122 / 4 040 = 3.020%
  worker files 0 / 163 = 0%
strict structured-fact exact references:
  task files 31 / 4 040 = 0.767%
  worker files 0 / 163 = 0%

task-directory linkage:
  137 / 464 have at least one legacy-upper-bound promoted fact
  327 / 464 = 70.474% have none
  13 / 464 have a strict structured promoted fact
  451 / 464 = 97.198% have none under the #429 unit contract
  48 / 464 have an exact task path in a fact
```

137 — намеренно upper bound: `#N` может связывать fact с несколькими prior tasks и не является
exact source locator. Для будущего gate пригодны 13 strict owners, а не 137. Результат опровергает
H3: текущий корпус нельзя массово объявить already promoted.

**Confidence: CONFIRMED для синтаксического coverage; UNCERTAIN для semantic recall — свободный
текст не позволяет установить забытые findings без external oracle.**

### F3. Измеримый no-approval subset сохраняет 3 835 файлов и пропускает 368; полный delete сейчас 0

`measure_inventory.py` исполняет только no-approval subset:
`owner_terminal AND exact_recoverable AND not observed_head_consumer`. Human approval input в
скрипте отсутствует. Observed consumer scanner читает tracked UTF-8 files ≤5 MB и exact relative
`.orchestra/tasks|workers` tokens; absolute, dynamic, binary, larger и untracked consumers он не
доказывает. Поэтому 368 — диагностический pass subset, не `STORAGE_DELETE_OK=true` [3].

На 4 203 реальных candidates [3]:

```text
kept_by_predicate       3 835 files / 86 911 107 B = 91.244% files / 96.082% bytes
passed_storage_gate       368 files /  3 543 668 B =  8.756% files /  3.918% bytes
                         (342 task files + 26 worker files)

overlapping keep reasons:
  active owner                                      547
  unknown owner or no explicit cleanup approval   1 836
  exact current-HEAD consumer                       194
  no exact reachable blob receipt for current bytes 2 745
```

Evidence store содержит 12 759 records. Только 1 492 current candidates имеют хотя бы historical
path record; 1 458 имеют exact current digest и полностью валидный reachable
`commit:path→blob→sha256`. Разница 34 доказывает, что path match без current digest опасен.

Примеры реального pass: `.orchestra/tasks/1/codex-review.md`,
`.orchestra/tasks/100/codex-review-plan.md`. Примеры keep: active
`.orchestra/tasks/108/plan.md`; current consumer `.orchestra/tasks/111/research.md`; missing exact
receipt `.orchestra/tasks/106/analyze_results.py`; unknown owner
`.orchestra/tasks/169/codex-review-research.md` [3].

368 — результат только **observed no-approval storage screen**. Полный consumer registry пока не
существует, а ни один current task/worker source не имеет #454 candidate manifest + external
completeness receipt + all-lanes resolution. Любой неизвестный consumer означает keep. Поэтому
реально разрешённых deletion по полной formula сегодня **0**, а не 368.

**Confidence: CONFIRMED для storage predicate на frozen snapshot; UNCERTAIN для semantic
eligibility, намеренно оставленной external oracle.**

### F4. Три текущих lifecycle seam не вызывают общий pipeline

- `finalize_merge_outcome` связывает commits и ставит `status="done"`, не читая task artifacts и
  не требуя knowledge disposition [4].
- DELETE session проверяет running/children/dirty/unmerged, затем `manager.remove` удаляет
  worktree и только архивирует session row; worker memory/history extraction отсутствует [5].
- `archive_session` меняет status и task binding, но не удаляет logs. Это подтверждает сохранение
  123 655 log rows / 319 811 601 content bytes у archived sessions [3][5].
- `compact` handoff берёт только `user_message`/`text`, отбрасывает platform messages, ограничивает
  последние 10 user turns и 64 000 chars. Это не lossless transcript [6].
- `commit_archive` уже демонстрирует полезный порядок «immutable archive → schedule extraction»,
  но читает только transient `session._turn_logs`, редактирует source через `redact_private`, держит
  extraction status в process-local `_EXTRACTIONS`, а production caller отсутствует [7]. Это
  prototype seam, не готовый owner.

В DB на watermark: 258 651 logs / 701 146 387 content bytes; 612 sessions, из них 516 archived;
непустой `last_summary` есть только у 84 sessions, суммарно 397 618 bytes [3]. Числа не доказывают
semantic loss сами по себе; source code доказывает, какие сообщения summary не включает.

**Confidence: CONFIRMED — primary current code trace + read-only DB measurement.**

### F5. Общая механика одна, но literal «один и тот же pipeline» опровергнут

H1 выдерживает проверку только в форме **один ledger + обязательные adapters**:

```text
SOURCE_SNAPSHOTTED
  → CANDIDATES_DECLARED
  → CANDIDATES_RESOLVED
  → REQUIRED_SINKS_COMMITTED
  → SOURCE_RELEASE_PROVEN
```

Один source record обязан содержать `required_lanes`; deletion возможен только после set equality
между declared и completed lanes. Иначе compact-rule lane может удалить диалог раньше, чем
worker-kill-to-KB lane извлечёт project knowledge.

Различия являются контрактом, а не тремя системами:

| Source | Trigger/owner | Sink | Sink proof | Release proof |
|---|---|---|---|---|
| task artifacts | task completion transition | project KB | exact fact keys + KB validator | Git protected-main blob/SHA + no HEAD consumer |
| worker memory + killed history | two-phase worker retirement | project KB | exact fact keys + KB validator | memory Git proof; ordered log-range archive proof; worktree/session removal last |
| on-demand Markdown | explicit scan proposal | project KB | exact proposed facts/diff | approved manifest SHA + unchanged HEAD/files + Git proof |
| dialogue/compact | compact/archive event | rule/prompt owner, **not KB** | target prompt contains approved anchors and non-target roles do not; rule receipt | ordered log IDs/highwater + immutable private archive; summary current-consumer check |

Part 3 расходится ещё в semantic policy: candidate обязан назвать target (`personal`, project rule,
pipeline role/module, global rule), пройти current trigger test и получить human approval. Запись
generic fact line в `.orchestra/kb/` не доставляет правило в prompt. Pipeline skills реально
доставляются разным runtimes в `.claude/skills`/`.codex/skills`, а orchestrator/sub-orchestrator
role lists являются owners назначения skill [8].

Approval gate Part 3 стоит на переходе `RULE_PROPOSED → RULE_APPROVED`, **до** writer. Receipt
content-bound к `(project_id, exact owner path, owner HEAD/before blob, proposed after-blob/diff
digest, affected roles+scopes, rule keys, delivery-check command+output)`. Apply повторно проверяет
HEAD/before blob; drift возвращает proposal. Для shared/global prompt live-owner positive check
должен пройти до prompt rollout, а approval одного scope не расширяется на другие.

Новый KB sink fact не имеет права ссылаться на удаляемый current path как на evidence. До release
writer обязан записать immutable evidence tuple `(source_commit, historical_source_path,
git_blob, source_sha256)` и resolver обязан читать path только внутри pinned commit. Current-path
link либо переписывается на такой receipt в sink commit, либо остаётся live consumer и блокирует
deletion. Это сохраняет fixed #429 path/blob/SHA contract без dangling evidence.

Для SQLite raw нельзя притвориться, что есть Git source: deletion proof должен фиксировать
ordered `(log_id, payload_sha256)` до highwater и private immutable archive receipt. Compact
summary не replacement raw: он неполон и пока session resumable остаётся live consumer. Если
dashboard/audit продолжает читать logs, либо archive reader принимает этот consumer, либо logs
не удаляются. Rule sink сам по себе chat history не заменяет.

**Confidence: CONFIRMED для расхождения adapters/current consumers; LIKELY для общей state model —
schema, CAS и replay ещё не реализованы.**

### F6. Замороженный Luna prompt провалил lossless gate и нестабилен между повторами

Prompt, 12 gold findings и scorer были закоммичены в `847d17ac` до первого результата. Source —
37 Markdown files / 445 607 B / 5 821 lines из шести реально `done` tasks #416, #417, #419,
#425, #426, #430. Три fresh `gpt-5.6-luna` запуска шли из scratch вне ancestry репозитория, чтобы
модель не могла прочитать KB/gold; source digest во всех трёх равен
`eee996bb…751227d` [11].

Preregistered pass: JSON/schema; 12/12 gold recall; 100% byte-exact evidence, declared line range и
numeric grounding в **каждом** run; pairwise gold coverage Jaccard=1.0. Команда:

```bash
/mnt/data/Projects/Python/orchestra/.venv/bin/python \
  .orchestra/tasks/454/score_extractor_eval.py
```

вернула RC=1 и `pass=false` [11]:

```text
run   candidates   frozen recall   exact quote   exact line range   numeric grounding
1          50        5/12=41.7%       84.75%          83.05%             61.54%
2          31        3/12=25.0%       97.73%          95.45%             94.44%
3          57        4/12=33.3%       65.08%          63.49%             91.67%
candidate count range = 26; frozen recall range = 16.67 pp;
pairwise gold coverage Jaccard = 0.60 / 0.50 / 0.75
```

Preregistration itself имела два дефекта: compound gold требовал независимые atomic facts в одном
candidate, а G419 требовал literal `808`, которого в source corpus не было. Эти результаты не
подогнаны: frozen score сохранён как failed; отдельный post-result diagnostic исключил один
source-invalid gold и match'ит весь candidate set задачи. Он всё равно дал только **8/11=72.7%,
6/11=54.5%, 6/11=54.5%**, recall range **18.18 pp**, minimum pairwise Jaccard **0.556** [11].

Механическая evidence-проверка не ловит неверную temporal status. Ручной counter-check нашёл
одно и то же ложное current knowledge в **3/3 runs**: `task-430-K8`, `task-430-K6`,
`task-430-K10` требуют per-scope/per-worktree receipt, хотя это требование явно отозвано, а user
выбрал forced automatic migration. Нижняя граница semantic falsehood — **3/138 candidates** и
минимум один ложный candidate в каждом run [11].

Три runs использовали 9 249 957 input, 8 722 176 cached input и 109 255 output tokens;
API-equivalent Luna cost по current `CODEX_TOKEN_PRICES` — `$0.11472512`, `$0.16429572`,
`$0.13208488`, всего **`$0.41110572`**. Runs 2/3 заняли 542.395/596.245 s. Первый общий runner
был прерван service restart после run 1; exact interruption receipt сохранён, partial trace без
terminal output удалён как неоценённый воспроизводимый вывод [11].

**Вывод:** выбранный Luna годится как candidate generator, но текущий prompt **не имеет права ни
писать canonical KB, ни удалять source**. Human/external oracle должен видеть raw + candidates, а
не только output модели.

**Confidence: CONFIRMED для failed prompt baseline — frozen repeated experiment. Исправленный
prompt не испытывался и остаётся UNCERTAIN.**

### F7. Project-wide skill имеет median 98 файлов; one-worker-per-file fan по деньгам проигрывает

Read-only `git ls-files -- '*.md'` выполнен на всех 13 registered scopes без failures [12].
Top-level Markdown и canonical owners `.orchestra/kb`, `.orchestra/pipelines`, `.claude/skills`,
`.codex/skills` исключены из deletion candidates; они остаются в total inventory.

```text
13 accessible repositories
tracked Markdown total 5 002; median 102/repo
eligible nested Markdown total 4 833 / 46 510 664 B
eligible/repo: min 4; p25 71; median 98; p75 301; max 1 723
```

При измеренных `$0.31–0.62` cold start и `$0.13` за model/tool round-trip [18] один дополнительный
worker окупается только если устраняет не меньше **3–5 round-trips** (`ceil(0.31/0.13)`…
`ceil(0.62/0.13)`). Наш prompt-run использовал 29/39/45 command calls на 37 files, то есть
0.78–1.22 calls/file [11]. Поэтому one-worker-per-file fan не достигает порога: при одинаковой
работе любой `F≥2` дороже последовательного ровно на `(F-1)×$0.31–0.62`. Для median 98 files
лишние cold starts стоят **`$30.07–60.14`**, ещё до reads/output.

Bounded fan по крупным shards имеет другую цену: три workers добавляют два cold starts,
`$0.62–1.24`. Для **денежной** окупаемости fan обязан именно устранить 5–10 billable calls; перенос
тех же calls с sequential critical path в параллельные children деньги не экономит. Observed
0.78–1.22 calls/file не даёт file-count threshold, потому что неизвестно, какие calls исчезнут.
Для **latency** порог вообще не измерен: fan может сократить wall-clock при тех же calls и большей
цене. Поэтому median 98 доказывает размер workload, но не доказывает ни monetary, ни latency win.

Layout A создаёт write collision: файл сначала классифицируется по content, один source может дать
несколько topics, а разные children могут дать одну тему. Три механики:

1. **split by topic before extraction** — exclusive writer, но требует отдельного classifier и
   теряет multi-topic facts;
2. **per-topic write queue/lock** — сериализует bytes, но не решает semantic duplicate/status race;
3. **fan только читает и возвращает immutable candidate shards; один writer resolves/dedupes и
   коммитит topic packs** — сохраняет параллельное чтение и одного canonical owner.

Третья механика единственная не требует знать topic заранее и не даёт N children писать один
Markdown owner. Writer начинает после fan barrier и human approval, не в child worktrees.

**Confidence: CONFIRMED для corpus/cost arithmetic и write collision; UNCERTAIN для wall-clock
break-even — parallel latency experiment не выполнялся.**

### F8. Timing task-close противоречит входу #429; три трактовки имеют разные failure costs

Промежуточная формулировка пользователя говорила «task работает как сейчас, Luna фоном **после
закрытия**». Fixed input #429 требует fact commit **до** task done event. Оба порядка одновременно
невозможны; эта разобранная развилка объясняет последующий выбор F9 и не удаляется из отчёта.

| Трактовка | Luna упала/quota/malformed | Десять task закрылись | Что ломает source deletion |
|---|---|---|---|
| **A. `done` сейчас, потом fire-and-forget** | Task уже done. Обычный `bg run` сообщает failure при exit, а restart interruption — только после следующего startup; без durable debt failure остаётся уведомлением, не обязательством | merges/task statuses не блокируются; десять независимых забываемых попыток | delete в том же Luna pass превращает measured 54.5–72.7% recall и 3/3 stale falsehood в необратимую потерю |
| **B. fact/approval до `done` (#429)** | Git merge может уже существовать, но finalization остаётся post-commit partial; worker/task не получают terminal lifecycle | десять зависших extractions → десять незавершённых finalization; очередь/worker bindings растут, хотя source сохраняется | source нельзя удалить до human approval; extractor hang блокирует closure, но не теряет raw |
| **C. `done` сразу + durable debt** | Task flow не блокируется; durable item хранит source manifest/status/error, source остаётся до drain | долг растёт на 10 и виден как 10 items; backpressure можно применить отдельно от merge | delete разрешён только отдельному drain/apply после approved sink receipt; failed item оставляет raw |

Пользователь отверг чистые A/B/C и выбрал F9: worker освобождается, но task остаётся
`knowledge_pending`; закрывает task successful durable drain.

**Что уже есть фактически:** SQLite `bg_jobs` хранит config/status и восстанавливает active
timer/file/command/ssh/cron jobs после restart; active `run` **не перезапускается**, а помечается
interrupted и будит target [13]. Этот контракт подтверждён текущим eval: service restart прервал
run, платформа прислала `INTERRUPTED`, автоматического retry не было [11].
`app/ia/recovery.commit_archive` ещё слабее для этой цели: extraction живёт в process-local
`_EXTRACTIONS` и запускается `asyncio.create_task` [7]. Durable delivery гарантирует доставку wake,
но не завершение extraction/resolution. Следовательно, **готовой durable extraction queue с item
state, mandatory drain и source receipt сейчас нет**. Ветка C требует нового durable work-item
owner; существующий `bg_jobs` — scheduler substrate, не такой owner.

Удаление — отдельный deterministic step с human approval. Same-pass order стоит ноль добавочных
model turns, но текущий `$0.1147–0.1643` extractor получает право уничтожать source при доказанно
неполном/нестабильном output. Separate order стоит тот же Luna run + один human approval turn на
batch; approved lines пишет один deterministic writer, поэтому дополнительный model run не нужен.
Цена — raw хранится до drain и visible debt растёт. Это сравнение порядка удаления, не выбор между
другими extractor architectures.

### F9. Выбран intermediate state: worker свободен, task закрывает durable extraction drain

Пользователь после разбора F8 выбрал точный переход:

```text
in_progress --work/merge complete--> knowledge_pending --approved drain--> done
                                      \--one failed auto attempt--> knowledge_blocked
```

Это снимает конфликт #429: canonical `done` появляется после sink fact и release proof, но
исходный worker освобождается сразу после merge. Current topology уже разделяет эти действия:
`prepare_merge_finalization(... outcome="complete")` строит terminal session без task, а
`finalize_merge_outcome` отдельно ставит task `done` и очищает `worker_session_id` [16]. Значит
точный lifecycle owner — `app/tm.py:861-924,1320-1372`: первое изменение заменяет `done` на
`knowledge_pending`, сохраняя release worker/reservation; отдельный internal drain finalizer с CAS
ставит `done`. Agent-facing `task_update` не получает это право: сейчас он code-enforced отвергает
platform-owned `in_progress/done`, и к set добавляются оба knowledge-status [16].

Физически status обязан жить там же, где task state сейчас:

- canonical `task.state.status` + `metadata.knowledge_extraction` с `source_digest`,
  `prompt_commit`, `attempt_id`, phase/error и sink/release receipts;
- legacy `tm_tasks.status` остаётся mirror/query projection текущего dual-owner transition;
- validator owners: `app/tm.py:32`, `app/ia/task_store.py:54`; SQLite `CHECK` в
  `app/db.py:439-460,1310-1331`; canonical schema уже разрешает typed `metadata`, но facade его
  сейчас не показывает [16].

Это уже классический duplicate-owner blocker: одна допустимость status скопирована в legacy
`VALID_STATUSES`, canonical `_VALID_STATUSES` и SQLite `CHECK` (сам CHECK дословно повторён в
create и rebuild schema). Расхождение любой копии либо отвергает transition, либо сохраняет state,
который другой слой не читает. Новый enum нельзя добавить только в одном месте: dashboard
группирует tasks исключительно по `STATUS_ORDER`, поэтому неизвестный status вообще не рисуется и
для пользователя выглядит как пропавшая задача. Видимость должна появиться в
`app/static/js/app.js:3953-3963,4303-4351` как раскрытая группа `EXTRACTION (N)` и отдельная красная
`EXTRACTION BLOCKED (N)`; API `task_list(status=...)` получает тот же validator enum. `completed_at`
остаётся null в обоих промежуточных состояниях и выставляется только финальным `done`, как сейчас
делают `app/tm.py:635-637` и `TaskStore.task_update:1389-1393` [16].

#### Сколько было бы видно сейчас

На DB watermark `2026-09-03T09:57:29.538867+00:00` у Orchestra 174 `done` tasks. При строгом
retroactive правиле «есть matching `.orchestra/tasks/<par>/`, но нет нового drain receipt» [15]:

```text
KNOWLEDGE_PENDING: 141 tasks, 1 525 files / 28 316 996 B,
                   из них 426 Markdown / 4 829 619 B
EXTRACTION_BLOCKED_SOURCE_MISSING: 33 done tasks без matching source directory

внутри 141 pending:
  134 tasks / 919 files / 19 960 797 B не имеют ни одного structured promoted fact;
  7 tasks / 606 files / 8 356 199 B имеют ≥1 fact, но не имеют нового drain receipt
```

При prospective-only rollout initial count был бы 0, но historical raw не очистился бы. Поэтому
число для истории — 141 pending + 33 blocked, а не 0 и не все 174 как runnable extraction.

Ретро — отдельный выбор пользователя, не часть rollout. Цена двух вариантов по одному counting
rule:

| Rollout | Исторические Luna turns | Исторический virtual cost | Что остаётся |
|---|---:|---:|---|
| **Только вперёд** | **0** | **`$0`** | 141 source-backed historical tasks не переходят в новый drain автоматически; 33 source-missing остаются отдельным debt |
| **Разобрать весь runnable backlog** | **141** (один background Luna turn/task) | **`$87.13–154.89`** | 141 cold starts × `$0.31–0.62` плюс 426 Markdown × observed 29–45 command calls / 37 files = ceil **334–519** calls × `$0.13`; 33 missing-source tasks моделью не запускаются |

Это arithmetic range, не quote: lower=`141×0.31 + 334×0.13`; upper=`141×0.62 + 519×0.13`.
Model output/review/human approval сверх указанных cold-start/call owners сюда не добавлены, поэтому
range является нижней оценкой полного backfill, а не бюджетным cap. Batch нескольких tasks одним
worker изменит cold-start count и требует отдельного решения; выбранный per-task event shape даёт
141.

#### Failure ceiling и terminal outcome

Готового retry owner сейчас нет: `bg_jobs run` делает одну попытку и после обычного fail/timeout
либо restart-interrupt будит target, но не перезапускает; queue item state для extraction
отсутствует [13]. Fail-closed contract для первого rollout:

- максимум **одна автоматическая попытка** на exact `(task stable_id, source_digest,
  prompt_commit, model)`;
- quota/preflight, process exit, malformed JSON, evidence/consumer check failure и semantic reject
  переводят task в `knowledge_blocked`, записывают exact error/attempt receipt и оставляют raw;
- `knowledge_blocked` terminal для automation, но не `done`; manual explicit requeue создаёт новый
  `attempt_id` и обязан назвать изменившееся условие (quota restored, new prompt commit либо source
  revision). Тихого retry той же модели/prompt/source нет.

Число 1 следует выбранному дешёвому Luna executor и наблюдаемому prompt failure: три identical
runs не сходятся, поэтому повтор не является completeness proof. Policy можно ослабить только
после отдельного retry-yield замера; сейчас бесконечный pending запрещён.

#### Crash-safe order одного durable drain item

```text
0. task event: status=knowledge_pending + source manifest/digest; worker unbound; raw intact
1. claim attempt by CAS; Luna writes candidate artifact only
2. machine validation + external/human semantic approval bound to candidate digest
3. single writer commits topic-pack facts with immutable source commit/path/blob/SHA evidence
4. verify sink commit reachable + every candidate/lane resolved + full consumer registry green
5. commit exact approved raw deletion; verify old source blob remains reachable and deletion tree
6. one TaskStore event records sink+deletion receipts and sets status=done/completed_at
```

Crash after 0–2 leaves pending/blocked + raw. Crash after 3 leaves knowledge + raw. Crash after 5
leaves task pending with raw absent from HEAD, but fact and pinned historical source already
reachable; replay verifies exact receipts and performs only step 6. Ни один prefix не создаёт
`done` без fact и не удаляет raw без fact. «Тот же проход закрывает task» означает один durable
drain item/attempt; human approval не требует держать Luna process живым.

| Сбой | Durable state/task | Fact sink | Raw current tree | Recovery |
|---|---|---|---|---|
| до/внутри step 0, до atomic task event | прежний `in_progress`; worker binding/reservation ещё старые | нет | есть | штатный merge-finalization replay |
| после step 0, до claim | `knowledge_pending`, worker уже unbound | нет | есть | drainer забирает item |
| внутри step 1 | pending lease либо `knowledge_blocked` с exact attempt error; partial model output не canonical | нет | есть | explicit requeue только новым attempt id |
| внутри step 2 | `knowledge_pending/awaiting_approval`; partial approval не существует без content-bound receipt | нет | есть | человек approve/reject exact digest |
| до Git ref update step 3 | pending + approved manifest | нет | есть | writer replay; candidate IDs idempotent |
| после atomic fact commit, до step 5 | pending + sink receipt | reachable immutable fact | есть | validators/release replay |
| во время deletion commit до ref update | pending + sink receipt | reachable | есть | повторить exact approved deletion |
| после deletion ref update, до step 6 | pending + sink/deletion receipts | reachable | отсутствует в HEAD, source blob достижим исторически | TaskStore replay проверяет receipts и закрывает |
| после atomic step 6 | `done`, `completed_at`, оба receipts | reachable | отсутствует в HEAD, source blob достижим исторически | idempotent no-op |

Executable state-model probe прошёл все 8 crash prefixes: `prefixes_ok=8`, каждый replay дошёл до
`done`, а отдельный failed-attempt arm дал `failed_attempt_raw_retained=true` [17]. Probe проверяет
порядок/invariants модели, не существующую production implementation.

**Confidence: CONFIRMED для current owners, visibility failure and retroactive counts; selected
transition is a direct user decision. One-attempt failure contract and metadata shape are PROPOSED
for Phase 2, not current code.**

## Part 2 — чужие проекты: dry-run и approval gate

Live `tm_projects` на 2026-09-03 содержит 13 non-empty scopes: Orchestra + 12 других targets [10].
Skill-only prompt enforcement недостаточен: слишком широкое применение уничтожает чужие файлы;
движок apply/delete обязан быть code-enforced, а skill только вызывает scan/apply и объясняет
receipt. Existing skill injector также прямо считает orchestrator cwd реальным пользовательским
репозиторием и отказывается перезаписывать tracked skill files [8].

### Read-only dry-run

1. Разрешить target по `git rev-parse --path-format=absolute --git-common-dir`; не переходить
   symlink, nested repo или submodule boundary.
2. Зафиксировать `project_id`, repo common dir, protected ref, HEAD, shallow state, `git status`,
   каждый candidate path/mode/size/SHA. **Все top-level files исключены**, не только
   `CLAUDE.md`/`AGENTS.md`/`README.md`; `.git`, `.orchestra/kb` и pipeline owners не являются raw.
3. Выполнить полный registered consumer set; lexical scan tracked UTF-8 — только один adapter.
   Неизвестный/dynamic consumer, unknown owner, untracked/dirty source, external current-path ref
   или missing Git proof получает `BLOCKED`, не heuristic delete.
4. Extraction выполняется вне target tree; proposal содержит каждую self-contained fact line,
   `promoted|duplicate|non_durable`, proposed sink diff, exact deletion list и byte delta.
5. Вернуть immutable manifest с `proposal_id`, `manifest_sha256`, target HEAD/ref, candidate set,
   blocked set, fact keys, additions/deletions. Dry-run **не пишет** в чужой repo.

### Approval receipt and two-stage apply

Human approval обязан дословно покрыть tuple:

```text
(project_id, git_common_dir, protected_ref, target_head,
 manifest_sha256, approved fact/resolution IDs, deletion paths+sha256)
```

Apply повторно строит manifest. Любой drift HEAD/status/file digest/incoming refs → refusal и новый
dry-run; approval нельзя переносить. Затем:

1. commit только sink facts/resolutions с immutable source commit/path/blob/SHA evidence, без
   current-path dependency на удаляемый raw;
2. validate KB and merge/reachability of sink/source commit on protected main;
3. повторить `STORAGE_DELETE_OK` на свежем tree;
4. отдельным commit удалить только approved exact paths.

Пустой manifest, partial resolution, approval другого repo/HEAD и `force` не обходят gate.
Top-level files остаются immutable policy даже при approval этого cleanup skill: их изменение —
отдельная задача. Raw conversation в public target repo также не коммитится как evidence; для него
нужен private archive adapter.

**Confidence: LIKELY — dry-run/CAS следует измеренным Git/source contracts, но apply prototype и
foreign-repo rehearsal не выполнялись в Phase 1.**

## Counter-evidence and limits

- 368/4 203 storage-pass не означает 368 безопасных semantic deletions; полный gate сегодня даёт
  ноль из-за отсутствующих manifests/oracle receipts.
- 34 files имеют historical path record, но изменившийся digest. Это прямой counterexample
  «incoming evidence path достаточно».
- 137 task dirs по legacy upper bound превращаются в 13 по strict `fact:` contract. Любой один
  coverage number без определения вводит в заблуждение.
- Luna extraction была дешёвой, но reviews нашли fidelity omissions; модель не может подписывать
  собственную semantic completeness.
- Frozen #454 prompt не просто имеет теоретический риск: strict scorer дал RC=1, post-hoc
  source-valid recall не превысил 72.7%, а superseded rollout rule вернулся как `current` в 3/3.
- One ledger не означает one sink и one release validator. Literal unified implementation H2
  refuted: task/worker sources — Git+KB, dialogue — ordered logs+rules/prompts.
- Logs уже маскируются на записи, но остаются dashboard/audit source; правило в prompt не является
  функциональным replacement истории.
- Измерен только recall 11 source-valid gold и минимальная semantic falsehood на шести task
  sources; полная semantic precision для 138 candidates, worker-memory/compact modes, время human
  approval, queue latency, concurrent CAS conflicts и foreign-repo dry-run false positives не
  измерены.

## Affected files and future implementation surface

Phase 1 ничего из перечисленного не меняла:

- task state owner: `app/tm.py:1320-1372`, `app/routes/sessions.py:1699-1740`,
  `app/ia/task_store.py`, `app/ia/schema.py`;
- intermediate-status mirrors/consumers: `app/tm.py:32`, `app/ia/task_store.py:54`,
  `app/db.py:439-463,1310-1331`, `app/mcp_stdio.py:2930-2946`,
  `app/static/js/app.js:3953-3963,4303-4351`, completion analytics that select only `done|paid`;
- worker retirement: `app/routes/sessions.py:1569-1637`, `app/manager.py:1218-1247`,
  `app/db.py:1979-1993`;
- dialogue/compact/archive: `app/session.py:2831-3100,3278-3329`,
  `app/ia/recovery.py:291-418`;
- code-enforced shared ledger/queue: new owner is required; exact file/name is Phase 2 architecture,
  not selected here; task status itself is the durable queue index, while attempt/source/sink
  receipts remain canonical task metadata rather than one `bg_jobs` row per task;
- universal orchestrator skill delivery: `.orchestra/pipelines/default/prompts/skills/`,
  `.orchestra/pipelines/default/pipeline.yaml:35-67`, `app/prompting.py:232-320`;
- KB validator/retrieval: `scripts/check_kb_contract.py`, `.orchestra/kb/`;
- prompt/eval owner: `.orchestra/tasks/454/extractor-prompt.md`, frozen gold and scorers; в Phase 2
  revised prompt должен получить новый version/commit, старые runs навсегда остаются baseline;
- Phase-2 tests must cover missing candidate, false `non_durable`, two required lanes, replay,
  source drift, live HEAD consumer, task pending state, kill failure before worktree removal,
  compact raw-vs-summary, cross-repo receipt substitution, symlink/nested repo and empty manifest.

## Review gate inputs

### Round 1 resolution

Fresh Luna returned six blocking findings and one suggestion in
`.orchestra/tasks/454/review-research-luna.md`; all were verified and accepted:

1. parenthesized `(terminal OR approved)` before the remaining `AND` clauses;
2. renamed 368 as the measured no-approval subset, not the full predicate;
3. made consumer checks an explicit fail-closed registry and downgraded lexical scanning to one
   incomplete adapter;
4. separated eliminated billable calls from parallelized critical-path calls and removed the
   unsupported 3–7-file latency threshold;
5. required immutable sink evidence before current-path source deletion;
6. bound Part 3 approval to exact owner/head/blob/diff/roles/scopes/check output;
7. split KB provenance between exploratory recall and preregistered evidence rates.

Artifact changed materially, so one same-session follow-up is allowed; this is the second and
final prose round. Round 2 marked all seven items `FIXED`, added no finding and returned
`APPROVED for Phase 1 prose/research`; its exact evidence quote is present at F7 [14].
После Round 2 пользователь выбрал intermediate state; F9 и backlog measurement добавлены после
review. Третий model round запрещён prose ceiling, поэтому post-decision delta имеет только
mechanical source/count/KB-contract checks и явно не прикрывается старым `APPROVED`.

- **Changed files/consumers:** only `.orchestra/tasks/454/`, `.orchestra/kb/knowledge-pipeline.md`
  and KB README entry; consumers are the user and future Phase 2. No production code/prompt changed.
- **Author metadata:** current Codex API session; exact runtime model metadata is not exposed in
  repository state and is not inferred from the agent name.
- **Exact AC:** mandatory Phase-1 requirements from task #454 plus updates: chosen background Luna,
  layout A, prompt repeatability test, fleet Markdown count/fan threshold and explicit lifecycle
  order conflict; no implementation/plan.
- **Named checks:** inventory script; project Markdown inventory; frozen prompt scorer → expected
  RC=1/`pass=false`; post-hoc diagnostic; KB forward-contract validator → `KB contract OK`.
- **Risk floor:** destructive data-loss path + shared lifecycle/prompt contract; strong semantic
  oracle absent. Canonical technical route would be Sol, but auxiliary Sol was not explicitly
  authorized. One fresh Luna session plus one evidence-backed same-session prose follow-up used
  the permitted route; round ceiling reached.

## Sources

1. **Tier 2, primary task input:** `task_get("454")`, fetched 2026-09-03 — three parts, fixed #429
   conclusions and mandatory Phase-1 measurements.
2. **Tier 2, accepted prior local research:**
   `task-429/research-kb-structure:docs/tasks/429/research.md`, read in full 2026-09-03 — atomic
   fact, transition owner/order, semantic boundary and Git deletion proof.
3. **Tier 1, direct measurement:** `.orchestra/tasks/454/measure_inventory.py` and frozen
   `.orchestra/tasks/454/inventory-output.json`; exact command above; HEAD and DB watermark embedded.
4. **Tier 2, primary current code:** `app/tm.py:1320-1372`, task completion without knowledge
   disposition.
5. **Tier 2, primary current code:** `app/routes/sessions.py:1569-1637`,
   `app/manager.py:1218-1247`, `app/db.py:1979-1993`, current kill/archive sequence.
6. **Tier 2, primary current code:** `app/session.py:2831-3100,3278-3329`, compact and bounded
   runtime handoff.
7. **Tier 2, primary current code:** `app/ia/recovery.py:291-418`, unwired process-local archive
   extraction prototype.
8. **Tier 2, primary current code/config:** `app/prompting.py:232-320`,
   `.orchestra/pipelines/default/pipeline.yaml:35-67`, current cross-runtime skill delivery and
   orchestrator role lists.
9. **Tier 1, direct historical measurement:** read-only `turn_usage` for tasks #399–#403 plus
   `.orchestra/tasks/kb-extract/part-1..5.json` and review artifacts — 22 sources, 764 candidates,
   12 turns, `$0.95704324`, observed fidelity defects.
10. **Tier 1, direct current measurement:** read-only `tm_projects` query — 19 rows, 13 non-empty
    scopes, 12 targets outside Orchestra on 2026-09-03.
11. **Tier 1, frozen repeated model experiment:** `.orchestra/tasks/454/extractor-prompt.md`,
    `eval-gold.json`, `eval-run-{1,2,3}.{txt,jsonl}`, `eval-run-manifest.json`,
    `eval-score-preregistered.json`, `eval-score-setlevel.json`, `eval-semantic-audit.json` — three
    fresh Luna runs on the same 37-file digest; prompt/gold commit `847d17ac` precedes outputs.
12. **Tier 1, direct fleet measurement:** `.orchestra/tasks/454/measure_project_markdown.py` and
    `.orchestra/tasks/454/project-markdown-output.json` — exact `git ls-files` per 13 registered
    repository HEADs, zero inaccessible repos.
13. **Tier 2 primary code + Tier 1 incident:** `app/db.py:528-547`,
    `app/bg_jobs.py:488-539,650-714`, `tests/test_bg_jobs.py:813-836`; actual #454 run interruption in
    `eval-run-manifest.json` — scheduler persists, active `run` is not restarted.
14. **Independent Luna review:** `.orchestra/tasks/454/review-research-luna.md` — Round 1 six
    blocking + one suggestion; all accepted; final prose Round 2 marks 7/7 fixed, no new findings,
    `APPROVED for Phase 1 prose/research` with exact artifact quote.
15. **Tier 1, direct backlog measurement:** `.orchestra/tasks/454/measure_pending_backlog.py` and
    `.orchestra/tasks/454/pending-backlog-output.json` — current read-only `tm_tasks` status joined
    to worktree artifacts and structured fact links under the embedded snapshot/head.
16. **Tier 2, primary current code:** `app/tm.py:32,628-638,861-924,1320-1372`,
    `app/ia/task_store.py:54,1370-1395`, `app/ia/schema.py:44-58,253-264`,
    `app/db.py:439-463,1310-1331`, `app/mcp_stdio.py:2930-2946`,
    `app/static/js/app.js:3953-3963,4303-4351` — status persistence, platform authority,
    completed_at and dashboard visibility owners.
17. **Tier 1, direct state-model experiment:** `.orchestra/tasks/454/probe_drain_prefixes.py` and
    `.orchestra/tasks/454/drain-prefix-output.json` — eight crash prefixes + failed-attempt arm,
    all safety assertions and replay checks passed.
18. **Tier 1, supplied measured cost constants:** task update from `Orchestra-orchestrator`,
    2026-09-03 — worker cold start 49–62K tokens / `$0.31–0.62`, one tool/model round-trip ≈`$0.13`;
    used only for explicit arithmetic, not as a latency measurement.
