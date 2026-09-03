# #417 — общая память агентов поверх `docs/kb`

Дата: 2026-08-30. Только Phase 1: внешние первичные источники, чтение текущего кода и
read-only измерения структуры `docs/kb`. Production, prompts, runtime state и индексы не менялись.

## Короткий вывод

Orchestra уже имеет правильный canonical-слой — project-local `docs/kb/` в Git. Строить рядом
ещё одну «память» не нужно. Нужны три независимо выбираемых улучшения поверх него:

1. **Поиск:** сначала проверяем agentic keyword retrieval обычными `rg`/`sed`, с несколькими
   уточняющими запросами и дедупликацией по текущему пути. Отдельный read-tool для этого не
   проходит пользовательский гейт: без него агент пишет две короткие shell-команды, не большой
   Python. Текущий `search_memory` остаётся compatibility-механизмом до отдельного решения
   пользователя, но не является фундаментом новой архитектуры.
2. **Связи:** факты могут явно ссылаться на факты соседних тем; обратные ссылки и граф — только
   производная навигация. LLM может предложить связь, но не записать её как истину и тем более
   не переписать старый факт. При 22 topic-файлах в текущем worktree отдельная graph DB пока не
   обоснована.
3. **Версии:** нынешняя пометка `ОТОЗВАНО` достаточна, чтобы человек не потерял историю, но
   недостаточна для запросов `current/as_of`, споров и контроля конфликтов. Машинное
   версионирование — отдельная дорогая развилка: stable `fact_key`, valid-time, status,
   provenance и explicit `supersedes`; начинать forward-only, без миграции 20 502 записей.

Текущий generic `knowledge(operation, payload)` **не доказал право быть универсальным интерфейсом**:
его mutation-часть скрыта за непрозрачным `payload`, доступна только оркестраторам и не создала
корпуса фактов. Но projection-backed query не эквивалентен сырому `rg`, поэтому удалять его только
по adoption нельзя. В A/B он остаётся отдельным control arm. Если пользователь выберет typed
branch, существующий deterministic state machine можно сохранить как внутреннюю
библиотеку/merge-validator и заменить generic wrapper узкими `kb_promote`/`kb_as_of`; если query
победит, его read-семантика также сохраняется под явным контрактом.

Судьба 808-МБ projection: **рекомендация — не нести её в целевую схему как есть**, но это не
принятое решение. Немедленное удаление также
не доказано: usage ≠ quality. Правильный гейт — frozen A/B минимум на 18 уже существующих вопросах
#256 плюс новый набор common-word/multi-hop запросов. Нет уникальных полезных побед vector arm →
    удалить rebuildable 808 МБ; есть победы по заранее заданному порогу → перестроить только project-local curated
    facts/topics, не переносить 20 502 старые resource/task записи. Ни одна развилка в этом
    research не выбрана: после `RESEARCH DONE` решение принимает пользователь.

## 1. Вопрос и критерий решения

- **Context:** все агенты Orchestra во всех проектах должны пользоваться одной формой памяти,
  сохраняя project isolation. Canonical знания проекта уже находятся в `docs/kb/`; полное
  доказательство остаётся в `docs/tasks/`.
- **Change under test:** поверх Markdown добавить ровно те механизмы, которые улучшают поиск,
  связи и версионирование, не создавая второй owner или обязательный мёртвый tool.
- **Baseline:** обязательное чтение `docs/kb/README.md` и релевантных тем, затем `search_memory`;
  agent-facing `knowledge`; центральная projection 808 МБ; ручные `ОТОЗВАНО` и отсутствие
  cross-topic adjacency.
- **Measurable outcome:** доля задач, где агент находит нужный current/rejected fact; stale
  contradiction; multi-hop success; provenance; tool calls/tokens/time до первого полезного
  факта; false supersession; authoring friction; prompt footprint; bytes/rebuild time derived
  indexes. Retrieval score без task outcome — только diagnostic.

## 2. Гипотезы и фальсификаторы

| Гипотеза | Что доказало бы её неправильной | Текущий статус |
|---|---|---|
| **H1. На curated Markdown агентный keyword search даст большую часть пользы vector RAG.** | На frozen локальных вопросах FTS/vector стабильно решает вопросы, которые bounded `rg` arm не решает, при том же context budget и без stale contradictions. | **LIKELY, не доказано у нас:** Amazon показал конкурентность на PDF-QA, но не на Orchestra [8]; текущий `search_memory` один раз упёрся в собственный 5-секундный deadline. |
| **H2. Atomic facts + explicit links улучшат cross-topic/multi-hop без graph DB.** | На ≥10 multi-hop вопросах typed links/backlinks не улучшают task success против README+keyword либо добавляют больше нерелевантного контекста, чем полезного. | **LIKELY:** A-MEM ablation поддерживает полезность links на LoCoMo [6], но corpus и task class чужие. |
| **H3. Автоматическая эволюция/перезапись безопасна как canonical authority.** | Auto-update на frozen conflict corpus даёт 0 false supersession, полную историю, deterministic replay и одинаковый current state на разных моделях. | **НЕ ПРИНИМАТЬ без safety proof:** A-MEM заменяет metadata старых заметок на месте без заполнения `evolution_history` [7]; отдельный Graphiti mechanism показывает тот же опасный outcome — collateral retirement [12]. Это не доказывает общий causal bug, но показывает цену ошибки. |
| **H4. Ручного `ОТОЗВАНО` достаточно для всей версии фактов.** | Агент механически отвечает на `что было верно на дату T`, отличает historical от rejected и связывает замену с прежним фактом без свободной интерпретации текста. | **REFUTED для machine query; CONFIRMED для human audit.** Git и сохранённая строка не дают stable identity/valid-time. |
| **H5. 808-МБ vector projection нужно снести сейчас.** | Usage и состав корпуса сами по себе доказывают отсутствие уникальных полезных ответов vector arm. | **НЕ ДОКАЗАНО:** usage показывает слабое принятие, не marginal retrieval value. Удаление разрешает только локальный A/B. |

## 3. Что принято как вход, а что измерено здесь

### 3.1 Вход пользователя — не перемерялся

За последние 7 дней: file reads `docs/kb/` = **1 709**, `search_memory` = **256**,
`knowledge` = **39**. В projection: **20 502 records / 165 МБ content**, из них
**19 773 resource (96.44%)** и **729 task.state (3.56%)**; фактов нет. Projection file =
**808 МБ**. Это direct measurement пользователя для #417 [1].

Эти числа доказывают adoption и corpus shape, но не качество ответов. Из них нельзя честно
вывести «каждый vector lookup бесполезен».

### 3.2 Текущий worktree — новый read-only срез

Команда:

```bash
python3 - <<'PY'
from pathlib import Path
import re
root = Path('docs/kb')
files = sorted(p for p in root.glob('*.md') if p.name != 'README.md')
names = {p.name for p in files}
links = []
for p in files:
    for target in re.findall(r'\[[^\]]*\]\(([^)#]+\.md)(?:#[^)]+)?\)', p.read_text()):
        if Path(target).name in names and Path(target).name != p.name:
            links.append((p.name, Path(target).name))
print(len(files), sum(p.stat().st_size for p in files), len(links),
      len({a for a, _ in links}), len({b for _, b in links}))
PY
```

Вывод: **22 topic files, 283 573 Б, 2 cross-topic link occurrences, 1 source topic,
1 target topic**. Обе ссылки — `token-efficiency.md → prompt-delivery.md`; 21 из 22 тем не
ссылаются на соседнюю тему. Отдельный подсчёт bullets дал **366 `Установлено`, 83 `Отвергнуто`,
82 `Пробелы`**; exact `ОТОЗВАНО` встречается в двух topic-файлах [2].

Это намеренно **top-level topic-body adjacency lower bound**: README исключён как навигационное
оглавление, nested Markdown не входил, а смысловые связи и другие формулировки supersession не
считались. Число не является corpus-wide graph measurement.

### 3.3 Текущий delivery и tool surface

- Один `memory-search.md` включён для orchestrator, sub-orchestrator, worker и full-cycle через
  `pipeline.yaml`; reducer имеет `modules: []`, потому что не должен интерпретировать отчёты
  [3]. Значит, «для всех агентов» нужно реализовывать одним общим protocol owner, а не копиями
  в ролях; обязательное чтение для reducer было бы пустой тратой, доступность project files при
  этом общая.
- `knowledge` имеет generic `payload: dict`, а его docstring не раскрывает promotion/query schema
  [3]. В live runtime mutation разрешена только orchestrator/sub-orchestrator; working agents,
  которые реально пишут research/KB, могут только query [3].
- Внутри уже существует строгая state machine: `fact_key`, statuses, valid-time, explicit
  supersede/disputed, evidence, CAS/head и as-of query (`app/ia/knowledge.py`) [3]. Проблема не в
  отсутствии ещё одной схемы, а в том, что agent-facing seam не принят и фактов нет.
- `search_memory` после 5 секунд отправляет агента в literal `rg "<whole query>" ...`; именно
  агентная декомпозиция запроса, а не буквальный перенос всей фразы, является механизмом Amazon
  и Search-R1 [3][8][9].

## 4. Сравнение подходов

Чужие числа ниже — измерения авторов на их corpus/model, не результаты Orchestra.

| Подход | Что даёт | Чем платим / counter-evidence | Подходит Orchestra |
|---|---|---|---|
| **Текущий `docs/kb` + Git** | Human-readable canonical; evidence в строке; rejected roads сохраняются; offline/clone/review. | Нет stable fact identity, as-of и adjacency; 2 literal cross-topic links на 22 темы; prompt discipline можно пропустить. | **Оставить owner.** Это база всех развилок, не baseline для замены. |
| **A-MEM / Zettelkasten** [6][7] | Atomic notes, LLM metadata, links к соседям; selective top-k. Авторы заявляют ≈1 200 tokens/operation и −85–93% против 16 900-token baselines; ablation связывает links/evolution с ростом LoCoMo scores. | LoCoMo/DialSim — разговоры, не coding/research. Exact «до 6×» в доступной paper v11/official repo не найдено, поэтому здесь не подтверждается. Production-code меняет `tags/context` старых notes на месте; `evolution_history` не пополняется; index refresh отложен. | **Взять atomicity и candidate links. Auto-rewrite не давать canonical authority до отдельного safety proof.** |
| **Zep / Graphiti temporal graph** [11–14] | Episodes не теряются; facts связаны с source episodes; valid/invalid и transaction time; current и historical retrieval; BFS + BM25 + vectors. Авторы: Zep 94.8% vs 93.4% DMR, LongMemEval 1.6k vs 115k context [11]. | DMR помещается целиком в context, что признают сами авторы. Issue #1728: 1 616/3 950 invalidated, 3/4 hand-audited retirements collateral; #1275: O(n) prompt и silent drop; #1661: reference time write-only. | **Взять bitemporal fields/provenance. Graph/LLM никогда не решает supersession.** |
| **GraphRAG survey / graph integration** [10] | Разделяет задачу на graph indexing, graph-guided retrieval и graph-enhanced generation; graph полезен для paths/subgraphs и relational questions. | Quality graph construction определяет весь downstream; candidate subgraphs растут экспоненциально; survey не доказывает benefit на 22 topics. Exact формулировку «28 методов» в accessible overview не удалось связать с одним проверяемым count. | **Только derived adjacency после multi-hop A/B.** Отдельная graph DB сейчас преждевременна. |
| **Agentic keyword search (Amazon)** [8] | Агент итеративно пишет `rga/pdfgrep`, меняет запрос по результатам; standing vector DB не нужен. Author results: faithfulness attainment 94.52%, context recall 88.05%, answer correctness 91.48% относительно их RAG. | Не «94.5% общего качества». Шесть PDF corpora, Claude 3 Sonnet, RAGAS/LLM judge; large docs, ambiguous queries и nuance названы limitations. | **Обязательный дешёвый control arm.** Механизм почти совпадает с `rg` по Git corpus. |
| **Search-R1** [9] | RL обучает модель interleave reasoning и несколько searches; авторы показывают average relative +24%/+20% на 7 QA datasets. | Это training method для Qwen 3B/7B, не готовый retriever и не prompt для закрытых Codex/Claude models. В тексте paper есть внутренняя разница headline 24%/20% vs contribution 41%/20%, поэтому переносить число нельзя. | **Взять только bounded iterative search protocol; RL не строить.** |
| **Mem0 / Mem0g** [15][16] | Atomic extraction, multi-signal semantic+BM25+entity+time; current vendor docs описывают ADD-only history. Paper: base Mem0 сильнее graph на single/multi-hop; graph ≈2% overall headline и выигрывает не во всех категориях. | Paper algorithm доверяет LLM ADD/UPDATE/DELETE и физически заменяет/удаляет facts. Поздняя ADD-only документация — vendor-reported design, не независимое safety measurement. Vector+graph+SQL сложнее Git corpus. | **Взять ADD-only как candidate policy и signal separation. Не брать продукт/three-store stack без локального прогона.** |
| **LangMem** [17] | Schema-shaped extraction, hot-path tools, background manager, pluggable store. | LLM parallel-tool CRUD; updates default on, deletes configurable; нет обязательного provenance, valid-time, explicit supersedes или Git owner. LangGraph-specific integration. | **API inspiration, не memory architecture.** Проигрывает нашему evidence/version contract. |
| **Coding-memory pilot Stompy** [18] | Единственный найденный близкий domain pilot сравнил MCP memory, identical Markdown и no-memory на coding tasks; направление — memory снижает exploration сложных задач. | 9 runs, 1 model, 1 own codebase, own system, same human reviewer, raw/reproduction artifacts не опубликованы. File arm дал лучший aggregate quality; простая задача была быстрее без memory. | **Только falsifier:** мерить end-to-end exploration и иметь file control; не использовать проценты как forecast. |

## 5. Инварианты общей памяти

Независимо от выбранной развилки:

1. **Общая форма, не общий центральный corpus.** Каждый проект владеет `<project>/docs/kb/`;
   все роли получают один protocol. Cross-project read требует отдельной authority. Это сохраняет
   решение #412 и не возвращает центральную вторую копию [5].
2. **Canonical = Git text/evidence.** SQLite/FTS/vector/adjacency — rebuildable projections с
   source path, blob/head и visible freshness; отсутствие в stale projection не доказывает
   отсутствие факта [4][5].
3. **Hot/warm/cold:** hot — README topic map; warm — `Установлено/Отвергнуто` релевантных тем;
   cold — linked `docs/tasks` evidence. Не инжектировать все 283 573 Б topic bodies.
4. **Новая информация append-only.** LLM может atomize, summarize и предложить связи, но existing
   claim меняет status только explicit operation с evidence. Никакого last-write-wins.
5. **Semantic similarity не authority по safety policy.** Она может вернуть candidate topic/link/fact. Current,
   disputed и superseded определяет stable identity + явное решение.
6. **Prompt меняется последним.** Сначала direct live workflow работает из настоящего agent
   contour, затем `build_system_prompt` доказывает доставку всем нужным roles. Мёртвая ссылка в
   общем prompt ломает все проекты [3].
7. **Никакой миграции 20 502 records.** 19 773 из них — raw resources, не conclusions. Новый
   fact shape сначала доказывает пользу на ≥10 локальных вопросах; затем максимум forward-only
   facts и выбранный hot subset.

## 6. Версионирование фактов

### Хватает ли ручного `ОТОЗВАНО`

| Требование | Ручной Markdown сейчас | Вердикт |
|---|---|---|
| Не стереть старую дорогу | Старая строка остаётся; Git хранит diff/author/time. | **Хватает.** |
| Показать человеку причину | Маркер требует date/task/reason; `Отвергнуто` хранит evidence. | **Хватает при соблюдении prompt.** |
| Ответить `что current` без толкования prose | Status не типизирован; более новая строка может жить в другой теме. | **Не хватает.** |
| Ответить `что было верно на T` | Git commit-time ≠ valid-time; `ОТОЗВАНО` не задаёт interval. | **Не хватает.** |
| Сохранить два поддержанных conflicting claims | Нет `disputed` identity и связи между claims. | **Не хватает.** |
| Не дать unrelated finding снять current fact | Нет same-key/explicit-supersedes enforcement. | **Не хватает.** |

### Минимум, если пользователь выбирает machine-versioning

Для **новых** volatile/decision facts, без bulk backfill:

```text
fact_id, project_id, topic, fact_key, claim,
status = current | historical | rejected | disputed,
valid_from, valid_to, observed_at, recorded_at,
supersedes[], disputed_by[], evidence[], canonical_head
```

- `historical` означает «было верно, позже перестало»; `rejected` — «неверно/закрытая дорога».
- TTL/`refresh_after` создаёт `stale-needs-validation`, но ничего не удаляет.
- Same-key overlapping value без `supersedes` или `disputed` fail-closed.
- Human Markdown остаётся entrypoint; record ссылается на точную строку/commit, а не заменяет её.
- Existing `app/ia/knowledge.py` уже кодирует большую часть state machine [3]. Выбор — принять
  authoring/schema cost, а не написать ещё одну схему.

### Риск A-MEM-style auto-rewrite

Риск **высокий и асимметричный**. Ошибочная ссылка добавляет шум; ошибочная перезапись меняет то,
что все следующие агенты считают прошлой истиной. В A-MEM paper старая note заменяется evolved
note [6]. В production repo поле `evolution_history` объявлено, но `update_neighbor` присваивает
`notetmp.tags/context` и кладёт объект обратно без append history; Chroma representation обновляется
только поздним consolidation [7]. Graphiti показывает другой causal mechanism, но тот же опасный
outcome: unrelated fact становится retired [12]. Это corroboration цены false retirement, а не
доказательство, что обе системы ломаются одинаково.

Поэтому допустимый auto-path:

```text
new evidence -> LLM candidate {atomic claims, link suggestions, possible conflict}
             -> deterministic validator + explicit author decision
             -> append new record/event
             -> old record retained with status edge
```

Недопустимый path: `nearest neighbors -> LLM says update -> overwrite old metadata/current`.

## 7. Связи между темами

Текущий literal graph практически пуст: 2 ссылки, обе одна и та же пара [2]. Но это не аргумент
за Neo4j. Для 22 тем сначала нужен более дешёвый representation:

- связь живёт рядом с atomic fact: `depends_on`, `explains`, `contradicts`, `supersedes`,
  `evidence_for`, `related` + target `topic#fact-anchor`;
- human Markdown показывает link прямо в строке факта, не вводя пятый обязательный section;
- backlinks генерируются детерминированно из ссылок; они не canonical;
- LLM/embedding предлагает candidates только в review artifact; принятую связь пишет человек
  или validated promotion;
- retrieval сначала находит seed fact exact/keyword, затем раскрывает максимум один hop в том же
  token budget. Unbounded traversal запрещён.

Graph DB становится кандидатом только если ≥10 frozen multi-hop вопросов показывают, что explicit
file links дают пользу, а plain adjacency перестаёт помещаться/обслуживаться. GraphRAG survey сам
разделяет graph construction и retrieval: наличие графа не гарантирует качество [10].

## 8. Пользовательский гейт на тулы

| Agent-facing действие | То же без тула | Длина/сложность без тула | Решение |
|---|---|---|---|
| `knowledge(query text)` | Сырой `rg` короче, но не эквивалентен typed/projection filters, `as_of` и head-aware results. Полный эквивалент потребовал бы parser/query code. | Для простого lookup 1–3 команды; для typed semantics — программа. | **Удаление не доказано.** Оставить current path отдельным control arm; после A/B либо сохранить узкий read contract, либо убрать generic query. |
| `search_memory(query)` | Тот же iterative `rg`, который Amazon использует как treatment. | Коротко; иногда больше model turns, что должен решить A/B. | **Не предлагать как новый фундамент.** Существующий compatibility callable не удалять без отдельного решения пользователя. |
| Автоматические neighbor links | Прочитать явные links в найденной строке; `rg -n '<topic>.md' docs/kb`. | 1 короткая команда. | **Tool не нужен.** |
| Текущий ручной append в topic | `apply_patch` одной строки + source link; при новой теме README. | Коротко. | **Generic mutation tool не нужен для Markdown-only branch.** |
| **`kb_promote` в typed branch** | Агенту пришлось бы написать Python для stable ID, schema, evidence resolution, same-key conflict, CAS/head, event append, status transition и delivery receipt. Ручная запись нескольких JSON даёт half-commit. | Большой и correctness-critical Python; неочевидные invariants. | **Проходит гейт.** Узкий typed command/API с явными аргументами; существующая state machine внутри. Не generic `operation+payload`. |
| **`kb_as_of(topic, fact_key, T)` в typed branch** | Найти все records, пройти supersedes/disputed edges, отсортировать valid-time отдельно от recorded-time, проверить evidence/head. | Нужен parser/маленькая программа; `git log` сам по себе отвечает на другой time axis. | **Проходит гейт только после появления typed facts.** До этого не создавать. |

Таким образом, минимальная развилка имеет **ноль новых MCP tools**. Typed-развилка допускает два
узких operations, но сначала должна доказать adoption на forward-only pilot. Судьба agent-facing
`knowledge` — пользовательская развилка после control-arm A/B: сохранить его read semantics под
узким контрактом или убрать; opaque multi-operation wrapper не является обязательной частью ни
одной развилки.

## 9. Судьба 808-МБ projection

### Что числа говорят

- 96.44% records — raw `resource`; 0 promoted facts [1]. Это индекс файлов, а не память выводов.
- За 7 дней прямое чтение KB использовали 1 709 раз, два indexed entrypoints вместе 295 раз [1].
- Curated human layer текущего worktree — 283 573 Б / 22 topics [2]. Сравнивать эти bytes с
  808 МБ как «коэффициент раздутия» нельзя: corpora и storage formats разные.

### Что числа не говорят

- 39/256 calls не измеряют unique answers, task success или avoided exploration.
- Толстый `CHANGELOG` в выдаче доказывает defective ranking/dedup для common queries, но не
  отсутствие semantic wins на paraphrases.
- 808 МБ rebuildable не означает 808 МБ valuable и не означает 808 МБ safe-to-delete прямо сейчас.

### Гейт судьбы

1. **Сейчас:** projection не canonical, не обязательна в prompt и не получает новую migration.
   Research-only task ничего не удаляет.
2. **Frozen comparison:** 18 immutable rows #256 + 12 new rows = **n=30**: exact, common-word
   paraphrase, current, rejected и cross-topic. Gold до первого запуска фиксирует current source
   path+HEAD, required literal fact anchors и stale/forbidden anchors; для cross-topic — все
   required fact IDs/anchors. Arms при одинаковом top-k/context budget: agentic `rg`; current
   `knowledge(query)`; current `search_memory`; project-local FTS; FTS+vector;
   FTS+explicit one-hop links. Results collapse по current canonical path/head, не по commits.
3. **Per-row pass:** все required anchors присутствуют в bounded result, canonical path/head
   совпадает, stale/forbidden anchors отсутствуют. Project isolation — hard gate, не score.
4. **Vector удалить:** `FTS+vector` имеет **0 unique passes** против FTS на 30 rows и не улучшает
   end-to-end success ни в одном из трёх повторов на complex-task subset. При любой утечке/stale
   regression удаление также не одобряется: сначала чинится эксперимент/изоляция.
5. **Vector оставить в урезанном виде:** `FTS+vector` даёт **≥3 unique passes (≥10% corpus),
   0 rows broken vs FTS**, те же rescued rows повторяются на втором independently frozen set,
   stale/isolation hard gates = 0, context chars ≤ FTS budget. Тогда rebuild only curated
   project-local topics/typed facts + explicitly linked cold evidence; 20 502 records не мигрируют.
6. **Иной результат:** `INCONCLUSIVE`; snapshot read-only максимум на один decision interval,
   prompt от него не зависит, corpus расширяется. Порог задан до запуска: один случайный rescue
   не покупает постоянный 808-МБ/operations layer.

Условная рекомендация по текущим данным: **проверить урезание/удаление по этому гейту**. Оставить,
урезать или снести — решение пользователя после результатов, не вывод #417.

## 10. Как встроить во всех агентов и не сломать все проекты

`docs/kb` уже физически попадает в каждый worktree. Общность достигается protocol delivery:

1. Один base-level availability invariant доходит до **каждой роли, включая reducer**: canonical
   находится в project-local `docs/kb`, cross-project default denied. Один operational owner
   `modules/memory-search.md`, без копий в decision-role files.
2. Во всех ролях, которые принимают решения (orchestrator, sub-orchestrator, worker, full-cycle),
   одинаковый read protocol: topic map → relevant current/rejected → bounded iterative search →
   linked cold evidence. Reducer имеет доступ к тем же project files, но не обязан читать их:
   его контракт запрещает интерпретацию/отбор; принудительный memory gate там меняет роль и жжёт
   контекст без consumer.
3. Delivery check перечисляет полный live matrix `(registered project, pipeline, role,
   prompt_overlay generation)`, а не только default roles. Для каждой строки он строит именно тот
   final prompt, который получает fresh agent; resumed native sessions отдельно доказывают новый
   generation/reconnect. Current repository имеет один `pipelines/default/pipeline.yaml`, но gate
   обязан fail-closed на неизвестном project override. Reducer получает availability/isolation
   anchors, но не mandatory interpretation step. Availability тула не считается delivery.
4. Любая новая command/API сначала отвечает успешно из реального agent contour. Только затем
   prompt начинает её требовать. При failure fallback — files, а не stop.
5. Prompt указывает project-local owner; cross-project query разрешён только orchestrator authority
   и никогда не включён по умолчанию.
6. Старые native sessions требуют отдельной prompt-generation migration/reconnect; merge файла
   не означает, что живой agent получил правило [3][4].

Это выполняет «во всех агентах» как shared protocol, а не как одна central DB и не как
безусловный tool call в каждом ходе.

## 11. Что проверяется только прогоном

1. **Retrieval utility:** per-row oracle и vector keep/delete thresholds из §9; paper scores этого
   не отвечают. Current `knowledge` — отдельный arm, сырой `rg` не объявляется эквивалентом.
2. **End-to-end task effect:** сократились ли exploration turns, cache-read/tokens и elapsed time,
   а не только R@5. Нужны complex и trivial negative-control tasks; Stompy pilot показывает, что
   memory может вредить простым задачам [18].
3. **Link value:** explicit one-hop против no-link на multi-hop questions; false/irrelevant expansion.
4. **Vector marginal value:** unique correct answers vector arm после path/head dedup и при равном
   context budget.
5. **Authoring adoption:** сколько research реально получает atomic fact/link и evidence без
   принуждения; время исправления rejected promotion.
6. **False supersession:** 12 write scenarios #256; допустимый canonical result = 0 false retirements.
7. **Runtime diversity:** Claude/Codex/Grok по одному и тому же protocol; Amazon/Search-R1 не
   доказывают transfer.
8. **Prompt rollout:** complete live `(project,pipeline,role,overlay)` matrix для fresh и resumed
   agents; missing/unknown combination fail-closed.
9. **Projection economics:** bytes, rebuild time, peak RSS и freshness debt curated-only FTS/vector.
10. **As-of semantics:** valid-time answers с unknown dates, disputed facts и later corrections.
11. **Project isolation:** positive case на известном fact своего project; negative cases на тот же
    fact из другого project, подменённый `project_id`, `cross_project=false`, worker с
    `cross_project=true` и project-specific tool visibility. Все negative cases обязаны вернуть
    denial/0 foreign records; пустой corpus не является положительным control.

До этого прогона нельзя мигрировать ни 20 502 records, ни 764 ранее extracted facts. Для trial
достаточны scratch representations и forward-only новые facts.

## 12. Архитектурные развилки с ценой

Ниже три **невыбранные** альтернативы. Это estimates для выбора направления, не Phase 2 plan и не elapsed measurements. Диапазон основан
на количестве затрагиваемых seams и на прежней оценке полного locality/cutover #412 в 17–30
engineer-days [5].

### A — File-first federation, без новых tools

**Строится:** current Markdown contract; explicit links в fact lines; deterministic backlink/FTS
projection; agentic `rg` protocol; opaque mutation-часть generic `knowledge` не используется.
Read-path решается control-arm A/B: проиграл → уходит из prompt/tool surface после delivery audit;
выиграл → сохраняется его read semantics под узким явным query contract. Vector решается тем же
предзарегистрированным гейтом.

- Цена реализации: **3–6 engineer-days** + **2–4 days** на frozen retrieval/task eval.
- Постоянная цена: Git files + небольшой FTS/backlink rebuild; больше model turns на трудных
  paraphrase queries.
- Цена ошибки: read-side false negative → повторное исследование; write-side manual false/stale
  promotion → плохой canonical факт читают все следующие агенты. Git делает ошибку обратимой, но
  не предотвращает её; A требует evidence/date lint и обычный review на изменённые fact lines.
- Что не получает пользователь: reliable `as_of`, typed dispute/supersession, machine CAS.

### B — Typed, auditable facts поверх Markdown; lexical retrieval first

**Строится:** A + forward-only records, stable `fact_key`, explicit version states, reuse internal
state machine, узкие `kb_promote`/`kb_as_of`, merge delivery receipts. Existing 20 502 не мигрируют.

- Цена реализации: **8–14 engineer-days** + **3–5 days** на write/read/adoption eval.
- Постоянная цена: schema maintenance, author repair on conflicts, projection generation checks.
- Цена ошибки: wrong `fact_key` может оставить два current facts или смешать разные assertions;
  fail-closed validator снижает blast radius, но authoring friction может снова дать пустой corpus.
- Что покупается: deterministic current/rejected/disputed/as-of и audit trail.

### C — Typed facts + learned vector/graph projection

**Строится:** B + vector candidates, LLM link suggestions, bounded graph expansion и ranking.
Canonical authority остаётся B.

- Цена реализации: **14–24 engineer-days** + **5–8 days** на multi-runtime eval/operations.
- Постоянная цена: embeddings/model churn, rebuild/RSS/storage, freshness and quality telemetry.
- Цена ошибки: false links/stale rank массово подают нерелевантное или устаревшее всем agents;
  если кто-то нарушит derived-only boundary, появляется риск false supersession/data loss.
- Выбирать только если A/B показывает unique multi-hop/paraphrase wins, которых A/B не дают.

### Цена неправильного выбора

- Выбрать A при реальной semantic need → повторные исследования и лишние tool turns, но откат
  дешёвый.
- Выбрать B без adoption → второй пустой structured corpus и мёртвые tools; это текущий failure
  class `knowledge`.
- Выбрать C без доказанного marginal gain → повторить 808-МБ индекс и graph invalidation risk,
  сохранив проблему поиска.

## 13. Чего мы не знаем

- Кто авторизован утверждать `supersedes` для разных классов фактов: любой research author,
  orchestrator или human-only для high-risk.
- Нужен ли machine `as_of` достаточно часто, чтобы оправдать branch B; 39 `knowledge` calls этого
  не доказывают, потому что corpus пуст и интерфейс непрозрачен.
- Достаточны ли explicit one-hop links; multi-hop gold ещё не создан.
- Сколько common-word queries реально встречается в задачах и какой у них success, а не только
  плохие top hits.
- Даёт ли vector unique recall после canonical-path/head dedup.
- Какая часть 1 709 file reads — полезное memory lookup, а какая обязательное чтение gate.
- Какой prompt footprint оптимален отдельно для Codex, Claude и Grok.
- Как сериализовать fact anchors так, чтобы human edits и line movement не ломали identity.
- Как обрабатывать факты без known valid date; #412 уже измерил много `null` metadata [5].
- Стоимость и latency curated-only embeddings на всех проектах.
- Достаточно ли repo-local FTS, или крупным проектам потребуется отдельная service projection.
- Будет ли forward-only typed corpus накапливаться быстрее, чем стареет.

## 14. Counter-evidence и ограничения

- Amazon поддерживает keyword arm, но сам фиксирует деградацию на больших документах,
  ambiguous queries и contextual nuance [8]. Поэтому «vector не нужен» пока гипотеза.
- A-MEM ablation показывает пользу evolution на их benchmark [6]. Мы не отбрасываем механизм
  исследования связей; мы запрещаем ему canonical mutation из-за отсутствия history и локального
  safety evidence [7].
- Current Mem0 vendor docs описывают ADD-only [16], что согласуется с safety direction, но не
  является независимым подтверждением; Mem0 paper документирует destructive LLM CRUD [15].
- Zep сохраняет temporal history концептуально правильно [11], но открытые production issues
  показывают, что наличие полей не гарантирует правильный read/invalidation path [12–14].
- Coding-memory pilot ближе к нашему domain, но одна реплика на cell и own-system bias делают его
  directional, не решение [18].
- Local link count — literal lower bound. Возможно, агенты уже соединяют темы reasoning'ом без
  записанных links; это проверит только task A/B.

## 15. Confidence по выводам

| Вывод | Confidence | Основание |
|---|---|---|
| `docs/kb` должен остаться canonical owner | **CONFIRMED** | Прямое решение пользователя + current project-local code/docs [1][4][5]. |
| Generic `knowledge` не доказал право быть target agent interface | **LIKELY** | Payload opaque; mutations role-mismatched; 0 facts и 39 calls, но query semantics не эквивалентны `rg` и требуют control-arm A/B [1][3]. |
| Manual `ОТОЗВАНО` сохраняет audit, но не даёт as-of semantics | **CONFIRMED** | Current format/code inspection + 449 established/rejected bullets и 2 explicit markers [2][3]. |
| A-MEM auto-rewrite не имеет достаточного safety proof для canonical | **CONFIRMED по коду A-MEM; transfer policy LIKELY** | Paper replacement semantics + production source mutation without history [6][7]; Graphiti [12] подтверждает цену false retirement, но имеет другой causal mechanism. |
| Explicit links должны предшествовать graph DB | **LIKELY** | Corpus 22 topics/2 links; GraphRAG complexity; benefit не измерен [2][10]. |
| Agentic keyword достаточно для Orchestra | **LIKELY, unmeasured locally** | Amazon primary experiment + matching file corpus mechanics; domain/model mismatch [8][18]. |
| Текущие 808 МБ можно удалить | **UNCERTAIN до A/B** | Состав/adoption плохие, marginal vector value не измерен [1]. |
| Typed branch окупится | **UNCERTAIN до adoption/task run** | State machine существует, но corpus facts пуст [1][3]. |

## 16. Affected files будущего плана

Только если пользователь выберет развилку; в #417 код не менялся.

- `pipelines/default/prompts/modules/memory-search.md`, `pipelines/default/pipeline.yaml` — common
  delivery и role boundary.
- `pipelines/default/prompts/base.md` — убрать optional generic `knowledge` только после live cutover.
- `app/mcp_stdio.py` — agent tool surface; сохранить совместимость `search_memory` до отдельного
  решения пользователя.
- `app/routes/memory.py`, `app/routes/knowledge.py` — route compatibility/deprecation.
- `app/ia/knowledge.py`, `events.py`, `projections.py`, `project_knowledge.py` — reuse typed state
  machine/project-local projection, если выбрана B/C.
- `tests/test_default_pipeline.py`, `tests/test_mcp_stdio.py`, knowledge/project-local suites —
  delivery, role isolation, no dead prompt dependency.
- `docs/kb/*.md`, optional `docs/kb/records/` — canonical facts/links only after local pilot.

## 17. Источники

1. Task #417 user-supplied measurements, 2026-08-30 — 7-day usage, 20 502-record composition,
   808-МБ projection. Приняты как вход и не перемерялись.
2. Current worktree read-only commands in §3.2 — topic bytes, literal links, section bullets,
   `ОТОЗВАНО` occurrences (Tier 1 direct measurement).
3. Current source: `pipelines/default/prompts/modules/memory-search.md`,
   `pipelines/default/pipeline.yaml`, `pipelines/default/prompts/base.md`,
   `app/mcp_stdio.py:2988-3045`, `app/routes/memory.py:1-105`,
   `app/ia/runtime.py:1480-1565`, `app/ia/knowledge.py:499-680,927-978` (Tier 2 primary code).
4. [`docs/tasks/256/research.md`](../256/research.md) and
   [`metrics.md`](../256/metrics.md) — prior frozen 18-query baseline and typed-fact design.
5. [`docs/tasks/412/research.md`](../412/research.md) — project-local owner, 764 extracted facts,
   locality/cutover cost baseline.
6. [Xu et al., A-MEM, arXiv 2502.12110 v11](https://arxiv.org/html/2502.12110) — paper,
   methodology, author benchmarks and limitations (Tier 2 primary paper).
7. [A-MEM production `memory_system.py`](https://raw.githubusercontent.com/agiresearch/A-mem/main/agentic_memory/memory_system.py)
   and [benchmark implementation](https://raw.githubusercontent.com/WujiangXu/A-mem/main/memory_layer.py)
   — in-place evolution behavior (Tier 2 primary code).
8. [Subramanian et al., “Keyword search is all you need”, AAAI 2026](https://cdn.amazon.science/df/78/e81873f9478d80b642d113acd05e/keyword-search-is-all-you-need-2.pdf)
   — author comparison, exact metric attainments and limitations (Tier 2 primary paper).
9. [Jin et al., Search-R1, arXiv 2503.09516](https://arxiv.org/html/2503.09516) — RL multi-turn
   search, author QA results (Tier 2 primary paper).
10. [Peng et al., Graph Retrieval-Augmented Generation: A Survey, arXiv 2408.08921](https://arxiv.org/html/2408.08921)
    — graph indexing/retrieval/generation taxonomy and challenges (Tier 2 survey).
11. [Rasmussen et al., Zep/Graphiti paper, arXiv 2501.13956](https://arxiv.org/html/2501.13956)
    — bitemporal graph, provenance and author benchmarks (Tier 2 primary paper).
12. [Graphiti issue #1728](https://github.com/getzep/graphiti/issues/1728) — production report:
    collateral invalidation (Tier 2 primary incident, small manual audit).
13. [Graphiti issue #1275](https://github.com/getzep/graphiti/issues/1275) — O(n) resolution and
    silent dropped episodes (Tier 2 primary incident).
14. [Graphiti issue #1661](https://github.com/getzep/graphiti/issues/1661) — stored
    `reference_time` absent from read paths (Tier 2 primary incident).
15. [Chhablani et al., Mem0 paper, arXiv 2504.19413](https://arxiv.org/html/2504.19413) — LLM
    CRUD, Mem0/Mem0g evaluation (Tier 2 primary paper).
16. [Current Mem0 evaluation/architecture docs](https://docs.mem0.ai/core-concepts/memory-evaluation)
    — later ADD-only and multi-signal design (Tier 2 vendor primary docs; not independent).
17. [LangMem repository](https://github.com/langchain-ai/langmem),
    [semantic memory guide](https://langchain-ai.github.io/langmem/guides/extract_semantic_memories/),
    [extraction source](https://github.com/langchain-ai/langmem/blob/main/src/langmem/knowledge/extraction.py)
    — agent CRUD and storage contract (Tier 2 primary docs/code).
18. [Sandelin, coding-memory pilot, February 2026](https://www.stompy.ai/stompy-memory-benchmark-report.pdf)
    — 9-run own-system pilot; directional only, no published raw artifacts (Tier 4 single
    self-authored report).

## 18. Review route inputs

- Artifact/consumers: `docs/tasks/417/research.md`; future shared prompts, every decision-making
  agent, project-local KB owners and rebuildable projections.
- Author runtime: Codex current session; exact model identifier is not exposed in repository
  metadata used by this research.
- AC: required approach table; versioning; links; 808-МБ projection; `knowledge` fate under
  no-tool gate; 2–3 priced branches; unknowns/run-only section; KB topic; no code.
- Mechanical checks: required headings/phrases, numbered sources, local command outputs,
  link/source validation, `git diff --check` and clean committed tree.
- Risk floor: shared prompt/runtime/data-governance architecture, no independent executable oracle.
  Canonical route would be Sol, but auxiliary Sol was not authorized; one fresh Luna completeness/
  falsification pass is the permitted route.

### Review outcome

Luna, 2/2 разрешённых prose rounds: round 2 подтвердил восемь исправлений из round 1 и вернул
`Needs work` из-за одной новой коллизии — Alternative A безусловно удаляла `knowledge` даже при
его победе в control-arm A/B. Finding принят: §12.A теперь сохраняет выигравший read semantics под
узким contract и удаляет read-path только при проигрыше. Третий round запрещён ceiling, поэтому
`APPROVED` не заявляется; механическая проверка после исправления сопоставляет §8, §9 и §12.A.
Полный artifact: `docs/tasks/417/codex-review-research.md`.
