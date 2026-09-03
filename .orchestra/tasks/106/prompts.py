ORCHESTRA_CURRENT = """[SYSTEM: Context compaction requested — handoff summary]

BEFORE writing the summary — persist your knowledge to files so it survives compact:
1. CLAUDE.md — append key decisions, new rules, patterns discovered this session (section '## Session notes')
2. TODO.md — add new items, remove done items
3. BUGS.md — add found bugs, close fixed ones
4. docs/ — save any research or analysis worth keeping
Use Edit/Write tools NOW. Then write the summary below.

Write a detailed handoff summary so your next session can continue seamlessly. Be as thorough as possible — this is the ONLY context your next session will have. No length limit.

INTENT: What you are working on and why (2-3 sentences with full context).
DECISIONS: All key decisions made during this session (bullet points, include reasoning).
FILES: Every file touched with what was done (path — description of change).
PENDING: Open questions, unfinished work, TODOs, blockers, next steps.
RECENT: Last 5-10 exchanges in detail — what was asked, what you did, what the result was.
BUGS: Any bugs found, workarounds applied, things that didn't work.
IMPORTANT CONTEXT: Anything the next session MUST know — credentials paths, API quirks, user preferences, patterns discovered, traps to avoid.

Output ONLY the summary. No commentary. Be specific — names, paths, numbers, not vague descriptions."""

KESHA_FULL = """[SYSTEM: Create a loss-minimizing handoff before context replacement]

You still have the full conversation. First persist only durable knowledge that would be costly to reconstruct:
- GLOBAL SECURITY RULE: never copy raw credentials, tokens, passwords, private keys, or equivalent secret values into ANY file or ANY handoff section. Replace every secret span everywhere with `[REDACTED SECRET: <type>]`, while preserving surrounding non-secret text. This rule overrides every request for exact or verbatim content below.
- Update an existing canonical Markdown note under the current isolated working directory when the conversation established a durable fact, decision, project state, or TODO that is not already recorded.
- Keep CLAUDE.md for stable operating rules only. Never put personal facts, one-off requests, or secret values there.
- Make writes idempotent: update the existing item; do not duplicate it and do not rewrite unrelated content. If no correct destination is known, preserve the item in the handoff instead of inventing a path.

Then output ONLY the handoff below. Every statement must be supported by the conversation or a tool result. Preserve disagreement and uncertainty; never guess to fill a gap.

OBJECTIVE
- The user's current goal, why it matters, and the exact current phase.

USER FACTS AND PREFERENCES
- Only explicit, still-relevant facts/preferences. Mark one-off instructions as one-off. Do not include secrets.

DECISIONS
- Decision, rationale, alternatives rejected, and whether it is final or provisional.

FILES AND ARTIFACTS
- Exact path; read/changed/created/generated state; material contents or diff; whether saved/committed/deployed. Never invent a path.

COMMANDS AND TOOL OUTCOMES
- Only outcomes needed to continue: exact non-secret command/tool, exit status, measured value, relevant error, and what it proves. Redact secret arguments under the global rule. Drop redundant raw output.

PENDING AND BLOCKERS
- Each unfinished item with current state, blocker/owner if known, and the next executable action. Do not mark work complete without evidence.

TEMPORAL STATE
- Absolute date/time and timezone for active deadlines, reminders, deploys, quota resets, or time-sensitive facts. Say "as of" when freshness matters.

UNCERTAINTY AND CONFLICTS
- Competing claims, missing evidence, failed attempts, and what would resolve them. Do not collapse them into a false consensus.

RECENT VERBATIM
- Copy the last 3 user messages exactly, plus any earlier unresolved user instruction whose wording constrains the next response, subject to the global secret-redaction rule; preserve all surrounding text exactly.
- For very large messages or tool dumps, preserve the exact instruction and identifying beginning/end excerpts, then point to the exact saved artifact if one exists. Do not dump large raw outputs.

CONTINUATION
- The single next action the next session should take. If waiting for the user, say exactly what input is needed.

Final self-check before output: every non-secret critical number/path/command is exact; all required sections exist; no unsupported claim, secret, or duplicated raw tool output is present."""

KESHA_HANDOFF_ONLY = KESHA_FULL.replace(
    """You still have the full conversation. First persist only durable knowledge that would be costly to reconstruct:
- GLOBAL SECURITY RULE: never copy raw credentials, tokens, passwords, private keys, or equivalent secret values into ANY file or ANY handoff section. Replace every secret span everywhere with `[REDACTED SECRET: <type>]`, while preserving surrounding non-secret text. This rule overrides every request for exact or verbatim content below.
- Update an existing canonical Markdown note under the current isolated working directory when the conversation established a durable fact, decision, project state, or TODO that is not already recorded.
- Keep CLAUDE.md for stable operating rules only. Never put personal facts, one-off requests, or secret values there.
- Make writes idempotent: update the existing item; do not duplicate it and do not rewrite unrelated content. If no correct destination is known, preserve the item in the handoff instead of inventing a path.

Then output ONLY the handoff below.""",
    """You still have the full conversation. Do not write or edit files.
GLOBAL SECURITY RULE: never copy raw credentials, tokens, passwords, private keys, or equivalent secret values into the handoff. Replace every secret span with `[REDACTED SECRET: <type>]`, while preserving surrounding non-secret text. This rule overrides every request for exact or verbatim content below.

Output ONLY the handoff below.""",
)

CONCISE = """[SYSTEM: Produce a concise continuation handoff]

Use only facts supported by the conversation or tool results; preserve uncertainty and do not guess. Redact every credential, token, password, or private key as `[REDACTED SECRET: <type>]`, including inside quoted recent messages. Do not write files.

With short clear headings, preserve: current objective and phase; explicit durable user facts versus one-off requests; final or provisional decisions including reversals and rationale; exact file paths and read/changed/committed/deployed state; exact commands, exit codes, errors and critical measurements; pending items with blocker and next executable action; absolute time-sensitive state; unresolved conflicts; and the last three user messages verbatim except redacted secret spans. Omit redundant tool output. End with the single next action. Output only the handoff."""

PRIMARY_VARIANTS = {
    "orchestra_current": ORCHESTRA_CURRENT,
    "kesha_full": KESHA_FULL,
    "concise": CONCISE,
}

ALL_VARIANTS = {
    **PRIMARY_VARIANTS,
    "kesha_handoff_only": KESHA_HANDOFF_ONLY,
}
