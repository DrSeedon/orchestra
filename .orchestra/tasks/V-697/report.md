# V-697 — English prompt rules

## Result

All rule prose in `.orchestra/pipelines/default/prompts/` is now English. The owner-decision
format is now `owner decision, <date>` with an English summary and reason; owner wording is not
quoted verbatim. `modules/project-maintenance.md` explicitly tells future authors to use that
summary form. The review-frozen state of `codex-debate` remains unchanged, but its text is now
English.

The translation touched the 18 prompt files named by the task and the explicitly required
`modules/project-maintenance.md` (19 prompt files total). The two brittle literal-wording tests
that failed after translation were changed to test mechanics instead: HTML profile properties and
role delivery/isolation. No runtime or external contract was changed.

## Checks

The instruction contract check passed:

```text
Instruction contract OK: AGENTS.md below 16 KiB, CLAUDE.md is a symlink to it
```

The requested focused test command initially found three stale wording/source assumptions. After
the prompt and test corrections, the targeted failing tests passed:

```text
21 passed in 6.23s
```

The full required command ran as durable job `bg-773c01cc3e` and passed:

```text
346 passed, 9 skipped, 3844 deselected in 46.14s
```

`git diff --check` is clean.
The test process imported the worktree application from
`/home/kesha/orchestra/worktrees/home-kesha-orchestra/prompt-engineer/app/__init__.py`.

## Remaining Cyrillic and why it is allowed

The acceptance grep leaves only these material strings:

- `skills/laptop-access.md:130` — the actual directory name `Рабочий стол` in the recorded laptop
  path; translating it would change a filesystem path.
- `skills/explainer-video.md:34–35` — Russian `say` examples used to explain Vosk input.
- `skills/explainer-video.md:69–70` — Russian `say` values in the Manim example scene.
- `skills/explainer-video.md:89` — `\text{запись}` in a Russian LaTeX example.
- `skills/explainer-video.md:128,132,135–136,152` — Russian stress, homograph, name, and number
  examples used by the Russian-voice instructions.

No Cyrillic remains in rule prose, headings, owner-decision summaries, descriptions, comments,
UI labels in the HTML motion scaffold, or role/module policy text.

## Translation boundaries and uncertainty

The only intentionally non-literal choices were owner-decision quotations, which became dated
English summaries per the task, and the two test rewrites required by the project rule against
literal prompt tests. Technical identifiers, commands, paths, measurements, task numbers,
model names, and source links were preserved. The translated skills were not executed as video,
HTML, or laptop operations; their runtime behavior remains covered only by the existing prompt,
skill, and pipeline tests.
