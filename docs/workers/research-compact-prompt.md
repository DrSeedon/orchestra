# Worker memory

- Claude CLI `429 You've hit your monthly spend limit` with
  `duration_api_ms=0` and cost `$0` can mean the 5h window is exhausted while
  supplemental capacity is disabled, not a payment limit. Before classifying
  it, check `/api/usage` → `anthropic.five_hour` and `extra_usage`.

- A preregistered analysis script must never be edited to work around a missing
  input. When one of two judges was unavailable, `analyze_results.py` refused to
  run. The right move is to **import** its bootstrap/CI functions from a separate
  script (identical seeds and math, lock hashes stay intact) and report the
  gate as UNDECIDED — not to patch the locked file. Re-verify all locked source
  hashes both before AND after the run.

- Before implementing an assigned fix for a judge/eval finding, open the RAW
  flagged outputs and the fixture. In #106 Q5, 3 of 5 "hallucinated read" flags
  were TRUE statements: the harness seeded the file on disk and passed
  `--tools Read`, but the ledger shown to judges is built only from the fixture
  transcript, so a live tool call is structurally invisible. Fixing the prompt
  would have "fixed" correct behaviour. An eval that cannot represent a true
  action will fail any candidate that performs it.

- A run that exits non-zero may still have completed all its paid work. A
  `pregate` crash on the manifest write happened AFTER all 18 generations
  succeeded; blindly re-running would have burned the spend twice. Check the
  results file (row count, `ok`, balance) before resuming or restarting, then
  write the missing artifact post-hoc with a note.

- `claude -p --output-format json` returns ONLY the final result — tool calls are
  invisible. To capture what the model actually did, use
  `--output-format stream-json --verbose` and read `type=assistant`
  → `content[].tool_use` plus `type=user` → `content[].tool_result` (ids pair
  them). Needed whenever an eval must PROVE an action happened; a file diff
  cannot, since reads mutate nothing.

- When probing whether a fix works, pick a fixture that RELIABLY triggers the
  behaviour. Two probes showed "0 events captured" and looked like a broken
  parser — the model had simply chosen not to call tools (`num_turns=1`). Q5
  actuals showed tools used in only 72/132 runs. Check the turn count before
  blaming the code.

- Before shipping a prompt an experiment validated, diff the SHIPPED text against
  the TESTED text token by token. #106 Q6: the tested prompt said "the runtime
  will append a redacted user tail and ledger" — true only because the harness
  called `compose_handoff()`. Production has no such appender, so the measured
  100% recent recall came from the harness, not the prompt. Ship the sentence
  verbatim and it promises a block that never arrives. Any harness-side machinery
  a prompt refers to must either be ported to production or the claim rewritten —
  and the gap stated where the numbers are quoted.

- When a locked source genuinely must change mid-experiment (stale constant that
  makes a validator unpassable), do NOT rewrite the lock file — that destroys the
  evidence anything changed. Amend the file, leave the lock as-is so the hash
  check reports drift, and write a dated `lock-amendment-NN.md` stating the diff,
  the reason, when it happened relative to generation/judging, and which gates it
  touches (ideally none). Drift on exactly one documented file is honest; a
  silently regenerated lock is not.

- A long command started inside my own turn DIES when the turn ends, even when
  the harness says "moved to background, you will be notified". That notification
  never comes and no wake is scheduled. Cost: 45 of 126 paid generations lost
  mid-run. For anything over ~10 minutes use
  `bg_create(type="run", command=..., timeout_seconds=...)` — it lives on the
  server and wakes me on completion. Then END THE TURN; do not poll.

- Renaming a corpus does not renew it. Copying `q5/` to `q6/` and sed-ing the ids
  gives fixtures that were ALREADY used to select the winner — measuring on them
  inflates the effect. Say so before anyone funds the round. Also: a fixture id
  appears in more places than the corpus file (mode selectors in
  `run_evaluation.py`, hardcoded ids and literals in tests, `SOURCE_FILES`), so
  grep for the old id across all `.py` after any rename.

- When summarizing a finished multi-round experiment for a reader, the numbers
  must carry their PROVENANCE, not just their value. #106's headline (+75.66 pp
  recent recall) is true on the harness and unguaranteed in production; a summary
  that lists it beside the shipped wins silently upgrades it. Split "what runs in
  prod" from "what was measured on the bench" as a visible structure the eye hits
  first, not a footnote — the same gap was already documented in `rollback.md`
  and would still have been mis-read from a flat metrics table.

- A teaching artifact must attribute each prompt rule to the metric it actually
  moved, and say so explicitly where no such metric exists. In #106 five of six
  rule changes map to a measured Q6 number (file-write condition → 218→0;
  both-polarity ban → 8→0; four typed sections → +7.74 pp; compactness → −61.4%;
  verbatim tail → harness-only), but the `UNKNOWN — source gap` rule was never
  isolated — it shipped inside the bundle. Writing "part of the general gain"
  there would be invention. The tutorial format pushes hardest toward exactly
  this kind of tidy causal story; resist it per-row, not in a global disclaimer.

- When quoting a prompt/config verbatim into a document, verify the embedded copy
  against the real source programmatically before shipping — unescape the HTML
  and assert every quoted line is a substring of the file. Hand-copied blocks
  drift silently, and a doc that misquotes the artifact it explains is worse than
  no doc. Also confirm WHICH commit holds the "old" version: my swap commit
  `8b5392d` and its squashed merge `f796a08` are different SHAs for the same
  change, so `^` on the wrong one yields the wrong parent.

- `~/.claude/projects/**/*.jsonl` is a free, tier-1 telemetry corpus for any
  question about real Claude behaviour: every assistant record carries
  `message.usage` with `cache_read_input_tokens` / `cache_creation_input_tokens`,
  and `{"type":"system","subtype":"compact_boundary"}` marks NATIVE compactions
  with `compactMetadata.trigger/preTokens/postTokens/durationMs`. Orchestra's own
  compacts are findable by the `PREVIOUS CONTEXT SUMMARY` preamble. Measure before
  theorizing — this answered #126 with 0 paid calls. Grep for the string alone
  matches my own file-reads of source code; assert on the parsed
  `subtype`/`type` field instead.

- Restating an assigned premise as a finding is the failure; check WHICH BRANCH a
  line sits in. In `compact()` the orchestrator read
  `self.session_id = pre_compact_session_id` as "the id is restored", but all
  three occurrences are failure paths (retry, ack timeout, quota). The success
  path does the opposite via `_ensure_backend(force_fresh=True)` →
  `resume_session_id=None`. A line's meaning is its control flow, not its text.
  **Symmetrical trap, same task:** I then accepted a neighbour's "the system
  prompt is never passed after compact" without checking the ack-turn branch —
  where `force_fresh=True` makes it a COLD START that does get the prompt. Trace
  the path to its end, not to the first branch that confirms the diagnosis;
  a correction can be right about the defect and wrong about where it fires.

- A measurement proving the CURRENT path is safe is not evidence for a NEW path.
  #125 measured `cache_read=0.889` on the inject turn (append-to-tail keeps the
  prefix) and offered it as the argument for sending `system_prompt` on every
  resume — a different operation nobody had measured, and one that risks
  invalidating the whole prefix on every reconnect. Ask "was this number measured
  on the thing being proposed, or on the thing being replaced?"

- Probe a "tool is unavailable" claim with the EXACT flags the code uses.
  `codex exec` from `/tmp` failed on a trust check (looks like a quota error but
  is not); rerun with the real flags gave the verbatim quota message and reset
  date. Cheap, and it separates "blocked" from "misconfigured".
