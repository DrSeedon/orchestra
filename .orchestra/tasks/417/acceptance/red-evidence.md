# #417 pre-implementation RED evidence

Environment:

```bash
ORCH_PY="$(dirname "$(git rev-parse --git-common-dir)")/.venv/bin/python"
```

## T1

Command:

```bash
"$ORCH_PY" docs/tasks/417/acceptance/test_t1_file_first_read_protocol.py
```

Observed before implementation: `RC=1`.

```text
AssertionError: T1 missing lexical protocol in its single prompt owner: ['Выдели 1–3 отличительных поисковых якоря', 'Сначала ищи только в `docs/kb/`', "`rg -l -i -F --glob '*.md'`", '`docs/tasks/` открывай только по ссылке из найденного факта', '`search_memory` остаётся compatibility-тулом']
```

## T2

Command:

```bash
"$ORCH_PY" docs/tasks/417/acceptance/test_t2_lexical_fact_contract.py
```

Observed before implementation: `RC=1`.

```text
AssertionError: T2 full-cycle prompt lacks lexical fact contract: ['Каждый новый или изменённый факт — одна самодостаточная строка без местоименных ссылок', '`искать:` содержит 1–6 буквальных якорей будущего вопроса', 'Сохраняй точные symbol, path, command и прежнее имя', 'Добавь русскую или английскую формулировку, которой пользователь реально задаст вопрос', 'Legacy-факты не переписываются пачкой; контракт применяется только к новым и изменённым строкам']
```

## T3

Command:

```bash
"$ORCH_PY" docs/tasks/417/acceptance/test_t3_approved_one_hop_links.py
```

Observed before implementation: `RC=1`.

```text
AssertionError: T3 link proposal/approval protocol is not delivered: ['LLM не записывает предложенную связь в `docs/kb/` как истину', '`candidate-link` остаётся в `docs/tasks/` до явного апрува', 'Canonical `связи:` требует ссылку на approved ticket/plan anchor', 'Retrieval раскрывает не больше одного перехода', '`depends_on|explains|contradicts|supersedes|evidence_for|related`']
```

All three failures are missing named behavior. There are no import, collection, fixture, or
environment errors.

The first frozen commits `6b815eb9`, `609ee812`, `d4d87141`, and `f72ae207` are superseded for Phase 3 replay:
before final plan review and before any production behavior, the oracles were strengthened to inspect
the actual FastMCP registry and disabled-RAG invocation, model runtime backends, resumed prompt
assembly, diff-line grandfathering, project-root containment, approval receipts, and self-links.
After the final prose-review round they were strengthened once more with a single-reference
compatibility-only invariant, fact-key/cardinality/one-line/section fixtures, and an existing
approval receipt carrying the wrong tuple.
The first failing assertion of each ticket is unchanged. The next commit containing this file is the
only immutable RED baseline.
