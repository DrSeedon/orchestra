<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently, a green oracle still cannot chmod a file 😏 The T1–T3 acceptance scripts pass, but #417 is not ready because the validator has several bypasses and its documented command cannot execute.

Verification:

- T1, T2, T3 acceptance scripts: all `PASS`.
- `uv run python -m pytest -q tests/test_kb_markdown_contract.py`: `22 passed`.
- Direct documented validator command: `zsh: permission denied`, exit `126`.

## Findings

### blocking

1. **`blocking:` Validator command is not executable.**  
   `research-method.md:135-136` instructs agents to run `scripts/check_kb_contract.py` directly, but the diff adds it with mode `100644`. POSIX execution fails before validation; acceptance tests invoke it through Python and therefore miss this. Commit the executable bit or document `python scripts/check_kb_contract.py ...`.

2. **`blocking:` Forward-only fact deletion/rewrite is not enforced.**  
   `scripts/check_kb_contract.py:252-299` validates only added lines. A deletion-only fact diff, or replacing a structured fact with an ordinary legacy bullet, returns no errors, allowing canonical facts to be removed or rewritten despite the append-only contract.

3. **`blocking:` Added content can masquerade as a diff header and disable validation.**  
   `scripts/check_kb_contract.py:203-228` processes any `+++ ` line as a file header even inside a hunk. An added content line such as `++ /dev/null` becomes `+++ /dev/null`, clears the current path, and causes subsequent invalid fact lines to be skipped.

4. **`blocking:` Empty evidence is accepted.**  
   `scripts/check_kb_contract.py:246-248` checks only for the substring ` · evidence:`; `evidence:` with no value passes. This allows ungrounded facts into canonical memory.

5. **`blocking:` Approval receipts are accepted from arbitrary task artifacts.**  
   `scripts/check_kb_contract.py:325-347` restricts receipts only to `docs/tasks`, so a matching tuple in `research.md` or another unapproved artifact is accepted. This conflicts with the approved-plan requirement and allows a candidate link to be promoted without a receipt in an approved ticket/plan.

## Verdict

**CHANGES REQUIRED.** Prompt delivery and tool-surface checks are green, but the validator’s documented execution failure and integrity bypasses block approval.

## Round (2026-08-30T09:32:57Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently, one more edge case survived the validator’s own tests 😏 Four Round 1 blockers are fixed; receipt provenance remains partially bypassable.

## Findings (blocking/suggestion/question)

### blocking

- **FIXED — Direct CLI:** `new file mode 100755` is present and `scripts/check_kb_contract.py --help` exits 0.
- **FIXED — Deletion/rewrite:** removed lines are tracked and same-key replacements are required; regression tests pass.
- **FIXED — Header masquerade:** hunk ranges are consumed before header parsing; regression test passes.
- **FIXED — Empty evidence:** empty extracted evidence is rejected; regression test passes.
- **STILL BROKEN — Receipt provenance:** `scripts/check_kb_contract.py:325-331` checks only `receipt_part.name == "plan.md"`, not the required `docs/tasks/<id>/plan.md` shape. A receipt at `docs/tasks/plan.md` is accepted, allowing a non-ticket plan artifact to authorize a canonical link.

### suggestion

None.

### question

None.

Verification:

```text
T1 PASS: file-first protocol delivered; knowledge retired; search_memory preserved
T2 PASS: changed facts require stable key, literal search anchors, and evidence
T3 PASS: only approved, typed, existing-target one-hop links enter canonical KB
29 passed in 2.04s
```

## Verdict

**CHANGES REQUIRED.** The implementation is otherwise green, but the remaining receipt-path bypass still permits unauthorized canonical links. It’s a `plan.md` wearing the wrong task number—apparently that counts as paperwork.

## Round (2026-08-30T09:35:49Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

Apparently `plan.md` now needs an actual task attached to it 😏 The Round 2 blocker is fixed, and no new blocking issue was found at this seam.

## Findings (blocking/suggestion/question)

### blocking

- **FIXED — Receipt provenance.** The validator now requires exactly `docs/tasks/<numeric-id>/plan.md`, with IDs matching `[1-9][0-9]*`. The regression creates a matching receipt at `docs/tasks/plan.md` and rejects it; the supplied mutation also confirms the guard is effective.

### suggestion

None.

### question

None.

## Verdict

**APPROVED.**

T1/T2/T3 pass, `tests/test_kb_markdown_contract.py` reports `30 passed`, and sessions remain `564 → 564`.

Evidence from the reviewed diff:

```text
+        or re.fullmatch(r"[1-9][0-9]*", receipt_parts[2]) is None
```

`plan.md` without a task ID is finally treated like a guest without a passport.
