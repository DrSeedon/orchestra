# V-895 — frozen protocol (committed before any model run)

Question: does rewriting the task with Rieseberg's "deeper version" prompt before executing it raise the share
of results accepted against a reference, and does it inflate paid tokens (V-666 risk)?

Tasks (reference = the real past fix; snapshot = parent commit of that fix, `app/ scripts/ pyproject.toml` only):
open O1 V-753 (tg-topic toggle), O2 V-814 (schema retries / budget label), O3 V-841 (log snapshot limit),
O4 V-817 (raw file link after worktree removal); closed C1 a43f2686 (timer expiry), C2 16ebb5e1 (git decode),
C3 7111f3c2 (precompact floor), C4 9fdd0499 (cron_command limit). Prompts: tasks.py (arm A text).
Substitution vs the brief: V-854 had no report in .orchestra/tasks, replaced by V-814 (has report).

Answer isolation: each run gets a fresh copy of a snapshot in its own directory — no .git, no .orchestra, no
CHANGELOG/TODO/tests, so no report or fix text exists in the tree; the fix itself is absent from the code. Network
off, MCP off. A prompt line tells the model to stay inside the directory (reads outside are not technically
blocked for Codex); raw output is scanned for `.orchestra/tasks` and the fixed task ids, and flagged runs are
reported (and excluded in a sensitivity check).

Accept rule (frozen): open = regex groups in tasks.py OPEN_RULES on the final answer (<=1800 chars); closed =
hidden pytest in hidden/ on the edited tree. validate_oracle.py: closed tests fail on the snapshot and pass on the
real fix; open rules accept a reference answer and reject a decoy. Scoring is a script, hence blind to the arm.

Arms: A original prompt. B same model first rewrites the prompt with the Rieseberg prompt (verbatim below), then
executes ONLY the rewritten prompt (rewrite cost counted in B). C original + one sentence requiring to name an
external check (tasks.py C_SUFFIX). Models: luna, sonnet (Sonnet 5.5). One run per cell, 48 runs; subscription
billing only. Tool sets are those of scripts/wf_adapters.py (Claude: Read/Write/Edit/Glob/Grep, no shell; Codex:
shell, workspace-write sandbox) — fixed across arms within a model.

Rewrite prompt (verbatim from the skill / blog, plus a task envelope):
"I want a deeper version of this task, not a bigger one. Before rewriting it: (1) say what a top professional in
this field would do here that I'm not asking for; (2) name the rawest material they would start from instead of
what has already been digested for me; (3) name the specific methods and tools they would use; (4) say what, other
than you or me, would show the result is right. Then rewrite my prompt to ask for exactly that."
Envelope: the task text, then "Answer the four questions, then give the rewritten prompt in a single fenced block.
Keep the same goal and the same final-answer format." The rewriting step may read the snapshot (read-only tools).

Metrics: accepted (0/1); paid tokens = output + cache_create + fresh input (Claude input_tokens; Codex
input - cached - cache_write); cache read excluded (KB V-660); turns = Claude num_turns, Codex count of completed
items of command/tool type (+1 for the final message). For B all of rewrite + execution are summed.
Decision rule (from V-893): take B if open-accepted(B) >= open-accepted(A) + 2 of 8 (4 tasks x 2 models), paid
tokens(B) <= 1.2 x paid tokens(A) and no regression on closed. C vs A reported separately.
Statistics: exact paired comparisons (McNemar exact / sign test) on cells, bootstrap CI on token ratio. With 8
open cells a difference of +2 is not significant by itself (exact one-sided p>=0.25 for 2-0); this is stated
in the verdict.
