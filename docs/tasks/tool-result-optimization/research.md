# Research — tool_result size in LLM-agent context (Orchestra)

**Task:** #tool-result-optimization
**Phase:** 1 (Research). No code. Truth-finding.
**Date:** 2026-07-09

---

## Question (framed)

- **Context:** Orchestra runs Claude agents via `claude-agent-sdk` (0.2.87) → bundled Claude Code CLI (2.1.197), preset `claude_code`. tool_results are stored in `logs` and replayed into context every turn → cache_read.
- **Change under test:** How do we reduce the token cost of tool_results being replayed each turn?
- **Baseline:** Current state — no truncation/offload config on our side; whatever the CLI does automatically.
- **Measurable outcome:** chars/tokens of tool_result in context, and $ of cache_read attributable to them.

The task's premise: *"Read of a 2000-line file = 20K tokens × 100 turns = 2M cache-read."* This is **directionally true but points at the wrong culprit** (see Finding 1).

---

## Hypotheses considered

- **H1 (task's implicit hypothesis):** The cost is dominated by agents reading whole large *text* files. Fix = teach agents to grep/read-with-limit. → **PARTIALLY REFUTED.** Text reads are only ~4% of tool_result bytes.
- **H2:** The cost is dominated by a small number of *monster* outputs, not by many medium reads. → **CONFIRMED.** 2.5% of results = 86% of bytes.
- **H3:** The monsters are base64 **images** read via the `Read` tool (screenshots, generated PNGs). → **CONFIRMED.** 89% of all tool_result bytes are image Reads.
- **H4:** We can fix this server-side by enabling Anthropic's context-editing API (`clear_tool_uses`) through the SDK. → **REFUTED for our SDK version** (betas field rejects that flag; see Finding 4).

Falsifiers I went looking for: "maybe images are a rounding error" (checked: they are 89%); "maybe the SDK exposes context_management" (checked installed source: it does not).

---

## Findings

### Finding 1 — The cost is ~90% base64 IMAGES read via `Read`, not text files
**Confidence: CONFIRMED** — direct measurement of our DB (evidence tier 1).

Paired every `tool_result` row to its preceding `tool` row (they are adjacent, `tool` content starts with `ToolName:`), n=6307 tool_results, 56.9M chars total (~14.2M tokens raw at chars/4):

| Bucket | n | chars | mean chars | % of all tool_result bytes |
|---|---|---|---|---|
| **Read — IMAGE (base64)** | **207** | **50,725,076** | **245,048** | **89.2%** |
| Read — TEXT | 695 | 2,408,664 | 3,465 | 4.2% |
| Bash | 2730 | 1,922,914 | 704 | 3.4% |
| WebSearch | 190 | 1,094,665 | 5,761 | 1.9% |
| Edit / Write / all MCP / rest | ~2400 | ~700,000 | — | ~1.3% |

- A single image Read = **245K chars mean ≈ 61K tokens** in context. Images are re-tokenized every turn just like text.
- Distribution is extreme: **>50K chars: 166 results (2.6%) = 87.4% of bytes.** **>100K: 158 results (2.5%) = 86.3%.** Median tool_result is **211 chars**.
- Top offenders are literally `Read {file_path: /tmp/*.png}` — screenshots and generated marketing/design PNGs (seedon designer, bobik spritesheets, admin captures), 550K–674K chars each.
- 164 distinct images, 207 reads → **some images re-read 3–4× within a session** (each re-read is a fresh 61K-token blob).

**Implication:** The task framing (grep-before-read for text files) attacks the 4% and ignores the 89%. The real lever is **image handling**.

### Finding 2 — Text-file over-reading is real but secondary (~4%)
**Confidence: CONFIRMED** — measurement.

- Read-TEXT mean = 3,465 chars (~866 tokens). That's *reasonable*, not the described 20K.
- Only **91 text reads exceed 10K chars** (~2M chars, ~4% of total). Biggest text walls (46K chars): research `.md` files, `mcp_stdio.py`, session transcripts.
- Notably, Claude Code **already truncates** big text reads: one result contained `<system-reminder>[Truncated: PARTIAL view — showing lines 1-470 of 565]`. So the CLI caps text Read output on its own.

### Finding 3 — Claude Code has a built-in 3-tier context pipeline, but **Read opts OUT of offloading**
**Confidence: LIKELY** — Anthropic compaction docs (primary) + reverse-engineering of the accidentally-shipped CLI source [3][6] (secondary, community). The "Read opts out" detail is from the leaked-source analysis, tier-2.

Claude Code pipeline before each API call: **budget → microcompaction → auto-compaction → manual /compact** [3][6].
- **Microcompaction:** large tool outputs are persisted to disk, replaced in-context with a ~2KB preview + file path; model re-reads on demand. Default per-tool threshold `maxResultSizeChars` ≈ **50K chars**. Applies to Bash, Grep, Glob, WebSearch, WebFetch, Edit, Write.
- **BUT: the `Read` tool opts out entirely (threshold = Infinity)** — because offloading a Read result to a file you'd Read back is circular [6].
- **AND: for image content, `maxResultSizeChars` has no effect at all** [1] — image offload isn't supported; the only lever is `MAX_MCP_OUTPUT_TOKENS`, and that's MCP-only.

**So the one built-in mechanism that would help is specifically disabled for exactly our #1 cost (image Reads).** Since we run the `claude_code` preset, microcompaction is already active for Bash/WebSearch/etc — which is why those stay small in our data. It cannot touch image Reads.

### Finding 4 — We CANNOT enable the server-side context-editing API through our SDK
**Confidence: CONFIRMED** — direct inspection of installed SDK source (evidence tier 1).

Anthropic's context-editing API `clear_tool_uses_20250919` (beta header `context-management-2025-06-27`) clears old tool_use/result pairs, keeping the last N [2]. Params: `trigger` (default 100K input tokens), `keep` (default 3 tool uses), `clear_at_least`, `exclude_tools`, `clear_tool_inputs`.

But in **our installed `claude-agent-sdk` 0.2.87**:
```
.venv/.../claude_agent_sdk/types.py:29:  SdkBeta = Literal["context-1m-2025-08-07"]
.venv/.../claude_agent_sdk/types.py:1682: betas: list[SdkBeta] = field(default_factory=list)
```
- `betas` accepts **only** `context-1m-2025-08-07`. There is **no `context_management` field** in `ClaudeAgentOptions` (fields: model, system_prompt, mcp_servers, permission_mode, resume, max_turns, disallowed_tools, betas, cwd, cli_path, settings, add_dirs, env, extra_args, max_buffer_size).
- `betas` is forwarded as a **CLI flag** `--betas` (`subprocess_cli.py:277`), not an HTTP header. `extra_args` also = CLI flags, not headers [SDK issue #845].
- **Conclusion:** the context-editing API is not reachable from our stack. Context management is delegated wholesale to CLI 2.1.197's automatic microcompaction, which (Finding 3) excludes image Reads.

### Finding 5 — `MAX_MCP_OUTPUT_TOKENS` / `maxResultSizeChars` don't apply to our problem
**Confidence: CONFIRMED** — Claude Code MCP docs (primary) [1] + our MCP output sizes (measurement).

- `MAX_MCP_OUTPUT_TOKENS` (default 25K) caps **MCP tool** output only, and **"has no effect on tools that return image content"** [1]. Our monster is the built-in `Read`, not MCP → knob useless here.
- `anthropic/maxResultSizeChars` (cap 500K) is for MCP servers we author. Our Orchestra MCP tools already output tiny results (send_message 47 chars, merge_worker 141, task_get 1.8K). Not our problem.

### Finding 6 — Industry consensus: cap tool output, prefer search/pagination, isolate heavy reads in subagents
**Confidence: LIKELY** — Anthropic engineering blogs (primary) [4][5], multi-secondary for competitors [7].

- Anthropic "Writing effective tools": **cap responses ~25K tokens**, paginate/filter, expose a `response_format` enum (`concise`/`detailed`), "return only what matters" [5].
- Anthropic "Effective context engineering": **context rot** — recall degrades as tokens grow; every token depletes the attention budget. Send *"go read everything"* tasks to **subagents** with isolated context; the lead agent gets only the summary [4]. (Tradeoff: multi-agent can burn ~15× tokens.)
- **Subagent isolation is the cross-industry answer for heavy reads:** Devin/Windsurf `Explore` read-only research subagents, Cursor cloud-VM isolation, Devin Local subagents [7]. The heavy tool_result lives in the subagent's context and dies with it; parent keeps only the digest.
- Truncation defaults elsewhere (comparison points): OpenAI Codex CLI truncates tool output at **10 KiB or 256 lines, head+tail**; Gemini CLI at 4M chars [1]. Claude Code microcompaction ≈ 50K chars/tool [3][6].

---

## Counter-evidence / conflicts

- **"Read whole file is the problem" (task premise) vs data:** data says text reads are 4%. If the recent workload shifts (e.g. a code-heavy sprint with no screenshots), text reads could dominate — this snapshot is design/marketing-heavy (seedon PNGs). So the grep-first rule still has *some* value, just not headline value. Present both.
- **Leaked-source specifics (50K threshold, "Read opts out", 2KB preview)** are tier-2 (community reverse-engineering of the 2026-03-31 accidental source drop), not official docs. Directionally corroborated by our data (Bash/WebSearch stay small → offload works; image Reads stay huge → they don't). Treat exact numbers as approximate.
- **cache_read total = 1.30B tokens** in our `sessions` table (cache_create 43M). The task's "600M / 87%" is plausible against this magnitude but I could not attribute cache_read to tool_result vs system-prompt vs history at row level (the SDK reports aggregate cache_read per turn, not per-block). So "87% of cache_read is tool_result replay" is **UNCERTAIN** as an exact figure — but "tool_results, dominated by images, are a large replayed cost" is CONFIRMED by the byte distribution.

---

## What we CAN actually do (affected surfaces)

Ranked by ROI (impact × feasibility given Finding 4 = no server-side API):

1. **Prompt rule: stop re-reading images; don't Read images you don't need to *see*.** ~89% of the cost is image Reads, 3–4× re-reads observed. An agent that generated/saved a PNG rarely needs to Read it back into context at all (it already knows what it made); when it must verify, Read once, never again. **Highest ROI, zero infra.**
   - Files: `pipelines/default/prompts/modules/*` (base or a new `tool-output.md`), `full-cycle.md`, `worker.md`.

2. **Prompt rule: heavy exploration → subagent.** For "read this whole dir / large file / many files", spawn a read-only subagent (Explore/Task) so the bulky tool_result stays in the subagent's context and the parent gets a digest [4][7]. We already have subagent telemetry (`subagents` table). Aligns with Anthropic's own guidance.

3. **Prompt rule: grep/read-with-limit before full Read of large text files.** Attacks the ~4% text-wall tail. Low cost to add, modest payoff. `Read` supports `offset`/`limit`; grep first to find the lines.

4. **Backend (optional, real work): strip base64 image blobs from the DB `logs` before they're used for anything context-shaped, and/or downscale screenshots at capture.** Note: this does NOT change what the *live CLI* replays (the CLI owns its transcript) — it only shrinks our DB and any place we rebuild context from `logs`. Value is mostly DB size (150MB, images dominate) + dashboard, not live cache_read. **Verify before building** where `logs.content` feeds back into a model.

5. **Screenshot hygiene at source:** capture PNGs at lower res / crop / JPEG. A 674K-char screenshot is usually a full-page 4K grab. Halving pixels ≈ halves the 61K-token blob. Touches whoever produces the screenshots (Playwright skills, designer workers), not core.

**Not available to us:** server-side `clear_tool_uses` context editing (Finding 4); `MAX_MCP_OUTPUT_TOKENS` for images (Finding 5). Do not propose these as fixes.

## ROI estimate (realistic)

- Image Reads = 89% of tool_result bytes. If prompt rules cut image re-reads by ~half and eliminate gratuitous read-backs, plausibly **remove 40–60% of tool_result replay volume** at ~zero infra cost. This is the single biggest lever.
- Text grep-first: attacks 4% → best case ~2–3% saving. Nice-to-have.
- Backend base64 stripping: big DB/dashboard win (~100MB+), **little-to-no live cache_read win** unless we confirm `logs` feeds context.

## Risks / edge cases for the code to come

- Image re-read is sometimes legitimate (agent iterating on a visual). A blanket "never Read images" rule would break design/QA workflows → rule must be "read once, don't re-read; prefer not to read your own generated output back."
- Subagent delegation costs tokens too (~15× worst case [4]) — only worth it for genuinely heavy reads, not every file.
- Verify (Finding 4 caveat): confirm the CLI can't be handed context-editing via a `settings.json` / env knob before concluding "impossible" — I confirmed the SDK path is closed, not every CLI config surface.

---

## Sources (all fetched this session)

1. Context windows / MCP output limits — https://platform.claude.com/docs/en/build-with-claude/context-windows , https://code.claude.com/docs/en/mcp (MAX_MCP_OUTPUT_TOKENS 25K default; image annotation caveat)
2. Context editing (`clear_tool_uses_20250919`) params + beta header — https://platform.claude.com/docs/en/build-with-claude/context-editing
3. Claude Code compaction pipeline (microcompaction/auto/manual) — https://platform.claude.com/docs/en/build-with-claude/compaction ; deep dive https://codex.danielvaughan.com/2026/04/14/context-compaction-deep-dive-codex-cli-claude-code-opencode/
4. Anthropic — Effective context engineering for AI agents — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
5. Anthropic — Writing effective tools for agents (cap ~25K, response_format, pagination) — https://www.anthropic.com/engineering/writing-tools-for-agents
6. Claude Code leaked-source analysis (Read opts out, 50K threshold, 2KB preview) — https://decodeclaude.com/compaction-deep-dive/ , https://newsletter.victordibia.com/p/inside-claude-code
7. Competitors (Devin/Windsurf Explore subagents, Cursor cloud isolation) — https://blog.getbind.co/cursor-vs-devin-desktop-windsurf-2026/ , https://docs.devin.ai/cli/changelog/stable
8. SDK beta constraint (context-management not passable) — https://github.com/anthropics/claude-agent-sdk-python/issues/845 + direct inspection of installed `claude-agent-sdk` 0.2.87 `types.py:29,1682` and `subprocess_cli.py:277`
