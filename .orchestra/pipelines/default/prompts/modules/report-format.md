<report-format>
## Report format

Every worker completion report MUST be sent with an actual `send_message` tool call before
the turn ends. This is role-owned: orchestrators do not repeat the instruction in each task.
Silent completion and turn failure are platform fallbacks, not an alternative reporting path.

Report to your orchestrator via `mcp__orchestra__send_message` (NOT the built-in SendMessage).

**Who to report to:** if the task message started with `[from:X]`, report DONE/WIP to X — not `{orchestrator_name}`. X gave you the task; they need the result.

**Review:** model review was frozen by the owner on 2026-09-20 — do not call it or seek a
substitute; do not seek repeated approval of unchanged work. Resolve verified blockers. The
report states the actual check result, final commit and remaining uncertainty. Under the
owner decision, 2026-10-23, add a short reading order and classify findings as must-fix /
optional / open question; uncertainty alone does not make a serious risk optional.

### DONE — task finished
```
mcp__orchestra__send_message(to="{orchestrator_name}", message="""DONE #<task-id>: <short summary>

Files: <changed files> (+N/-M lines)
Reading order: <central files, then relevant unchanged callers/config/hooks; why this order>
Tests: <what you tested, results>
Breaking: none | <what changed>
Findings: <must-fix / optional / open question; omit empty categories>
Notes: <anything orchestrator should know>""")
```

### WIP / STOPPED — interrupted before finishing
```
mcp__orchestra__send_message(to="{orchestrator_name}", message="WIP #<task-id>: done X, Y; TODO: Z")
```
Commit the WIP first (`WIP #<task-id>: <what's unfinished>`), then report.

### Pipeline gates (full-cycle only)
- After a phase that needs approval, report and STOP:
  `RESEARCH DONE #<id>: <summary>. Findings, evidence and limitations in .orchestra/tasks/<id>/research.md. Awaiting approval.`
  `PLAN READY #<id>: <summary>. Plan + selected review evidence in .orchestra/tasks/<id>/. Awaiting approval.`
</report-format>
