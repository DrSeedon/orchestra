<code-quality>
## Code quality

Check current code and discoverable facts first. Prefer the simplest complete solution
within the task; challenge a faulty premise with evidence. Reuse existing code or the
standard library before adding an abstraction or dependency. Follow surrounding style;
comments explain non-obvious reasons. Do not reformat neighbors or remove unrelated dead code.

### Evidence and data

Batch independent read-only diagnostics with bounded output; keep dependent operations,
mutations and retries sequential. Preserve actual output for evidence.
For approved external-data collection, retain complete source records and fields in the
appropriate storage and apply business filters at display/query time. Narrow at source
only for an actual source restriction or measured resource limit; state lost coverage.
Completeness never overrides privacy, retention limits or permission to collect the data.
Evaluate candidate licenses against the project's real use and record restrictions.
Media research needs actual authorized samples as well as public demos; vendor scores
alone do not establish local quality.

### Resource failures

For Killed/exit 137, inspect the process cgroup's memory.max/current/events as well as host
memory before diagnosing code. Reduce concurrency/data footprint or report the resource
blocker. Do not change service limits, delete data or move processes to another cgroup
to evade the limit. Use project resource wrappers and protect the platform from test OOMs.

### Tests and code intelligence

Use rg for literal occurrences; use task-local AST analysis for Python reachability and
registries. LSP/Serena is optional for static symbol changes; check strings, templates and
configuration too. A zero search result alone does not prove code unreachable.

Test stable behavior: integrity, authorization, accounting, lifecycle, concurrency,
recovery and external contracts. Reproduce a defect or identify the exact contract before
claiming a regression is protected. A test should fail when the defect is reintroduced;
reported mutations need durable regression tests in the delivered diff, not throwaway probes.
Delete as unreachable only with a production-root proof and appropriate regression evidence.

For editable prompts/docs, test delivery, assembly, role isolation and source ownership
rather than editorial phrases. Preserve existing frozen structural anchors and acceptance
tests. If a frozen contract is wrong, report evidence and request revision; do not delete
it to pass. Keep checks meaningful and proportional to the changed behavior.

### Explicit, visible behavior

Keep state and policy with one owner, flow readable and errors visible. Fail an unsafe
operation at its boundary; optional metadata or bookkeeping must not crash an independent
safe path. Test both refusal and allowed behavior when adding a gate. Do not turn a small
change into a speculative framework or a second implementation of an existing contract.
</code-quality>
