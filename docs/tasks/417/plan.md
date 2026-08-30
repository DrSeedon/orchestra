# #417 — план file-first памяти агентов поверх `docs/kb`

Статус: Phase 2 only. Архитектура обсуждена и одобрена; implementation не начата.
Final immutable RED commit: `88390896`. Предыдущие freezes `6b815eb9`, `609ee812`, `d4d87141`
и `f72ae207`
superseded/excluded: до plan review и до любых production изменений T1 усилили отрицательными
проверками старого `<knowledge-capability>` и stale `knowledge` в двух MCP access registries;
первая RED-причина осталась прежней.

## 1. Принятые решения и новый baseline

1. **Canonical память проекта — только Git Markdown в `<project>/docs/kb/`.** Второй canonical
   store, vector DB, graph DB и автоматическая fact migration не создаются.
2. **Semantic retrieval закрыт результатом #419 и не переоткрывается в #417.** Frozen holdout:
   vector/`knowledge(query)` unique = **0**, ordinary `rg` unique = **6**
   (E04, C01, C02, C04, C06, R02), ties = **0**, N01 empty on both arms. Числа 12/2/4 из
   прежнего пересказа отозваны: они считали непустой шум ответом. Источник:
   `main:docs/tasks/419/report.md` + `main:docs/tasks/419/raw/final_lexical.jsonl`.
3. **Векторный `current.db` уже удалён, `RAG_ENABLED=false`.** Implementation #417 не создаёт
   индекс заново и не добавляет semantic fallback.
4. **`search_memory` остаётся MCP-тулом и остаётся упомянут в prompt.** При выключенном RAG он
   честно отвечает «семантический поиск выключен» и отдаёт маршрут в `rg`; основной protocol не
   тратит обязательный вызов на заведомый fallback.
5. **Generic `knowledge` уходит с agent-facing MCP/prompt surface.** Его lexical query проиграл
   #419, typed/as-of branch не выбран, promoted fact corpus отсутствует. Внутренние модули
   `app/ia/*` этим планом не удаляются и не объявляются новым owner.
6. **LLM не переписывает и не supersede'ит canonical facts.** Он может предложить связь только в
   task artifact; canonical link появляется лишь когда exact target и approval anchor уже названы
   в одобренном плане/тикете.
7. **Rollout forward-only.** Новый формат обязателен только для новых и изменённых fact lines;
   449 legacy established/rejected bullets не переписываются пачкой.

## 2. Целевой read path: вопрос → topic → fact → evidence

```text
вопрос
  -> 1–3 отличительных literal anchors
  -> rg -l -i -F только по docs/kb/*.md
  -> rg -n -i -F внутри 1–нескольких candidate topics
  -> прочитать Установлено + Отвергнуто
  -> при необходимости пройти ОДНУ approved Markdown-связь
  -> открыть docs/tasks evidence только по ссылке из найденного fact
```

Почему два прохода: #419 показал, что «непустой `rg`» не равен ответу. E06 вернул 122 строки
шума на `test_frontend`; сначала список файлов (`-l`), затем точный поиск внутри candidate topic
не тащит сотни строк в model context.

Prompt-owned алгоритм:

1. Прочитать `docs/kb/README.md`, выбрать вероятные durable topics.
2. Выделить **1–3 отличительных поисковых якоря**: exact symbol/path/command, старое имя или
   существительное из пользовательской формулировки. Не передавать весь вопрос как один literal.
3. **Сначала искать только в `docs/kb/`**:
   `rg -l -i -F --glob '*.md' '<anchor>' docs/kb`.
4. В candidate files искать второй anchor с `rg -n -i -F`; открыть только релевантные sections.
5. `docs/tasks/` открывать только по source/evidence link из найденного fact. Если KB ничего не
   дал, разрешён отдельный targeted `rg` по tasks, но вывод не объявляется promoted memory.
6. Approved `связи:` раскрывать максимум на один переход; новый target проходит тот же literal
   filter и context budget.
7. `search_memory` остаётся compatibility-тулом и не является обязательным шагом. Это
   единственное occurrence имени тула в operational module; второе occurrence запрещено oracle.
   RAG-disabled fallback никогда не ретраится.

## 3. Lexical-friendly Markdown fact contract

Новый/изменённый fact остаётся одной bullet-строкой в существующих sections. Никакого YAML,
JSON sidecar или database row:

```markdown
- `fact:<durable-kebab-key>` — <самодостаточный claim словами будущего вопроса> ·
  искать: `<exact_symbol>`, `<old_name>`, «русский или английский синоним» ·
  связи: `depends_on` → [topic](topic.md) ·
  approved: `docs/tasks/<id>/plan.md#<ticket>` ·
  evidence: `<file:line | command + result | URL>` · <date, #task>
```

Правила:

- **Filename:** durable subsystem/decision nouns, kebab-case; не task number, session name и не
  одноразовая модель. Существующие filenames не мигрируют.
- **Fact key:** уникален в topic, стабилен при переформулировке claim; это locator, не natural
  search substitute.
- **Claim:** одна self-contained мысль без «это/он/такой» со ссылкой на предыдущую bullet.
- **`искать:`:** 1–6 literal anchors. Сохраняются exact symbol, path, command, env/config key,
  прежнее имя и хотя бы одна русская/английская формулировка, которой зададут вопрос.
- **Status:** current facts живут в `Установлено`, closed/wrong roads — в `Отвергнуто` или остаются
  на месте с `ОТОЗВАНО`; automatic overwrite/delete запрещён.
- **Evidence:** остаётся в той же строке. `искать:` без evidence и evidence без `искать:` — invalid
  для changed line.
- **Legacy:** validator получает unified diff, разрешает только paths внутри resolved project-local
  `docs/kb` root и валидирует added/modified fact lines. Unchanged legacy bullets в том же файле
  grandfathered; invalid новая строка не прячется рядом со старой. Bulk rewrite = scope violation.

`scripts/check_kb_contract.py` — repository validator, **не MCP tool**. Без него merge-gate автору
пришлось бы каждый раз писать Python для section parsing, duplicate fact keys, changed-line scope,
link target/approval checks и actionable errors; поэтому он проходит пользовательский utility test.
Обычный read/grep таким validator'ом не оборачивается.

## 4. Связи: proposal → approval → canonical one-hop

Разрешённые отношения: `depends_on`, `explains`, `contradicts`, `supersedes`, `evidence_for`,
`related`.

Write protocol:

1. LLM пишет `candidate-link` только в `docs/tasks/<id>/research.md` или plan discussion. Эта
   строка не canonical knowledge.
2. Одобренный plan/ticket содержит approval receipt: stable anchor + exact relation, source fact
   key и существующий target topic. Сам факт human approval остаётся фазовым гейтом пользователя;
   validator проверяет структуру/совпадение уже одобренного receipt, а не изображает человека.
3. Только implementation одобренного ticket добавляет `связи:` + `approved:` в fact line.
4. Validator отвергает `candidate-link` внутри `docs/kb`, unknown relation, missing/mismatched
   approval receipt, missing target, self-link, absolute target, `../` traversal и changed file
   за пределами resolved project-local KB root.
5. Read protocol раскрывает одну связь; target links рекурсивно не обходятся. Graph traversal и
   LLM-generated neighborhood отсутствуют.

Цена ошибки ограничена: неправильный accepted link добавляет irrelevant context, но не меняет
status/claim старого факта. Git review и approval anchor показывают, кто разрешил связь.

## 5. Оставшиеся пробелы: решение и цена

| Пробел | Решение Phase 2 | Что входит | Цена |
|---|---|---|---|
| Vector unique task-success | **СНЯТ / закрыт #419** | Ничего; negative scope guard запрещает vector/semantic revival. | Уже заплачено #419; #417 = 0 дней. |
| Machine `as_of` | **ОТЛОЖЕН** | Git history + `ОТОЗВАНО` остаются human path; no `fact_key` time intervals, parser, DB или `kb_as_of`. | Возврат: estimate 5–8 engineer-days на valid-time schema, parser/query, conflict cases и migration policy. Новый query прошёл бы tool utility test, потому что без него нужен код; сейчас измеренного спроса нет. Trigger: ≥3 реальные задачи, где ручная реконструкция «что было верно на T» нужна для решения, либо compliance requirement. |
| One-hop links | **ВХОДИТ, T3** | Только approved typed Markdown links, proposal stays in task artifact, one-hop read. | 2–3 engineer-days; review burden на каждую новую link и риск irrelevant context. |
| Единый Claude/Codex/Grok protocol | **ВХОДИТ, T1** | Один assembled prompt до runtime factory; delivery checks для трёх builtin factories, decision roles и resumed prompt assembly. | 2–4 engineer-days; риск stale native session/role drift, поэтому prompt delivery и reconnect checks обязательны. |

## 6. Проверка каждого tool-кандидата

| Действие | Без нового тула | Вердикт |
|---|---|---|
| Найти topic/fact | Две короткие команды `rg -l` → `rg -n`, затем обычный read. | **Новый tool запрещён.** |
| Пройти one-hop link | Открыть Markdown target из найденной строки. | **Новый tool запрещён.** |
| Добавить fact вручную | Одна `apply_patch` строка; формат уже в prompt. | **Новый write tool запрещён.** |
| Валидировать все changed facts/links перед merge | Без validator нужен объёмный parser: sections, duplicate IDs, search/evidence fields, target files, relations, approval anchors, grandfathering legacy. | **Repository CLI validator разрешён**, но не экспортируется через MCP и не участвует в retrieval. |
| Machine `as_of` | Без query нужен код для valid-time/status/supersession. | **Tool мог бы быть оправдан**, но весь feature отложен и сейчас не создаётся. |
| Generic `knowledge` | #419 сравнил его query с ordinary `rg`: unique 0 против 6; mutation branch не выбран. | **Agent-facing MCP decorator и prompt block снимаются в T1.** Internal `app/ia/*` вне scope. |
| `search_memory` | Уже существующая compatibility point с полезным disabled fallback. | **Сохраняется 1:1; не новый tool.** |

## 7. Файлы и точные seams

### T1 — read/delivery/tool surface

- `pipelines/default/prompts/base.md`: заменить `<knowledge-capability>` на короткий all-role
  invariant `Canonical project memory lives in docs/kb`; reducer получает owner, не workflow.
- `pipelines/default/prompts/modules/memory-search.md`: заменить обязательный semantic Step 2 на
  двухпроходный lexical algorithm; сохранить literal `search_memory` compatibility/fallback.
- `app/mcp_stdio.py::knowledge`: снять только `@mcp.tool()` и убрать имя из
  `READ_ONLY_MCP_TOOLS`/`REDUCER_MCP_TOOLS`; функцию/internal HTTP route не удалять.
- `app/mcp_stdio.py::search_memory`: **не менять контракт/decorator**.
- `tests/test_default_pipeline.py`: source+assembled delivery для orchestrator,
  sub-orchestrator, worker, full-cycle; reducer negative operational check.
- `tests/test_runtime_registry.py`: Claude/Codex/Grok factories получают один assembled prompt;
  Codex skill index additions не меняют memory anchors.
- `tests/test_mcp_stdio.py`: knowledge отсутствует на agent MCP surface; search_memory остаётся и
  при `RAG_ENABLED=false` возвращает actionable `rg` fallback.
- Read-only consumers under behavioral oracle: `app/runtime_registry.py::build_backend` and
  `app/manager.py::SessionManager.assemble_prompt`. Production edits там не планируются; если
  sentinel/resume test обнаружит реальный wiring defect, T1 останавливается для перепланирования,
  а не расширяет scope молча.

### T2 — lexical fact writer/validator

- `pipelines/default/prompts/modules/research-method.md`: forward-only fact-key/claim/`искать:`/
  evidence contract и запрет bulk migration.
- `scripts/check_kb_contract.py` (new): added-line Markdown validator; stdlib only; explicit CLI
  `--root` + `--diff <unified.patch>`; canonical-root containment and actionable path/line errors.
- `tests/test_kb_markdown_contract.py` (new): valid fixture, bad key shape, 0/7 anchors,
  multiline fact, wrong section, missing search/evidence, duplicate key, mixed unchanged-legacy +
  valid/invalid added line, traversal/absolute changed paths.
- `tests/test_default_pipeline.py`: write anchors reach full-cycle and do not leak mandatory write
  steps to reader-only roles.

### T3 — approved one-hop links

- `pipelines/default/prompts/modules/research-method.md`: candidate/approval/canonical link rules.
- `pipelines/default/prompts/modules/memory-search.md`: one-hop-only read rule.
- `scripts/check_kb_contract.py`: relation whitelist, target existence, approval anchor, candidate
  rejection, self-link and canonical-root containment.
- `tests/test_kb_markdown_contract.py`: real approval receipt + exact tuple, existing receipt with
  mismatched tuple, wrong/nonexistent receipt, candidate, unknown relation,
  missing/traversal/absolute target and self-link fixtures.

## 8. Что не трогать

- `docs/kb/README.md` — ownership/conflict boundary from orchestrator; entry is added outside #417.
- Existing 449 fact bullets — no bulk rewrite or migration.
- `app/ia/*`, `canonical/`, `task-current.db`, SQLite schemas — no second store cleanup/refactor.
- Vector/embedding/reranker/RRF code and dependencies — #417 does not reopen deletion work #419.
- `RAG_ENABLED` or deleted `current.db` — runtime decision already applied outside this branch.
- `search_memory` decorator, name, arguments and disabled fallback.
- Runtime-specific copies of the lexical protocol — one prompt owner only.

## 9. Rollout and compatibility

1. T1 → T2 сериализуются: behavior независим, но оба меняют `tests/test_default_pipeline.py`.
   T3 ждёт T2 validator и косвенно T1.
2. Inside T2/T3, validator behavior becomes green before the prompt starts requiring its output.
3. Inside T1, prompt stops referencing generic `knowledge` before its MCP decorator is removed;
   `search_memory` remains available throughout.
4. Prompt delivery is checked behaviorally: an assembled sentinel reaches actual Claude/Codex/Grok
   backend objects; `SessionManager.assemble_prompt` rebuilds the lexical protocol on resumed rows
   while preserving a full operator prompt byte-for-byte.
   Operator full-prompt overrides remain byte-preserved; plan reports them as not migrated, not
   silently rewritten.
5. No production restart is part of ticket AC. If later implementation changes only prompt files,
   live verification uses fresh/reconnected agents; `mcp_stdio.py` tool-surface changes require
   reconnect before claiming delivery.
6. Rollback is per ticket: revert prompt/validator/tool-surface commit. Canonical facts and DB have
   no migration to reverse.

## 10. Tickets

### T1 — File-first read protocol across Claude/Codex/Grok
- Estimate: 2–4 engineer-days.
- Files: `pipelines/default/prompts/base.md`,
  `pipelines/default/prompts/modules/memory-search.md`, `app/mcp_stdio.py`,
  `tests/test_default_pipeline.py`, `tests/test_runtime_registry.py`, `tests/test_mcp_stdio.py`.
- Consumers checked without planned edits: `app/runtime_registry.py::build_backend`,
  `app/manager.py::SessionManager.assemble_prompt`.
- Test: `docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py` — committed RED in
  `88390896`.
- RED: `AssertionError: T1 missing lexical protocol in its single prompt owner: [...]`.
- AC: `ORCH_PY="$(dirname "$(git rev-parse --git-common-dir)")/.venv/bin/python"; "$ORCH_PY" docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py` is green; `"$ORCH_PY" -m pytest -q tests/test_default_pipeline.py tests/test_runtime_registry.py tests/test_mcp_stdio.py` is green; actual FastMCP registry contains `search_memory` and not `knowledge`; module/prompt has exactly one `search_memory` occurrence and it says compatibility-only/not mandatory; registered tool executes disabled-RAG → `rg`; assembled sentinel reaches Claude/Codex/Grok backends and resumed assembly; no semantic/vector code or runtime state is added.
- blocked-by: none

### T2 — Forward-only lexical fact contract and merge validator
- Estimate: 3–5 engineer-days.
- Files: `pipelines/default/prompts/modules/research-method.md`,
  `scripts/check_kb_contract.py` (new), `tests/test_kb_markdown_contract.py` (new),
  `tests/test_default_pipeline.py`.
- Test: `docs/tasks/417/acceptance/test_t2_lexical_fact_contract.py` — committed RED in
  `88390896`.
- RED: `AssertionError: T2 full-cycle prompt lacks lexical fact contract: [...]`.
- AC: `ORCH_PY="$(dirname "$(git rev-parse --git-common-dir)")/.venv/bin/python"; "$ORCH_PY" docs/tasks/417/acceptance/test_t2_lexical_fact_contract.py` is green; `"$ORCH_PY" -m pytest -q tests/test_kb_markdown_contract.py tests/test_default_pipeline.py` is green; validator is stdlib/repository CLI without MCP decorator; bad key, 0/7 anchors, multiline fact and wrong section fail; mixed legacy+valid added line passes, mixed legacy+invalid added line fails, and absolute/traversal changed paths fail with reason.
- blocked-by: T1

### T3 — Explicitly approved one-hop topic links
- Estimate: 2–3 engineer-days.
- Files: `pipelines/default/prompts/modules/research-method.md`,
  `pipelines/default/prompts/modules/memory-search.md`, `scripts/check_kb_contract.py`,
  `tests/test_kb_markdown_contract.py`.
- Test: `docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py` — committed RED in
  `88390896`.
- RED: `AssertionError: T3 link proposal/approval protocol is not delivered: [...]`.
- AC: `ORCH_PY="$(dirname "$(git rev-parse --git-common-dir)")/.venv/bin/python"; "$ORCH_PY" docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py` is green; `"$ORCH_PY" -m pytest -q tests/test_kb_markdown_contract.py tests/test_default_pipeline.py` is green; exact approval tuple passes while candidate/unknown/nonexistent-receipt/existing-wrong-tuple/missing-target/missing-approval/self/traversal/absolute fixtures stay rejected; no graph store or recursive traversal is introduced.
- blocked-by: T2

## 11. Mutation and regression checks for Phase 3

- T1: break one backend's received sentinel, break resumed assembly, add a second `search_memory`
  instruction or change the sole compatibility line into a mandatory step, retain `knowledge`
  decorator, or remove `search_memory` decorator — T1 must fail for each.
- T2: accept bad fact key, 0/7 anchors, multiline fact, wrong section, a line without `искать:`,
  without evidence, or duplicate fact key — T2 must fail;
  unchanged legacy + valid addition stays green, invalid addition and outside-root diff stay red.
- T3: accept `candidate-link` in canonical KB, unknown relation, existing wrong approval tuple, missing target,
  missing approval, self-link or outside-root target — T3 must fail for each.
- Full regression after all tickets: ordinary project tests plus all three immutable acceptance
  scripts; `git diff 88390896 -- docs/kb/README.md app/ia` must be empty.

## 12. Review route inputs

- Changed Phase 2 files: `docs/tasks/417/plan.md`, immutable acceptance evidence, and
  `docs/kb/agent-memory-architecture.md`; Phase 3 consumers listed in §7.
- Author runtime: Codex current session; exact model ID not exposed in repository metadata.
- AC: three named immutable checks at `88390896`, exact green commands in tickets, plus no-touch
  boundaries.
- Observed RED: T1/T2/T3 all `RC=1` on missing named prompt behavior; no import/collection failure.
- Risk floor: shared prompt and agent tool surface across Claude/Codex/Grok; no strong pre-existing
  behavioral oracle. Desired route is Sol, but auxiliary Sol is not authorized. One fresh Luna
  pass is permitted, with a second prose round only after artifact changes for verified blockers;
  any remaining high-risk uncertainty is reported, not hidden.

### Review outcome

Luna ran 2/2 allowed prose rounds. Round 2 marked the first infrastructure blockers fixed and
returned `Needs work` on three remaining oracle gaps: rewordable mandatory `search_memory`, missing
fact-key/cardinality/one-line/section fixtures, and no existing approval receipt with the wrong
tuple. All three findings were accepted and mechanically closed in immutable RED `88390896`:
single compatibility-only occurrence, focused T2 fixtures, and a second real mismatched receipt.
The prose ceiling forbids a third round, so this plan does **not** claim `APPROVED`; the reviewer
artifact plus post-verdict resolution remain in `docs/tasks/417/review-plan-luna.md`.

## 13. Final RED evidence

```text
RED commit: 88390896

T1 RC=1
AssertionError: T1 missing lexical protocol in its single prompt owner: [...]

T2 RC=1
AssertionError: T2 full-cycle prompt lacks lexical fact contract: [...]

T3 RC=1
AssertionError: T3 link proposal/approval protocol is not delivered: [...]
```
