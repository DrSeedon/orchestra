# V-1080 — animation scaffold source path

Changed only the extraction-source wording and native default paths in the canonical
`html-artifacts/references/animation.md`: the motion-template fence lives in that
reference, not in the injected `SKILL.md` entrypoint. Both `.claude` and `.codex`
examples now point to `references/animation.md`. Added one minimal Unreleased fix entry.
Preserved the V-1078 Fixed line titled "Narrow log searches avoid sorting full log
payloads and blocking the API" verbatim from the public main CHANGELOG; it was absent
from this older hub copy. No generated skill copies or injector implementation changed.

The new `tests/test_html_scaffold_extraction_1080.py` injects the real skill for each
native home, reads the shell recipe and that home's default source from the delivered
reference, substitutes the documented placeholder, and executes the recipe offline.
It checks the complete extracted HTML bytes against the canonical fenced payload,
the doctype and document ending, and HTML, style, script and SVG elements. The working
directory includes spaces. Removed all assertions on internal player IDs and control
names, together with the unused parser element map. Assertions cover extraction and
the complete copy, not prompt phrasing or internal naming. No browser or JavaScript
runtime execution was needed.

All test shells used:

```sh
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
export TMPDIR="$PWD/.orchestra/tasks/V-1080/tmp"
nice -n 15 uv run --frozen python -m pytest tests/test_html_scaffold_extraction_1080.py tests/test_unified_html_skill.py tests/test_laptop_skill_delivery_572.py tests/test_instruction_contract.py tests/test_manager.py::TestInjectSkillsRealCopy tests/test_manager.py::TestRefreshSkills tests/test_manager.py::TestCodexSkillHome -q
```

Final stdout (also in `pytest-final.log`):

```text
...........................................................              [100%]
59 passed in 12.49s
```

Mutation proof: temporarily restored the original canonical reference, ran only the
new regression with the same frozen uv runner, and restored the fix in `finally`.
Both native variants failed at the HTML doctype assertion after successful awk exit
and empty output: `2 failed in 2.62s` (`mutation.log`). The final combined run above
was after restoration. Existing stale-copy, tracked-copy and native-home injector
checks passed as part of that combined run.

The original and fixed fenced payloads were compared byte for byte, including the
reference's trailing blank line. Extracted scaffold SHA-256:
`753734351f62d77a01c6e2ee7ee90fee5c7d4cad342954d826df252697852b64`.

Imported app, from `uv run --frozen python -c 'import app; print(app.__file__)'`:
`/home/<redacted-for-publication>/orchestra-ws/vmi3407579/hub-6e41d5925f07459e/app/__init__.py`.

Required standalone instruction-contract command was attempted with the same runner:
`uv run --frozen python scripts/check_instruction_contract.py` exited 1:

```text
Instruction contract: CLAUDE.md must be a symlink to AGENTS.md, not a copy: a copy drifts and then one client silently runs on stale rules
```

This provisioned hub copy has no root `CLAUDE.md`; it was already absent before edits.
The 9 fixture-based instruction-contract tests pass, but the repository-wide command
remains unverified beyond this missing-input refusal. Root must rerun it in the full
checkout; no root-file repair or acceptance-test changes were made here.

No provider, browser, API, Telegram, SSH, live database, deployment or restart actions.
Full-suite and rendered playback checks were outside this path-only fix. Existing
sessions receive refreshed references through the normal native skill injection path;
generated delivery files are not a second canonical owner. No old-data migration needed.
