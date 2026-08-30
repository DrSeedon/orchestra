# #417 — отчёт реализации file-first памяти агентов

## Результат

Реализована утверждённая ветка без второй базы и без semantic/vector retrieval:

- canonical project memory остаётся в `docs/kb/`;
- общий prompt для Claude/Codex/Grok выполняет двухпроходный literal `rg` и раскрывает не больше
  одной approved-связи;
- generic `knowledge` снят с agent-facing FastMCP registry и access-mode списков, но его внутренняя
  функция и `app/ia/*` не удалены;
- `search_memory` остался зарегистрированным, с прежней сигнатурой и disabled-RAG → `rg` fallback;
- новые/изменённые structured facts и one-hop links проверяет repository CLI
  `scripts/check_kb_contract.py`; нового MCP tool и нового хранилища нет.

## Выполненные tickets

### T1 — File-first read protocol

- `pipelines/default/prompts/base.md` (+4/-11): owner memory заменён на project-local `docs/kb`.
- `pipelines/default/prompts/modules/memory-search.md` (+24/-12): 1–3 literal anchors,
  `rg -l` → `rg -n`, evidence-only переход в `docs/tasks`, максимум один approved hop; ровно одно
  compatibility-only упоминание `search_memory`.
- `app/mcp_stdio.py` (+0/-3): снят только decorator generic `knowledge` и два list membership;
  `knowledge()` остался внутренним callable, `search_memory()` не менялся.
- `tests/test_default_pipeline.py` (+5/-1), `tests/test_runtime_registry.py` (+38),
  `tests/test_mcp_stdio.py` (+25): delivery/registry/fallback для decision roles и трёх runtimes.

Порядок аварийно-безопасный закреплён историей: prompt перестал ссылаться на generic `knowledge`
в `7b035c91`, decorator снят следующим commit `807f879d`. На каждом #417 commit оба gate давали 1:

```text
search_memory @mcp.tool() count = 1
memory-search.md search_memory count = 1
```

### T2 — Forward-only lexical fact contract

- `pipelines/default/prompts/modules/research-method.md` (+27 вместе с T3): one-line stable
  `fact:` key, 1–6 quoted `искать:` anchors, непустой evidence, legacy grandfathering.
- `scripts/check_kb_contract.py` (+378, mode 100755): stdlib CLI разбирает hunk ranges unified
  diff, проверяет root containment, section, stable key, duplicate, anchors, evidence и same-key
  replacement удалённого structured fact.
- `tests/test_kb_markdown_contract.py` (+288 вместе с T3): valid update, deletion/rewrite,
  malformed key, 0/7 anchors, multiline, wrong section, empty evidence, path escapes и контрпример
  `+++ /dev/null` внутри hunk content.

### T3 — Explicitly approved one-hop links

- LLM proposal остаётся в `docs/tasks`; canonical `связи:` допускает только шесть typed relations.
- Validator требует существующий non-self Markdown target внутри project KB и exact tuple
  `source fact + relation + target` из `docs/tasks/<numeric-id>/plan.md#anchor`.
- Контрпримеры: canonical candidate, unknown relation, absent/self/absolute/traversal target,
  missing anchor, existing wrong tuple, receipt из `research.md` и `docs/tasks/plan.md`.

## Проверки

Frozen acceptance commit `88390896` не изменён:

```text
T1 PASS: file-first protocol delivered; knowledge retired; search_memory preserved
T2 PASS: changed facts require stable key, literal search anchors, and evidence
T3 PASS: only approved, typed, existing-target one-hop links enter canonical KB
```

Focused regression после финального фикса:

```text
tests/test_kb_markdown_contract.py: 30 passed
combined prompt/runtime/validator selection: 177 passed, 109 deselected
docs/kb diff through scripts/check_kb_contract.py: KB contract OK
production sessions: 564 -> 564
```

Полная обязательная команда выполнена:

```text
uv run python -m pytest -x -q
1 failed, 30 passed, 39 skipped, 3 deselected in 9.50s
FAILED tests/test_api.py::TestTaskProjectIdentity::test_create_defaults_to_callers_mapped_scope
production sessions: 564 -> 564
```

Это не новая краснота #417: тот же node на неизменённом base `965535cf` возвращает тот же
`400 != 200` (`1 failed in 4.06s`). Точный T1 pytest-набор также имеет два baseline-red теста в
`tests/test_mcp_stdio.py` (role-dependent `task_update` и stale cross-repo delivery expectation);
оба отдельно воспроизведены на `965535cf`. #417 их не меняет.

Mutation evidence против committed oracles:

- убрать decorator `search_memory` → T1 RC=1; восстановление → PASS;
- отключить 1–6 anchor count → T2 принимает zero anchors и падает RC=1;
- разрешить canonical proposal → T3 принимает candidate и падает RC=1;
- снять executable bit, same-key deletion guard, hunk-content guard, nonempty evidence,
  `plan.md` provenance или task-id shape → каждый соответствующий committed pytest краснеет;
  после каждого восстановления тест зелёный;
- каждый pytest/mutation run, поднимавший DB layer, сохранил production `sessions` 564 → 564.

## Pre-mortem следующего consumer

| Риск | Наблюдаемый симптом | Проверка |
|---|---|---|
| Runtime получает старый/неполный prompt | один из Claude/Codex/Grok теряет lexical anchors | frozen T1 + runtime sentinel tests |
| Вместе с generic tool исчезает compatibility fallback | `search_memory` отсутствует в FastMCP registry | T1 registry invocation + decorator mutation |
| Merge удаляет canonical fact под видом legacy rewrite | deleted `fact:` исчезает без same-key replacement | deletion/rewrite regressions + mutation |
| Строка KB ломает state unified-diff parser | invalid fact после content `+++ /dev/null` пропускается | committed header-masquerade regression |
| Модель сама подделывает approval | link с receipt не из task-scoped plan проходит | research/root-plan/wrong-tuple regressions |

## Review

Route: Luna, 3 executable-code rounds, artifact
`docs/tasks/417/review-implementation-luna.md`.

- Round 1: `CHANGES REQUIRED`, 5 blockers; все воспроизведены и исправлены.
- Round 2: 4 `FIXED`, receipt path `STILL BROKEN`; добавлена точная task-path форма.
- Round 3: `APPROVED`; цитата reviewer evidence:
  `or re.fullmatch(r"[1-9][0-9]*", receipt_parts[2]) is None`.

## Breaking / rollout

- Breaking намеренно: agent-facing MCP tool `knowledge` больше не публикуется.
- Совместимость сохранена: internal `knowledge()` и `app/ia/*` не тронуты; `search_memory`
  остаётся tool.
- Prompt общий для всех проектов; живых чужих агентов не использовали как стенд по прямому запрету.
  Новая сборка доедет штатным prompt assembly/reconnect путём.
- Миграции 20 502 записей, vector rebuild, `as_of` schema и recursive graph traversal отсутствуют.
- `docs/kb/README.md` не изменён; строку оглавления добавляет orchestrator.

## Оставшиеся пробелы

- Machine `as_of` по-прежнему отложен; trigger из plan — три реальные задачи с историческим
  reconstruction либо compliance requirement.
- Влияние one-hop links на ≥10 cross-topic вопросов не измерено. Реализован только безопасный
  protocol записи/чтения; task-success не заявляется.
- Baseline-red full-suite и два baseline-red `test_mcp_stdio` за пределами #417 требуют отдельных
  владельцев, если их решено чинить.

## Reusable lesson

Full-cycle worker, которому одобрена Phase 3 и выданы ownership + собственные frozen oracles,
реализует tickets в своей ветке. Создание побочной task/worker без прямого поручения создаёт
неапрувленную единицу работы и пересечение файлов.
