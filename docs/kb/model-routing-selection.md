# model-routing-selection

## Установлено

- #298 сформулировал тотальное дерево как server-side first-match router перед созданием worker: metadata/sensitivity/special-complex/capability/oracle → Ox только для публичной closed/oracle-backed text+tools ветки с zero-spend/canary gate → Luna для закрытого deterministic fallback → Sol для open/complex; prompt остаётся зеркалом, runtime/backend — downstream constructor · `docs/tasks/298/research.md`, current owners `app/mcp_stdio.py:893-926`, `app/manager.py:643-714` · 2026-08-23, #298
- Для каждого Sol-листа #298 требует отдельный trusted `sol_authorized` receipt, scope/expiry-проверку и first-match `REFUSE_SOL_AUTH`; parent-task approval, prompt, alias или старую Sol-сессию нельзя считать авторизацией нового Sol spawn/review/eval · `docs/tasks/298/research.md` §Fallback and escalation invariants, current auxiliary-authorization boundary из `codex-debate` · 2026-08-23, #298
- Полное дерево #298 содержит явные листья Claude Opus (special creative/vision/ambiguity и Codex-exhaustion consequence), Spark (измеренный strict contract, one-failure handoff/no retry), Ox, Luna, authorized Sol и REFUSE_DISABLED_MODEL для Fable/Terra; отказ Sol-auth не деградирует в Ox/Luna · `docs/tasks/298/research.md` §Proposed routing-tree/No-unmatched proof · 2026-08-23, #298

- `codex_review` omitted model currently defaults in executable MCP code to `gpt-5.6-luna`; `app/mcp_stdio.py:798-800,2413` · 2026-08-23, #229
- `codex_review` accepts registered Codex-runtime models whose quota bucket is `codex`, and rejects non-Codex runtimes plus Spark; `app/mcp_stdio.py:803-852` · 2026-08-23, #229
- `spawn_worker` has no model fallback: empty/omitted `model` raises before HTTP; `app/mcp_stdio.py:912-917` · 2026-08-23, #229
- Managed worker effort resolves exact canonical model → runtime → `default` from the role manifest; `app/pipeline.py:524-538`, `app/manager.py:736-740` · 2026-08-23, #229
- Current worker task-class Luna/Sol/Opus routing is prompt-only; code validates the caller-selected model, availability and admission but does not select a model; `pipelines/default/prompts/modules/model-routing.md:3-20`, `app/mcp_stdio.py:912-926`, `app/manager.py:579-714` · 2026-08-23, #229
- Pipeline skill source is tracked under `pipelines/default/prompts/skills/`; `.codex/skills/` is an ignored runtime projection guarded by `app/prompting.py:195-217,262-267` · 2026-08-23, #229
- The current Codex Sol orchestrator prompt contains the DIY/research/delegation markers, yet its live session made 21 Bash scans (264 unique marked Markdown paths, 2,257 result lines) before its first `spawn_worker`; prompt delivery was present, but no code guard enforces spawn-before-read · `sessions.system_prompt` marker probe + `logs` metadata, 2026-08-23, #229

## Отвергнуто

- Универсальный Ox default и единая цепочка Ox→Luna→Sol отвергнуты: #236 зафиксировал unsuffixed zero-price TOCTOU и шесть no-effort пустых Ox turns, а #283 даёт только узкое 6/6 production-shaped evidence; routing обязан учитывать sensitivity, oracle, openness и complexity до spawn · `docs/tasks/298/research.md`, `docs/tasks/236/research.md`, `docs/tasks/283/research.md` · 2026-08-23, #298

- `codex_review` omitted model is still Sol — current default is Luna; #304’s Sol statement was superseded by `9a1e2d10` and retained through `0707d925` · 2026-08-23, #229
- `spawn_worker` omission uses the pipeline role default — current MCP rejects omission, and HTTP omission defaults to Sonnet rather than manifest Opus; `app/mcp_stdio.py:912-917`, `app/routes/sessions.py:121-155` · 2026-08-23, #229
- A live quota router chooses Luna/Sol/Opus at spawn — the former router/model policy was removed by `0707d925`; current code only admits the chosen model · 2026-08-23, #229
- The parent read hundreds of Markdown files because the delegation rule was absent from its prompt — the stored prompt contains the relevant markers; the missing piece is an executable ordering guard, while prompt wording still leaves timing to model judgment · `sessions.system_prompt` marker probe, `app/backend_claude.py:61-69,447-455`, `app/backend_codex.py:2235-2238` · 2026-08-23, #229

## Пробелы

- Не определены кодом trusted task metadata (sensitivity/openness/oracle/capability), атомарный OpenRouter broker/lease, vision capability Ox и точная class→effort карта; до закрытия этих seam-ов соответствующие листья должны fail-closed · `docs/tasks/298/research.md` §Current-state/seam inventory · 2026-08-23, #298

- Effective effort used by standalone `codex_review` was not measured from the live Codex CLI/config; current review command contains no explicit effort flag · 2026-08-23, #229
- VPS/Contabo observed-use counts were not collected because a safe read-only DB path was not established in this session · 2026-08-23, #229
- The model’s hidden rationale for scanning before spawning is not recorded in structured logs; only tool order and prompt delivery are observable · 2026-08-23, #229

## Источники

- `docs/tasks/298/research.md` — тотальное first-match дерево, current-state/seam inventory, failure matrix и rollout gates.

- `docs/tasks/229/research.md` — current routing evidence matrix, historical supersession and local observed-use counts.
