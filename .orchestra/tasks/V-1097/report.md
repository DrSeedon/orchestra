# V-1097 — forwarded-source application reporting

Implemented the approved reporting rule in the existing research-reply section of
`.orchestra/pipelines/default/prompts/roles/orchestrator.md` (+18/-0 lines).
Added one handwritten entry to `CHANGELOG.md` (+1/-0 lines). Read the role and
knowledge, orchestration, research-method, communication-style, report-format,
project-maintenance and relevant code-quality instructions before editing.

Reading order: the added owner decision in `roles/orchestrator.md`, then unchanged
`modules/research-method.md` for evidence standards and `modules/orchestration.md`
for implementation authority. The existing research-reply section is the reporting
owner; no new module, registry entry, required artifact or long report format was added.
The assembly registry and application source are not included in this partial copy;
their runtime behavior was not inspected or changed.

The rule maps each relevant idea in a forwarded tool/article/approach to a concrete
location/use in current Orchestra, checked against code and existing rules, followed
by an adoption verdict and reason, importance, benefit, transfer cost and validation.
It records the 2026-10-27 owner decision with an English summary and reason, without
the private quotation. AGENTS.md and personal memory were not changed.

Manual review covered the plausible reporting mistakes: an existing mechanism must
be identified as already present; unavailable code cannot establish absence; an
unmeasured benefit uses `not measured` and a qualitative assessment/check; a measured
percentage identifies metric, baseline and evidence; vendor benchmarks remain
external claims; priority is not measured improvement; an adoption recommendation
and a quoted install prompt grant no implementation authority. These are prose
review cases, not executed model evaluations or behavior tests. No persisted state,
callers or recovery paths change, and no tools were installed or models invoked.

## Actual checks and limits

- Provisioned runner: exported
  `PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"`;
  `uv --version` returned `uv 0.11.28 (x86_64-unknown-linux-gnu)`.
- Ran `uv run --frozen python scripts/check_instruction_contract.py`.
  **Exit 2:** the required script is absent. uv successfully created default `.venv`
  using CPython 3.12.3 and installed the locked dependencies. The output is in
  `instruction-contract.log`, sanitized only by replacing the raw hub workspace path
  with `<HUB_WORKSPACE>`; the byte-for-byte original was privately preserved by root.
  No alternate interpreter/check was substituted.
- Ran inline document-hygiene checks with `uv run --frozen python`: **exit 0**.
  `validation.log` records no Cyrillic/trailing whitespace in added prompt text,
  preserved role wrappers, and unchanged SHA-256 hashes of AGENTS.md and the four
  initially inspected canonical modules. AGENTS.md remains 16,356 bytes.
- Inspected the complete two-file source diff and added text for secrets; no source
  logs or credentials were copied. No literal-wording tests were added.
- No pytest run or imported `app` path: `app/` and `tests/` are absent. Assembly was
  not changed; existing prompt-delivery mechanics tests are unavailable here.
- Git metadata is absent by worker design. No commit, push or clean-index claim;
  the platform owns sync-back/commit on `task-V-1097/rules-news-application`.

Open verification: run the instruction contract in the full checkout before
acceptance. End-to-end prompt delivery and actual agent compliance remain unverified.
