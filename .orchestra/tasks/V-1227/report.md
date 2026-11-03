# V-1227 — Unslop steps in html-artifacts

Owner 02.11 18:47 КРС: «давай» — on the proposal to add the useful Unslop steps to the existing
`html-artifacts` skill (research V-1226).

## Changed files
- `.orchestra/pipelines/default/prompts/skills/html-artifacts.md`, the canonical source
  (`app/prompting.py:_SKILLS_DIR`), edited inside the existing sections:
  - *Established appearance*: polishing an existing artifact keeps its functions, actions, data and meaning, a screen that
    already works, the light default, design system, user palette, density and emoji. Removing a button is not a
    visual fix, and polish is not a redesign.
  - *Check and deliver*: a short audit (issue → file/selector → desired result), a scope chosen from the actual defects
    (none / targeted / full pass), no invented "before" for new artifacts, no separate audit file for small fixes, and
    no extra approval round. After the render, recheck the same list and name anything unfixed or untested.
    It asks for contrast and focus checks in the real render next to the narrow and reduced-motion checks.
  - *BASIS*: attribution to heydamir/unslop, Damir Sokolovsky, pinned `a6f121eee5f29c2f74976b75456feae8b66afb3a`,
    the source URL, CC BY 4.0 plus the licence URL, a list of changes, and the owner decision of 2026-11-02 in English.
    The text is our own: nothing was copied verbatim, and no install, dependency or MCP was added.
- `CHANGELOG.md`: one Unreleased entry, because the repo logs prompt/skill changes there (see V-1088).
- No second skill, no copies, no global dotfiles, no new tests. The prompt stays English.

## Checks (runner: provisioned uv 0.11.28, `uv run --frozen`)
`app` was imported from this workspace's `app/__init__.py`. The absolute path is in `raw/app-path.txt` (task-local, git-ignored).

Round 1 (sparse copy without `pipeline.yaml` and `CLAUDE.md`), red, kept as history:
- the 5 test files gave 29 failed and 49 passed, all with `FileNotFoundError: pipeline 'default' not found`;
- the instruction contract failed: `CLAUDE.md` was missing;
- substitute injector byte-compare: green for `.claude` and `.codex`.
The raw round-1 logs stay in this branch's history and in the host's private copy (`initial-*`).

Round 2 (the copy delivered with the real `pipeline.yaml`/roles/modules; `CLAUDE.md -> AGENTS.md` symlink restored in this
working copy only):

| Check | Result | Raw (task-local `raw/`, ignored by `.orchestra/tasks/V-1227/.gitignore`) |
|---|---|---|
| pytest test_unified_html_skill, test_html_scaffold_extraction_1080, test_legacy_pipeline_skills, test_prompting, test_laptop_skill_delivery_572 | **78 passed, 0 failed, 0 skipped** | `.orchestra/tasks/V-1227/raw/pytest-rerun.log` |
| `scripts/check_instruction_contract.py` | **OK** (AGENTS.md is below 16 KiB, CLAUDE.md is a symlink to it) | `.orchestra/tasks/V-1227/raw/contract-rerun.log` |
| `scripts/secret_scan.py` on the changed files | rc 0 | — |
| Trailing whitespace / diff check | clean. No `git diff --check` here (the copy has no .git) | — |

Round 2 text fix: *Check and deliver* now asks explicitly for text contrast and visible keyboard focus in the real render,
alongside the narrow-screen and reduced-motion checks. The earlier claim that the existing checks already covered them is
gone. BASIS links back to https://github.com/heydamir/unslop.

## Activation
The skill is a prompt file. Python and restart are not needed. Each new turn or spawn runs `inject_skills_to_worktree*`,
which copies the canonical file into the worktree's `.claude/skills/html-artifacts/SKILL.md` and
`.codex/skills/...`. The hub copy sends that worktree content as well. A turn that is already running keeps the
version it loaded, and the CLI reads it again on its next turn or session. Requirement: the change must land on main
(merge or push — yours) on the host where the agent's worktree is created.
