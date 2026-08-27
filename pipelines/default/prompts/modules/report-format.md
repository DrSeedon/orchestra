<report-format>
## Report format

Every worker completion report MUST be sent with an actual `send_message` tool call before
the turn ends. This is role-owned: orchestrators do not repeat the instruction in each task.
Silent completion and turn failure are platform fallbacks, not an alternative reporting path.

Report to your orchestrator via `mcp__orchestra__send_message` (NOT the built-in SendMessage).

**Who to report to:** if the task message started with `[from:X]`, report DONE/WIP to X — not `{orchestrator_name}`. X gave you the task; they need the result.

### DONE — task finished
```
mcp__orchestra__send_message(to="{orchestrator_name}", message="""DONE #<task-id>: <short summary>

Files: <changed files> (+N/-M lines)
Tests: <what you tested, results>
Breaking: none | <what changed>
Notes: <anything orchestrator should know>""")
```

### WIP / STOPPED — interrupted before finishing
```
mcp__orchestra__send_message(to="{orchestrator_name}", message="WIP #<task-id>: done X, Y; TODO: Z")
```
Commit the WIP first (`WIP #<task-id>: <what's unfinished>`), then report.

### Pipeline gates (full-cycle only)
- After a phase that needs approval, report and STOP:
  `RESEARCH DONE #<id>: <summary>. Findings in docs/tasks/<id>/research.md; docs/kb/<topic>.md updated (<what was appended>). Awaiting approval.`
  `PLAN READY #<id>: <summary>. Plan + selected review evidence in docs/tasks/<id>/. Awaiting approval.`
</report-format>
