<report-format>
## Report format

Report to your orchestrator via `mcp__orchestra__send_message` (NOT the built-in SendMessage).

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
  `RESEARCH DONE #<id>: <summary>. Findings in docs/tasks/<id>/research.md. Awaiting approval.`
  `PLAN READY #<id>: <summary>. Plan + Codex review in docs/tasks/<id>/. Awaiting approval.`
</report-format>
