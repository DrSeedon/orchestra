> **RETRACTED как описание текущего main (08.09.2026, #530).** Ниже — историческое доказательство ветки #504, а не действующий контракт. Утверждения о живых площадках A, необходимости внедрить T1/T2/T3/T5, ожидании T4 и текущей пригодности прежних оракулов отменены коммитом `264daeb75484bbe9f97e53c654180fca11c8a12a`: main уже отделяет управление от прозы, удаляет T4-классификатор и safeguard-fork, использует `provider_limit`, завершение CLI и временный round hint. Исторические результаты тестов остаются результатами своих снимков, не текущего main. Адресная развязка всех десяти площадок и тестов: [дифференциал #530](../530/diff-main-vs-504.md). Исходные байты: `git show bf496f8828e4ae5859ac09fd1a20a864ac9e895b:.orchestra/tasks/504/source-to-sink.md`.

# #504 source-to-sink completeness pass

This is independent of the curated 101-row anchor inventory. It starts at every model-text ingress found in `app/`, then follows the value to literal/regex decisions. Pass-through logging, persistence, rendering, and dynamic duplicate suppression are recorded but are not new literal/regex sites.

## Producer roots

| producer | mechanical discovery | direct consumer |
|---|---|---|
| Claude assistant text | `app/backend_claude.py:1268` emits `AgentEvent("text", block.text)` | `AgentSession._handle_event` |
| Codex assistant text | `app/backend_codex.py:2178` emits `AgentEvent("text", text)` | `AgentSession._handle_event` |
| Grok assistant text | `app/backend_grok.py:1117` emits `AgentEvent("text", text)` | `AgentSession._handle_event` |
| Harness assistant text | `app/harness/loop.py:256` emits `AgentEvent("text", content)` and stores the assistant message in `history`/`new_messages` | `AgentSession._handle_event`; harness cleanup |
| Claude native assistant history | `app/session_turns.py:43` reads SDK messages and `app/session_turns.py:49` checks `role == "assistant"` | safeguard rewind cut point |
| Compact model output | `app/session.py:2957` consumes backend events and `app/session.py:2959` appends `text` to `summary_parts` | compact summary validation |
| Review model output | `app/codex_review_artifact.py:34` extracts typed JSONL `agent_message`; `app/codex_review_artifact.py:197` reads/finalizes the artifact | review job validation, verdict and finding parsers |
| Model-authored `send_message` body | `app/routes/sessions.py:968` receives `req.message`; task rewriting occurs at `app/routes/sessions.py:1024`; terminality itself is typed `message_kind` at `app/routes/sessions.py:1069` and `app/routes/sessions.py:1083` | task-prefix contract only |
| Persisted assistant `text` rows | `app/session.py:2488` persists; TG and dashboard consume the typed row kind | silent marker and tool-call warning renderers |

Command used to enumerate the four runtime emitters:

```text
rg -n -F 'AgentEvent("text"' app
app/harness/loop.py:256
app/backend_claude.py:1268
app/backend_codex.py:2178
app/backend_grok.py:1117
```

## Sink closure

| producer root | literal/regex sinks reached | other consumers checked |
|---|---|---|
| `AgentEvent("text")` → `_handle_event` | A rows 1-3 (`_subscription_limit_kind`, `_is_safeguard_refusal`) | `_log`, `_turn_logs`, `_last_text_output` are pass-through; `_last_text_output` has only B silent-marker matching in auto-report |
| compact `summary_parts` | A rows 1-2 through `_is_terminal_subscription_limit`; A row 4 through `_GARBAGE_PATTERNS` | empty/length/newline checks are structural, not vocabulary inference |
| native assistant history | A row 3 through `_is_safeguard_refusal` | all other fields used are typed `role`/UUID |
| review artifact / JSONL agent message | A rows 6 and 6b; B rows 12-17 | `_last_agent_message` matches typed JSONL item type, but the missed `app/mcp_stdio.py:3590` then regexes that typed item's model-produced `text`; receipt coverage otherwise uses typed columns except the listed artifact parsers |
| harness assistant history | A rows 7-8 | remaining branches use structured `role`, `tool_calls`, `tool_call_id`, and finish reason |
| `send_message` model body | B row 18 | fan terminality uses typed `message_kind`; `DONE`, `RESEARCH DONE`, and `PLAN READY` have no consumers |
| persisted `text` row in TG/dashboard | A rows 5 and 9; B rows 10-11 | direct rendering and dynamic stream de-duplication do not compare against a literal/regex and are outside the requested shape |

Closure searches:

```text
rg -n '_last_text_output|summary_parts|role.*assistant|agent_message|event.type == "text"|t == "text"' app
rg -n '_subscription_limit_kind|_is_terminal_subscription_limit|_is_safeguard_refusal|is_silent_turn_text|looks_like_unexecuted_tool_call|_BLIND_REVIEW|_REVIEW_VERDICT|FINDING_RE|FINDING_HEADING_RE' app
rg -n 'RESEARCH DONE|PLAN READY|DONE #|SILENT_TURN_MARKER|## Verdict' app
```

Corrected Phase-2 result: every literal/regex sink reached from a model-text root maps to one of the 19 A/B rows in `research.md`. The original Phase-1 closure missed `app/mcp_stdio.py:3590` because it stopped at the typed JSONL `agent_message` discriminator and failed to follow the inner `text` field into `_CODEX_EXECUTION_FAILURE_JSONL_CHECK`; the corrected closure includes it as A row 6b.

## C provenance basis

The 83 C rows in `check_anchors.py` are the retained lookalikes from the shape scan, not a claim that they are every deterministic-text parser in the repository. Their producer groups are source-local and mutually exclusive:

- Python runtime/provider/DB errors: C1-C7.
- Python command/file/SSH/SSE/tool outputs: C8-C21.
- Python platform/TG/task/merge/status-generated text: C22-C40.
- Browser deterministic tool/status/error payload renderers: C41-C83.

The class-C count answers “how many inspected shape hits were excluded from A/B.” It is not used to prove the class-A closure; the producer-root pass above does that. A C row moving onto a model-text ingress would therefore be caught as an unclosed sink even if its old provenance label remained stale.
