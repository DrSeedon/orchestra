# V-1029 — hub routing policy

Updated only the MultiCode hub bullet in `.orchestra/pipelines/default/prompts/modules/model-routing.md` and corrected the existing Unreleased changelog entry. The policy now records the owner's 2026-10-22 18:30 KRS decision in English, without quotes: Orchestra alone owns routing; the effectively unlimited hub uses `hubsol` for any work regardless of remaining pool and when our own subscription gate closes; hub Sonnet/Opus serve important creative work or a user request for that model. The known-heavy Opus restriction is explicitly confined to our own pool. The project-specific exception was removed.

Preserved `model_reason` enforcement (including the existing Haiku mechanism), persistence/display, whole-pool window admission, unknown-account handling, provider-limit notification, remote-copy/merge lifecycle, and the sensitive-data boundary. No runtime, database, quota-gate or model-catalog code changed.

Inspected test references across the supplied `tests/` tree. The `test_model_routing_reaches_only_spawn_capable_roles` method in `tests/test_default_pipeline.py` derives module text and bullets dynamically to verify delivery, duplication and role isolation; it does not freeze routing prose. No prompt wording test needed deletion and no tests were changed.

Verification:

- Attempted `uv run --offline --frozen python -m pytest tests/test_default_pipeline.py -q` with task-local cache/temp directories and nice=15. Exit 127: no executable uv behind the hub shim. Exact stderr is in `pytest.log`.
- This supplied partial copy also lacks `app/pipeline.py`, `.orchestra/pipelines/default/pipeline.yaml`, and `scripts/check_instruction_contract.py`, so real pipeline assembly and instruction-contract checks cannot run here. No `app` was imported; an imported-app path cannot be reported.
- Executed offline Node structural checks for both changed files: final newline, no trailing whitespace, no merge markers; routing wrapper remains balanced and unique. All passed (`structure-check.log`).
- Reviewed the edited text against the supplied decision and retained protections. Credential-shape scan over changed documents and task artifacts returned no matches (complete scope: the two changed documents and this task directory).

Caller/old-data/recovery risk is limited to prompt interpretation: own-pool restrictions and all executable state stay unchanged. Runtime gate behavior and assembled prompts remain unverified; run the existing pipeline tests in the complete repository. No provider calls or service changes were made.

This hub copy has no `.git`; the hub-worker contract prohibits commit/push and assigns committing to the platform. Suggested commit header: `#V-1029: align hub routing with owner decision`.
