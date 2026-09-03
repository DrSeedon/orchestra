# #288 — даст ли OpenSpec измеримую пользу Orchestra

Дата исследования: 2026-08-16. Фаза: только research. Версия OpenSpec: `v1.9.0`,
upstream `main` `2826b8889e5223a9a8095d4428b60b56597e1020`. Код, runtime, конфиги и промпты
Orchestra не менялись. Полный машинно-проверяемый срез чисел и source manifest — в
[`evidence.json`](evidence.json); правила реконструкции были зафиксированы до неё в
[`prereg.md`](prereg.md).

## Вердикт

**SLICE — не внедрять OpenSpec как framework и не ставить CLI; проверить только заимствованную
идею короткой change-capsule/delta в слепом read-only pilot.**

Full adoption без удаления нынешних owners создаст в Orchestra второй writable слой для intent,
задач, фаз и архива. На завершённой #214 ретроспективная реконструкция OpenSpec породила 5 активных
файлов / 8 448 байт (≈2 112 tokens), после archive — 6 сохраняемых файлов / 11 476 байт
(≈2 869 tokens). Она повторила 13 из 14 выбранных несущих фактов в 55 размещениях и дала 42
внутрипакетных повтора; фактическое доказательство `536 passed` и результаты мутаций не перенесла
[M1]. Ноль фактов сверх tracker+report здесь **истинен по построению**, потому что bundle был
реконструирован из этого же корпуса; это duplication audit, не causal test prospective value.

При этом узкая идея полезна как проверяемая гипотеза: на границе runtime change передать не весь
OpenSpec-корпус и не session memory, а ≤2 KiB производной capsule с observable delta, non-goals,
точными AC и ссылками на владельцев. Пока измерения не пройдены, даже этот slice не считается
пользой. **FULL — нет; ADAPTER — нет сейчас; SLICE — pilot; при провале pilot → REJECT.**

Уверенность: **LIKELY** для выбора SLICE и отказа от FULL — primary docs + прямой локальный замер,
но нет A/B на handoff и нет contemporaneous OpenSpec change. **CONFIRMED условно** только
структурное утверждение: если оставить нынешние normative owners и добавить canonical OpenSpec,
получатся два writable владельца; actual drift в Orchestra не измерялся.

## Вопрос, baseline и гипотезы

**Контекст:** личная/малокомандная Orchestra, где людей мало, но одновременно работают многие
агенты в реальных worktree с Task Manager, трёхфазными gates, RED-oracles, merge/recovery и
Claude/Codex/Grok runtime.

**Change under test:** сделать OpenSpec полностью или частично владельцем product intent и change
artifacts.

**Baseline:** Task Manager + `docs/tasks/<id>/{research,plan,codex-review-*,report}` + pipeline gates
+ immutable RED tests + git worktree/squash merge + отдельные CLAUDE/pipeline policy, personal
memory и DB-backed runtime handoff [M2][M3].

**Решающий outcome:** меньше потерянных/противоречивых требований и повторных reads после смены
runtime при ограниченном приросте context; отсутствие второго writable source of truth.

1. **H1:** full OpenSpec вреден, потому что дублирует уже принуждаемые владельцы Orchestra.
   Фальсификатор: contemporaneous OpenSpec bundle, замороженный до implementation, сохраняет
   уникальные решения/предотвращает дефект против такого же baseline либо OpenSpec полностью
   заменяет пересекающегося owner без новой точки drift.
2. **H2:** узкая delta-capsule улучшит cross-runtime handoff, потому что current transcript tail не
   выделяет canonical intent и AC. Фальсификатор: в парном pilot recall/next-action не улучшается
   или context/retrieval cost растёт выше порога.
3. **H3:** даже capsule не нужна, потому что ссылки на tracker/plan уже достаточны. Фальсификатор:
   capsule стабильно улучшает intent recall и сокращает pre-action reads без invented facts.

## 1. Что сейчас называется OpenSpec

### Идентичность и зрелость

Речь именно о **Fission-AI/OpenSpec**, npm package `@fission-ai/openspec`, а не об одноимённых
репозиториях. Owner — GitHub organization `Fission-AI`, лицензия MIT, package требует Node
`>=20.19.0` [S1][S5]. На срезе GitHub API: repo создан 2025-08-05, не archived, 65 028 stars,
4 484 forks; поле `open_issues_count=201` включает PR, UI отдельно показывал 104 issues и 97 PR
[S1][S2]. Stars — популярность, не доказательство корректности.

Последний release — stable `v1.9.0` от 2026-08-13. API вернул 44 releases от `v0.1.0`
(2025-09-06), 3 за 30 дней и 8 за 90; median gap 3.323 дня, mean 7.929, включая prerelease [S3].
Это **активный, но молодой и быстро меняющийся** инструмент: v1.9 ещё добавляет fail-loud root
resolution, scenario-loss checks и проверку archived task checkboxes; stores официально beta
[S1][S4]. Maturity для ограниченного pilot — **LIKELY**; стабильность контракта для миграции
Orchestra — **UNCERTAIN**.

### Формат и lifecycle

OpenSpec — локальный CLI и набор Markdown-инструкций для coding agents, не agent runtime, MCP,
task manager или git orchestrator. `openspec/specs/` объявлен source of truth текущего поведения;
`openspec/changes/<change>/` хранит предлагаемую модификацию [S7]. Default `spec-driven` change:

```text
.openspec.yaml
proposal.md
specs/<capability>/spec.md   # ADDED/MODIFIED/REMOVED/RENAMED requirements
design.md                    # optional по критериям
tasks.md                     # checkbox list
```

Artifact graph: `proposal → {specs, design} → tasks → implement`. Зависимости прямо названы
«enablers, not gates»: порядок помогает генерации, но не является approval/merge barrier [S7][S13].
Spec — observable contract с `Requirement`, RFC 2119 `SHALL/MUST` и Given/When/Then scenarios;
implementation details должны жить в design/tasks [S7]. Артефакты можно менять по мере работы.

Archive применяет delta к canonical `specs/` и перемещает весь change в
`changes/archive/YYYY-MM-DD-name/`; bundle не копируется, а сохраняется на новом пути. Sections
ADDED/MODIFIED/REMOVED меняют canonical requirement семантически [S7]. В v1.9
`validate --archived` проверяет, что checkbox-ы отмечены, но это не запуск тестов и не доказательство
поведения [S4].

### CLI, agent commands и hooks

Terminal CLI имеет `init/update`, `new change`, `status`, `instructions`, `validate`, `archive`,
`list/show`, schema/config/store/workset/doctor/context commands и JSON contracts для агентов [S8][S9].
Agent layer по умолчанию доставляет шесть workflow: `propose`, `explore`, `apply`, `update`, `sync`,
`archive`; expanded profile добавляет `new/continue/ff/verify/bulk-archive/onboard` [S10].

Official docs/default schema не документируют native lifecycle hooks, а открытый issue #704 сообщает,
что `on_archive` отсутствует и просит его добавить; parser source целиком на это не аудитился.
Можно вручную вызывать `validate` из pre-commit/CI, но это внешний hook владельца репозитория, не
OpenSpec enforcement [S13][S16]. `operations.apply/archive.guidance` — advisory; project context обязателен
на prompt-level, но docs прямо говорят, что ни context, ни guidance не являются enforceable check
[S12]. Значит OpenSpec не заменяет Orchestra gates, permission boundary или immutable test contract.

### Agents и конфликт путей

Official table перечисляет 30+ tools, включая Claude, Codex и OpenCode; **Grok отсутствует** [S10].
Claude получает `.claude/skills/openspec-*/SKILL.md` и `.claude/commands/opsx/*.md`; Codex — только
`.agents/skills/openspec-*/SKILL.md`, invocation `$openspec-*`, без custom prompt files. OpenSpec
управляет только `openspec-*` dirs и marker; локально изменённые managed файлы перегенерируются,
остальные обещано сохранять [S10].

У Orchestra другой проверенный маршрут: pipeline skills инжектятся в `.claude/skills` и
`.codex/skills`; tracked project skill имеет приоритет над injected copy (`app/prompting.py` main
lines 195–229) [M4]. Поэтому Claude-путь разделяет namespace с Orchestra, Codex-путь не совпадает,
а Grok compatibility не заявлена. Это не доказательство фактического double-load — его можно
доказать только runtime pilot; это **LIKELY compatibility risk**, а не confirmed incident.

Source skill blobs core-profile занимают 65 747 байт (≈16 437 tokens по `ceil(bytes/4)`); два
дерева для Claude+Codex — нижняя граница 131 494 байт (≈32 874), без Claude commands. Это storage,
не per-turn context: skills progressive-load. При вызове один core skill имеет 6 925–16 213 байт
(≈1 732–4 054 tokens), а apply-skill — 8 198 байт (≈2 050) [M5]. Optional project `context`
инжектится во **все** artifact prompts, поэтому копировать туда CLAUDE/pipeline policy нельзя [S12].

### Security boundary

OpenSpec работает локально от прав текущего пользователя, не поднимает server/listener/daemon,
читает/пишет Markdown в указанной директории [S6]. Published package имеет 9 production deps и
postinstall; текущий postinstall только печатает hint, не делает network/file/shell action [S5][S6].
Но boundary шире одного binary:

- telemetry включена при unset, шлёт command name/version/random UUID; отключается
  `OPENSPEC_TELEMETRY=0`/DNT и выключена в CI [S6];
- `openspec update` делает npm version check, а с явным согласием может выполнить global
  `npm install -g @fission-ai/openspec@latest`; security fixes только в latest [S6];
- `init/update/archive` пишут, обновляют и перемещают project files; opt-in Copilot cloud setup
  также создаёт GitHub Actions workflow [S8][S10];
- generated skills являются prompt supply chain: сам OpenSpec не исполняет реализацию, но выбранный
  agent затем запускает code/tests со своими — в Orchestra широкими — правами.

Безопасная проба поэтому не должна запускать `npm install -g ...@latest`, `openspec init/update` или
`archive` в рабочем repo. Если когда-либо тестировать CLI — exact version/digest, отдельный scratch
clone, telemetry off, diff всех generated files.

## 2. 1:1 ownership-overlap mapping с Orchestra

| OpenSpec surface | Текущий owner Orchestra | Класс owner | Установленное отношение |
|---|---|---|---|
| `proposal.md` | Task Manager description + approved research/plan | writable normative + historical evidence | semantic overlap; drift пока лишь потенциальный |
| delta `specs/**/spec.md` | plan AC + committed immutable RED test | normative + enforced executable | useful plain-language complement, но второй normative owner без явной иерархии |
| canonical `openspec/specs/` | code/tests + report | enforced behavior + historical evidence | новый writable normative owner; конфликт неизбежен только если старый нормативный текст не удалить/не сделать derived |
| `design.md` | research risks + approved plan approach | evidence + writable normative | semantic overlap; actual drift не измерялся |
| `tasks.md` checkbox | Task Manager status + plan tickets/blocked-by/AC/Test | enforced lifecycle + normative | duplicate и слабее: нет RED commit, failing assertion и executor contract |
| change folder | `docs/tasks/<id>/` + task row | namespace + historical record | duplicate package, не lifecycle authority |
| artifact dependencies | Phase 1/2 approval gates | enforced transition | конфликт семантики: OpenSpec dependencies — enablers, gates Orchestra блокируют переход |
| `/opsx:verify`, `validate` | exact tests + Codex review + mutation evidence | executable enforcement + derived evidence | complement как lint/agent assessment, не replacement |
| archive | task `done` + report + squash merge | enforced lifecycle + historical record | второй transition; отдельно мутирует canonical specs и перемещает bundle |
| branch convention | auto-created worker branch/worktree | enforced isolation | не замена: OpenSpec не branch/commit/push/pull [S11][M6] |
| config `context/rules` | CLAUDE/AGENTS + pipeline role/modules | writable normative policy | потенциальный duplicate; копия будет инжектиться во все artifact prompts |
| generated skills/commands | Orchestra native pipeline skills | managed delivery | overlapping namespace/разные roots; runtime double-load не измерен |
| archived change knowledge | report, Codex artifacts, git history | historical evidence | duplicate history; OpenSpec не захватывает raw measurements/test logs автоматически |
| project/user/session memory | CLAUDE, personal memory, SQLite/logs/runtime handoff | policy/lesson/enforced live state | не тот объект: spec не должен становиться authority для policy, lessons или live state |

Текущий full-cycle контракт имеет три строгих phases и два approval gates, обязательные research и
review artifacts, vertical tickets, committed failing test, immutable oracle и exact regression
commands (`pipelines/default/prompts/roles/full-cycle.md` main lines 1–169) [M2]. OpenSpec может
записать похожий результат, но не принуждает этот contract. Git-boundary тоже различается:
OpenSpec говорит «всё ниже — convention, not enforcement» и «one change, one owner»; Orchestra
создаёт worktree/branch и принимает squash merge серверно [S11][M6].

`CLAUDE.md`/pipeline policy и personal memory не являются product spec: первое задаёт способ работы,
второе хранит переносимый урок конкретного агента. Перенос в OpenSpec смешает behavior с policy и
создаст ещё один owner. Единственная потенциально новая роль OpenSpec — долговечный human-readable
слой **публичного observable product behavior**; в личной Orchestra его ценность надо сначала
доказать, потому что executable tests и report уже покрывают этот слой.

## 3. Реконструкция завершённой #214

Выбрана task #214: status `done`, commit `1e6a817`, 12 файлов, +1 152/−26. Она удобна тем, что
исходная tracker-постановка выросла в ходе implementation: model-aware effort дополнился безопасным
next-turn reconciliation, stable manifest reads и fail-closed invalid level [M1][M7].

По default schema вручную реконструированы ровно те файлы, которые создал бы OpenSpec:

| Состояние | Файлы | bytes | ≈tokens (`ceil(bytes/4)`) | Доля текущих tracked docs #214 |
|---|---:|---:|---:|---:|
| active change | 5 | 8 448 | 2 112 | 18.1% |
| после archive: bundle + canonical spec | 6 | 11 476 | 2 869 | 24.6% |
| текущие `docs/tasks/214/*` | 3 | 46 557 | 11 640 | baseline |

Текущие 46 557 байт — report + 2 Codex reviews; Task Manager row, code, tests и git history в число
не входят. Поэтому проценты — прирост tracked documentation, а не total project storage и не
автоматически prompt billing. Файлы реконструкции лежат в
[`reconstruction-214/`](reconstruction-214/) и доступны для построчной проверки [M1].

Prereg зафиксировал правило `explicit fact only`; implication не считается. Но он **не содержал и
не хешировал сам список 14 фактов**: atomic boundaries можно проверить в `evidence.json`, однако
нельзя независимо доказать, что их заморозили до результата. Результат descriptive audit:

- current report содержит 14/14 load-bearing facts; tracker — 3/14;
- OpenSpec surfaces повторили 13/14 фактов в 55 явных placements;
- после первого размещения каждого из 13 фактов осталось 42 внутренних повтора;
- unique facts относительно tracker+report: **0 по построению**, потому что reconstruction брала
  именно эти sources;
- пропущен 1 факт: реальные `536 passed` и exact mutation outcomes. Checkbox «run tests» — намерение,
  а не evidence.

Следовательно, замер **подтверждает размер и семантическое повторение выбранного bundle**, но не
проверяет prospective unique capture и не является causal evidence за FULL/против FULL. Чтобы
проверить уникальную ценность, OpenSpec bundle должен быть contemporaneous и заморожен до
implementation, после чего его сравнивают с независимо возникшими code/test/report facts. Полная
fact matrix и это ограничение записаны в `evidence.json`.

## 4. Четыре режима

| Режим | Реальная выгода | Migration / drift | Context и agents | Failure/security modes | Вердикт |
|---|---|---|---|---|---|
| **FULL** | единый plain-language каталог текущего behavior; uniform commands | backfill всех capabilities; либо удалить нормативные дубли tracker/plan/report, либо жить с 2 SOT; archive конфликтует с task done/merge | +≈2.1K tokens change на #214 и ≈2K apply skill при полном чтении; Claude/Codex/OpenCode supported, Grok нет | stale spec, late archive conflict, checkbox≠test, npm/generated-prompt supply chain, agent может обойти gate | **REJECT** |
| **ADAPTER import/export** | interchange с внешней командой/tool; можно рендерить delta | bidirectional sync заводит conflict resolution; one-way export обязан быть `DERIVED` и hash-bound | on-demand; generic Markdown читают все runtimes | stale checked-in export принимают за canonical; import может ослабить AC | **не сейчас**: нет внешнего consumer |
| **SLICE: capsule/delta** | только intent handoff: маленькая observable delta + non-goals + exact AC | без backfill/archive; однонаправленно из approved owners, never edited | ≤2 KiB; plain Markdown для Claude/Codex/Grok; OpenSpec CLI не нужен | stale source hash, invented compression, capsule ошибочно используют как live state | **PILOT** |
| **REJECT** | нулевой новый owner/context | migration/drift нет | полная текущая compatibility | останутся измеренные потери общего transcript handoff | fallback при провале pilot |

Full migration могла бы быть оправдана только обратным решением: сделать `openspec/specs/` единственным
нормативным owner **и удалить/сделать производными** пересекающиеся AC/docs. Это архитектурная миграция,
а не установка CLI. Для личной Orchestra нет измеренного эффекта, который оправдывает такой риск.

Adapter имеет смысл лишь при реальном внешнем consumer OpenSpec. Импорт↔экспорт без владельца —
самостоятельная distributed consistency задача; one-way export безопаснее, но сейчас создаёт данные,
которые никто не потребляет.

## 5. Cross-runtime handoff: что OpenSpec может и не может нести

OpenSpec **может концептуально быть canonical product intent**, потому что plain Markdown читается
разными agents и отделяет current behavior от proposed delta. Но он **не должен быть authority для
Orchestra chat/session/native runtime state**. Markdown физически способен сериализовать такой state;
OpenSpec не даёт нужных lifecycle, atomicity, replay, native-protocol fidelity и security semantics.
Исследование #174 и текущий код устанавливают границу:

- provider-native transcripts не переносят скрытое reasoning, provider events и полную tool protocol
  semantics; устойчивый объект — provider-neutral handoff [M3];
- current `runtime_handoff` хранится в session state, на следующем send оборачивается как
  `<prior-conversation>` и очищается только после успешного `backend.send`
  (`app/session.py` main 1167–1191) [M3];
- builder берёт bounded recent semantic text из DB logs (`app/session.py` main 2473–2505), а #174
  измерил на длинной сессии retention лишь 24/1 284 semantic rows (1.87%) и 0.86% characters [M3].

Отсюда разделение владельцев:

```text
product intent/delta  → approved task/plan/test owners; optional derived capsule
session/live state    → SQLite + queue + runtime_handoff + logs
native runtime state  → provider session/transcript; не переносить через OpenSpec
policy/agent behavior → pipeline prompts / CLAUDE
reusable lessons      → personal/project memory
```

В будущем canonical OpenSpec intent возможен только для ограниченного класса долговечных публичных
contracts и только после удаления другого нормативного owner. Для pilot capsule остаётся
`DERIVED`, содержит source paths+commit/hash; она может ссылаться на opaque live-state id для
traceability, но не владеет им и не replay-ит. Скрытое reasoning, transcript, tool results, queue
status, current turn и native session state остаются в runtime owners. Whole OpenSpec corpus в
handoff не нужен.

## 6. Counter-evidence и вредные края

1. **Parallel changes не изолируют смысл.** Official team docs сами признают canonical-spec conflict
   при двух изменениях одного requirement. Дополнительно open issue #1387 **сообщает** о позднем
   конфликте/тихом overwrite после rebase из-за отсутствия base snapshot и о невстроенном
   pre-archive overlap detection; этот incident здесь не воспроизводился [S11][S14]. Для многих
   Orchestra worktrees это правдоподобный load-bearing риск, не confirmed local failure.
2. **Stale specs исторически случались.** Закрытый report #1212 для v1.2/v1.3 описывает успешный
   propose/ff→apply→archive без delta. Текущий schema и v1.9 safety закрывают названный fast-path;
   это не current blocker, а свидетельство зависимости SOT от версии generated workflow
   [S4][S13][S15].
3. **Ceremony измерима.** #214 дала +5 active files и +18.1% к уже существующим tracked task docs;
   retrospective bundle повторил 13 выбранных facts, но prospective unique capture этим не
   измерялась [M1]. Сложные задачи могут получить больше capability deltas.
4. **Spec-code drift не исчезает от формата.** `verify` — optional agent workflow, archive validation
   проверяет checkboxes/format, не production end effect. Хорошо сформированный SHALL может быть
   неверным, а ambiguity может просто переехать в scenario.
5. **Формат не принуждает Orchestra AC.** Default tasks требуют verifiable steps, но не committed RED,
   exact failing assertion, immutable oracle, clean executor diff или crash recovery [S13][M2].
6. **Agent/worktree conflicts откладываются.** Разные change folders не конфликтуют, canonical
   `specs/` конфликтует при archive; OpenSpec не знает Task Manager, blocked-by, worker ownership или
   squash merge [S11].
7. **Prompt/context overhead имеет два слоя.** Artifact bundle + invoked workflow skill; optional
   config context повторяется во всех artifact prompts. Stored two-tree guidance не равно per-turn
   bill, но копирование CLAUDE rules туда гарантированно удваивает текст [S10][S12][M5].
8. **Supply-chain boundary не нулевая.** Postinstall сейчас benign, но CLI/latest deps, telemetry,
   self-update и managed prompt files остаются новым trusted input [S5][S6].
9. **Совместимость неполна.** OpenSpec документирует Claude/Codex/OpenCode, но не Grok; путь Codex
   `.agents` расходится с native Orchestra `.codex` [S10][M4].

Counter-evidence **в пользу** OpenSpec тоже есть: plain-language delta даёт reviewer intent до code;
archive сохраняет why/design/tasks; JSON contract fail-loud; v1.9 активно закрывает scenario/root
ошибки; project config различает required context и advisory guidance [S4][S7][S9][S12]. Именно эти
плюсы делают slice достойным измерения, но не отменяют дублирование.

## 7. Близкий современный подход: GitHub Spec Kit

Spec Kit — более тяжёлый сосед, не лучший replacement. Его core — `Spec → Plan → Tasks → Implement`,
а полный путь добавляет constitution, clarify, checklist, analyze и converge; 35 integrations
[S17][S18]. `analyze` read-only сверяет spec/plan/tasks, `converge` сравнивает code с artifacts и
может дописать новые tasks [S18]. Это сильнее OpenSpec как явная cross-artifact проверка, но ещё
больше дублирует research/plan/tickets/review Orchestra и остаётся agent assessment.

Полезное counter-example из собственных docs Spec Kit: команда перестала размножать constitution
по templates, потому что propagation дублировал single source of truth; теперь phases читают живой
owner, а templates держат pointer [S19]. Это первичное независимое подтверждение архитектурного
правила для pilot: **ссылка/hash на owner, не синхронизируемая копия**.

## 8. Минимальный безопасный falsifiable pilot

Pilot не устанавливает OpenSpec и не меняет runtime. Он проверяет только H2 против H3.

### Capsule contract

На каждый кейс одно `DERIVED — DO NOT EDIT` сообщение/файл ≤2 048 UTF-8 bytes:

1. task id, authoritative paths и exact source commit/hash;
2. 3–7 atomic observable ADDED/MODIFIED/REMOVED requirements;
3. non-goals;
4. exact AC/test commands из approved plan;
5. никаких progress/status, hidden reasoning, transcript summary, tool output, queue/session/model state.

Любое расхождение hash → fail loud, capsule не выдаётся. Owners остаются Task Manager + approved
plan/test; capsule одноразовая производная для handoff.

### Дизайн

- **До capsule authoring** выполнить замороженный chronological query и взять первые 3 eligible
  historical runtime handoff после заданного UTC cutoff. Eligibility: handoff input сохранён;
  approved plan/AC существовали до handoff и имеют commit/hash; solution commit позже; нет внешнего
  side effect. Task ids, timestamps, inclusions/exclusions и hashes зафиксировать до outputs.
- Для каждой task восстановить только handoff-time corpus. Capsule author и answer-key author не
  видят final code/report/reviews. Atomic answer key и scoring rubric хешируются до первого run.
- Создать независимые read-only стенды на pre-implementation commit через `git clone --no-local`;
  prove solution commit/object unreachable. Один и тот же target runtime/model/effort, fresh context,
  только read/search tools; output — next action, preserved AC/non-goals и нужные reads.
- Три arms: **A** — текущий provider-neutral handoff; **P** — тот же handoff + position/byte-matched
  capsule template, где task semantics заменена deterministic padding; **B** — handoff + настоящая
  capsule. P отделяет смысл от эффекта длины/структуры/позиции. Позиция capsule фиксируется заранее
  как часть production-shaped intervention.
- По 3 независимых повторения каждого arm на каждой task: **27 agent runs**. Labels и порядок
  рандомизируются; одинаковая task не попадает в один context. Это минимальный discovery-дизайн,
  который одновременно видит generation noise, task sensitivity и position/length effect; он всё
  ещё не оценивает общий population effect.
- Два независимых scorer-а не видят arm labels и получают frozen answer key плюс candidate output.
  Exact AC/path/command проверяются механически; semantic факт — бинарно по rubric. До сравнения arms
  посчитать inter-rater agreement; disagreement консервативно считается miss, а `κ < 0.8` останавливает
  pilot как scorer failure.

### Метрики и pass/fail до запуска

Primary:

1. `intent_recall = correctly preserved atomic facts / answer-key facts`;
2. `invented_or_contradictory_facts`;
3. корректность first next-action и exact AC command.

Cost:

4. read/search tool calls до первого корректного next-action;
5. input tokens; wall time записывается diagnostic, но не primary из-за общей host load;
6. capsule bytes и rough token count.

До unblind B вычислить control noise отдельно по A и P: для каждой task/metric range трёх повторов;
`noise_floor` — максимум этих control ranges. Формула и threshold заморожены заранее, B в noise не
входит. **PASS только если одновременно:** все 9 B имеют 0 invented/contradictory facts и верный exact
AC; median recall B не хуже A и P ни на одной task; на ≥2/3 tasks прирост B против **обоих** controls
≥ `max(20 percentage points, recall_noise_floor)`; median pre-action reads B ниже обоих controls
минимум на 1 и сильнее `reads_noise_floor` на ≥2/3 tasks; capsule ≤2 048 bytes и ≤750 tokenizer
tokens. Улучшение B против A, но не против P означает formatting/position effect и не подтверждает
semantic capsule. Иначе benefit не измерен → **REJECT**, не «почти получилось».

**Stop immediately:** capsule конфликтует с owner; source hash stale; agent пытается редактировать
capsule или трактует её как progress/session state; clone видит solution object; любой side effect
вне scratch; handoff-time source отсутствует и требует hindsight reconstruction; scorer agreement
ниже порога; overhead >10% total first-turn input без primary improvement. После pilot не менять
пороги и не доливать кейсы, увидев labels.

До первого run надо также закоммитить exact aggregation program: tie handling фиксировано numeric
median, любой missing/aborted run останавливает весь pilot (не заменяется новым sample), raw inputs и
JSON output хешируются. Иначе даже заранее написанная формула оставляет discretionary реализацию.

Если PASS, следующая Phase 2 может спланировать production-shadow pilot. Даже тогда это не аргумент
за OpenSpec CLI/full adoption — только за derived capsule.

## Confidence по несущим выводам

| Вывод | Confidence | Основание |
|---|---|---|
| OpenSpec identity/version/lifecycle/security surfaces описаны верно | **CONFIRMED** | official repo/docs/source/release, tier 2, открыты 2026-08-16 |
| Full adoption при сохранении current owners создаёт второго writable owner | **CONFIRMED условно** | ownership-overlap mapping; actual drift не измерялся |
| #214 bundle повторяет 13 facts / 55 placements / 42 repeats | **CONFIRMED descriptive** | explicit matrix и арифметика, tier 1 |
| #214/OpenSpec prospective unique capture равен нулю | **UNCERTAIN / не измерено** | retrospective bundle построен из comparison corpus; inventory не был pre-hashed |
| Grok не поддержан OpenSpec | **CONFIRMED как отсутствие в official list; UNCERTAIN runtime compatibility** | official list не содержит Grok, generic `.agents` не испытан |
| Capsule улучшит cross-runtime handoff | **UNCERTAIN до pilot** | механизм правдоподобен, A/B нет |
| FULL/ADAPTER сейчас хуже SLICE/REJECT | **LIKELY** | overlap + reported concurrency risk + нет consumer; benefit capsule ещё не измерен |

## Codex second opinion

Раунд 1 нашёл два blocking дефекта: retrospective reconstruction не могла измерить unique capture,
а 6-run A/B путала condition с generation/task/scorer noise. Оба приняты: causal claim снят, audit
ограничен описательными 13/55/42; pilot заменён на frozen handoff-time A/P/B design из 27 runs с
repeats, blind scoring и control noise floor. First-round dissent сохранён дословно в
[`codex-review-research-r1.md`](codex-review-research-r1.md).

Раунд 2 подтвердил исправления и дал **APPROVED FOR PHASE 1**
([`codex-review-research.md`](codex-review-research.md)). Его suggestion про aggregation code/ties/
missing runs добавлен в prereq pilot выше. Вместо хранения 1 783 396 байт rendered HTML mutable docs
S7–S12/S17–S19 переведены на raw Markdown, pinned к upstream commits; hashes и sizes остаются в
`evidence.json`. Для issue/API snapshots, которые нельзя pin к git commit, сохранены fingerprints и
утверждения намеренно квалифицированы как reported.

## Затрагиваемые файлы и риски будущей работы

Research создал только `docs/tasks/288/`. Ничего не внедрено. Если pilot будет одобрен отдельно,
его artifacts также должны жить в task-local research area; production integration, prompts,
runtime handoff, CLI install и `openspec/` остаются вне scope до следующего gate.

Offline HTML не создан: сравнительные связи полностью выражаются двумя Markdown-таблицами, а
вторая визуальная копия отчёта не добавила бы проверяемого отношения и сама увеличила бы drift.

Главные будущие риски: capsule становится writable owner; stale hash пропускается; answer key
составляется после outputs; solution history доступна стенду; transcript-only judge не видит real
reads/side effects; Grok generic skill support предполагается без прогона.

## Источники

Evidence tier: **tier 1** — выполненный локальный замер/артефакт; **tier 2** — official docs,
repository/source/API. Secondary sources для load-bearing выводов не использовались. Все URL ниже
открыты 2026-08-16.

- **[S1]** [Fission-AI/OpenSpec repository](https://github.com/Fission-AI/OpenSpec) — tier 2.
- **[S2]** [GitHub repository API](https://api.github.com/repos/Fission-AI/OpenSpec) — tier 2.
- **[S3]** [GitHub releases API](https://api.github.com/repos/Fission-AI/OpenSpec/releases?per_page=100) — tier 2.
- **[S4]** [OpenSpec v1.9.0 release](https://github.com/Fission-AI/OpenSpec/releases/tag/v1.9.0) — tier 2.
- **[S5]** [OpenSpec package.json at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/package.json) — tier 2.
- **[S6]** [OpenSpec security policy at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/SECURITY.md) — tier 2.
- **[S7]** [OpenSpec core concepts at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/docs/concepts.md) — tier 2.
- **[S8]** [OpenSpec CLI reference at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/docs/cli.md) — tier 2.
- **[S9]** [OpenSpec agent contract at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/docs/agent-contract.md) — tier 2.
- **[S10]** [OpenSpec supported tools at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/docs/supported-tools.md) — tier 2.
- **[S11]** [OpenSpec team workflow at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/docs/team-workflow.md) — tier 2.
- **[S12]** [OpenSpec customization at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/docs/customization.md) — tier 2.
- **[S13]** [Default spec-driven schema at measured SHA](https://raw.githubusercontent.com/Fission-AI/OpenSpec/2826b8889e5223a9a8095d4428b60b56597e1020/schemas/spec-driven/schema.yaml) — tier 2.
- **[S14]** [Open issue #1387: parallel drift/overlap](https://github.com/Fission-AI/OpenSpec/issues/1387) — tier 2, counter-evidence.
- **[S15]** [Closed issue #1212: stale specs fast path](https://github.com/Fission-AI/OpenSpec/issues/1212) — tier 2, historical counter-evidence.
- **[S16]** [Open issue #704: requested archive hooks](https://github.com/Fission-AI/OpenSpec/issues/704) — tier 2.
- **[S17]** [GitHub Spec Kit docs at measured SHA](https://raw.githubusercontent.com/github/spec-kit/bf88c9f9a82fa370c7a7257aa2b3cf10b457b65c/docs/index.md) — tier 2.
- **[S18]** [Spec Kit agentic SDD at measured SHA](https://raw.githubusercontent.com/github/spec-kit/bf88c9f9a82fa370c7a7257aa2b3cf10b457b65c/docs/reference/agentic-sdd.md) — tier 2.
- **[S19]** [Spec Kit upgrade/SOT rationale at measured SHA](https://raw.githubusercontent.com/github/spec-kit/bf88c9f9a82fa370c7a7257aa2b3cf10b457b65c/docs/upgrade.md) — tier 2.
- **[M1]** [`evidence.json`](evidence.json) + [`reconstruction-214/`](reconstruction-214/) — tier 1.
- **[M2]** `pipelines/default/prompts/roles/full-cycle.md@2e3d6276` — tier 2, current code.
- **[M3]** [`docs/tasks/174/research.md`](../174/research.md) + `app/session.py@2e3d6276` — tier 1/2.
- **[M4]** `app/prompting.py@2e3d6276` lines 195–229 — tier 2.
- **[M5]** GitHub tree blob-size measurement at OpenSpec SHA; exact output in `evidence.json` — tier 1.
- **[M6]** `pipelines/default/prompts/modules/orchestration.md@2e3d6276` lines 69–72 — tier 2.
- **[M7]** Orchestra MCP `task_get(214)` + [`docs/tasks/214/report.md`](../214/report.md) — tier 1.

SHA-256 и byte length exact responses для S1–S19 сохранены в `evidence.json`:
raw sources pinned к commit, mutable documentation pages — к capture hash на дату доступа.
