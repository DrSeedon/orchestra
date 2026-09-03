# #221 — Telegram formatting rules in the top-level orchestrator prompt

## What the bridge does

`app/tg_bridge.py:497-502` calls `telegramify_markdown.convert()` and returns converted text plus
Telegram entities. `_formatted_chunks()` converts before enforcing the final payload limit
(`app/tg_bridge.py:893-898`), and `_tg_send_safe()` sends the result with
`parse_mode=None, entities=send_entities` (`app/tg_bridge.py:1959-1962`). Text events enter this
path at `app/tg_bridge.py:3153-3163`.

Direct checks against the installed converter:

- `# Heading` becomes `📌 Heading` with underline and bold entities.
- `**bold**` becomes bold; `*bold*` becomes italic.
- Backtick and fenced-code forms become code/pre entities.
- A Markdown table becomes preformatted text, which is still a poor phone layout.

Therefore the source advice that `#` does not render and `*bold*` is bold was not copied: both
claims contradict the live bridge. The prompt uses bridge-supported `**bold**`, `_italic_`, code,
and fenced code, while retaining the phone/table, bare-URL, and question-length guidance.

## Owner selection

| candidate | who reads | verdict |
|---|---|---|
| `pipelines/default/prompts/modules/` | Only roles listed in each module's `pipeline.yaml` `modules` entry; adding it to all senders would broaden its audience | no — no shared module is needed for one direct user-facing role |
| `pipelines/default/prompts/roles/orchestrator.md` | Top-level orchestrator; its role text says replies go directly to the user and Telegram | **owner** |
| `pipelines/default/prompts/base.md` | All four roles, including workers and sub-orchestrator; sub-orchestrator reports to its parent and workers report to the orchestrator | no — the user-facing Telegram rule would leak to roles that do not write to the user directly |

## Verification

```text
uv run pytest -q tests/test_default_pipeline.py
79 passed in 6.42s
```

Mutation of `pipelines/default/prompts/roles/orchestrator.md` (copy → remove the whole section →
test → restore with `mv` → `touch` → test) produced:

```text
FAILED ...test_every_source_clause_reaches_the_assembled_user_prompt
FAILED ...test_telegram_formatting_does_not_leak_to_non_user_roles
2 failed, 77 passed
```

After restoring and touching the owner file, the complete targeted test returned `79 passed`.
