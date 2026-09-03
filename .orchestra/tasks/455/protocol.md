# #455 — preregistration of the simplification measurement

Frozen before the call-graph/clone metrics were run.

## Question and outcomes

- Context: successful worker/full-cycle merges recorded for scope
  `/mnt/data/Projects/Python/orchestra`.
- Change under test: the delivered prompt clause `200 lines where 50 suffice → rewrite` and the
  surrounding minimum-code/no-speculative-abstraction rules.
- Baseline: merges whose task did not explicitly ask for deletion/simplification; counter-arm:
  merges whose task/title explicitly asked to remove, simplify, consolidate, or refactor code.
- Outcomes: newly added production Python lines in statically unreachable definitions; removed
  unreachable lines; newly introduced exact AST block clones; per-file LOC change across repeated
  merges; presence of an executable simplification gate.

Possible verdicts are frozen as follows.

1. `ambient requirement effective`: no manually confirmed dead/clone introduction in the ambient
   cohort and its rates do not exceed the metric's own split-half noise.
2. `ambient requirement not enforced; explicit request works`: at least two independently verified
   ambient merges introduce unreachable/duplicate code above noise, while explicit tasks remove it.
3. `model did not simplify even when asked`: explicit tasks retain or add the same verified defects
   and do not produce a reduction beyond noise.
4. `not measurable`: unresolved dynamic dispatch intersects the candidates, the legal-duplication
   negative control is flagged, or the observed contrast is below the preregistered noise floor.

One counterexample can refute an absolute claim but cannot establish a population rate. Population
claims use the full recorded cohort below.

## Frozen corpus

- Git snapshot: `main` = `dcfb3538214760fe2ceee43e2cd42611c54cd407`.
- Database boundary: `merge_operations.state='SUCCEEDED'`, exact scope above,
  `finished_at <= '2026-09-03T08:44:44.926475+00:00'` (148 rows at freeze time).
- Keep rows whose joined session prompt contains the exact anchor
  `200 lines where 50 suffice` and whose resulting Git commit object exists.
- Structural-rate cohort: rows changing at least 10 lines in tracked `app/**/*.py`; documentation,
  tests, scripts, binary files, merge-only rows, and manual commits outside `merge_operations` are
  excluded. This is a census, not a hand-picked sample.
- A merge is `explicit` only when its frozen task title/description or merge subject explicitly asks
  to remove/simplify/consolidate/refactor production code. Regex hits are exported first and manually
  labelled before structural metrics are opened. Incidental words such as “drop a field” are not
  enough. All other rows are `ambient`.

## AST reachability metric

For each parent/merge snapshot, parse all tracked `app/**/*.py` without importing the application.
Every module body is a production root, which deliberately over-approximates reachability. Decorated
definitions and dunder methods are also roots. Resolve direct names through module imports/local
definitions; resolve attribute calls conservatively to every definition with the same terminal name;
count function/class objects passed or stored as edges; connect class construction to `__init__`.

`getattr(obj, "literal")` and finite literal sets assigned to the name argument add call edges.
Every non-literal/unresolved `getattr` is reported separately with file and line. A would-be dead
definition whose name appears in non-Python tracked application/config text is excluded from the
confirmed set. Protocol/ABC/overload definitions and decorated definitions are not dead candidates.
A dead cluster must have no path from any root in this deliberately over-approximating graph; grep
counts are never a verdict.

Per merge:

- denominator: added lines in tracked `app/**/*.py`;
- `dead_added_lines`: added-line positions lying inside after-snapshot unreachable definitions;
- `dead_removed_lines`: deleted-line positions lying inside before-snapshot unreachable definitions;
- rate: `dead_added_lines / app_python_additions`.

Pilot correction, frozen before the full run: an added definition may be intentionally staged in an
early ticket and connected by a later ticket. Therefore `dead_added_lines` is retained as an immediate
diagnostic, while the load-bearing metric is `persistent_dead_added_lines`: the same stable
`module:qualname` remains an unreachable candidate at frozen `main`. A candidate that becomes reachable
or disappears by frozen `main` is reported as `resolved_later`, not charged as residual dead code. This
correction was triggered by pilot commit `d19f68cfce` (#315 T1): 234 immediate candidate lines in schema
definitions that later tickets were expected to wire.

Post-run validity correction before accepting any result: the first full candidate table exposed the
live import `from app.portfolio_watchdog import ensure_task as ensure_portfolio_watchdog` in
`app/main.py`; the original graph resolved the declared name but not `ImportFrom.asname`. That made a
live watchdog cluster look closed. Import aliases are therefore added to the graph and the entire run,
controls, noise, and comparison are discarded and repeated. Only the compact invalidation receipt is
retained; the derivable 637 KB invalid output was removed so it cannot be mistaken for evidence.

All non-zero candidates are manually checked against the exact diff, imports, decorators, runtime
registries, and unresolved computed `getattr` sites before the word “dead” is used.

## Exact clone metric and controls

The clone detector hashes location-free AST for windows of at least four consecutive executable
statements within the same statement list. A clone requires the same hash in at least two distinct
locations. Imports and windows made only of control terminators are excluded. A merge introduces a
clone when the occurrence count increases from parent to merge; overlapping windows are collapsed to
unique source lines before computing `clone_added_lines / app_python_additions`.

Negative control (real code): the three-line transaction cleanup
`except Exception: / conn.rollback() / raise` appears repeatedly in current `app/tm.py` (the handler
body contains two AST statements). The detector must return zero windows for that exact three-line
block. Positive control: two scratch function bodies with four identical executable statements must
produce one clone group. Either control failing
invalidates the clone metric.

## Noise before comparison

1. Instrument noise: run the same current-snapshot AST analysis three times and require byte-identical
   JSON after removal of timestamps (expected deterministic spread: zero, but it is measured).
2. Sampling noise: before comparing explicit and ambient cohorts, make 1,000 seeded (`455`) random
   equal split-halves of the ambient cohort. For each metric record the absolute difference of weighted
   rates between halves. The median split-half difference is the decision floor; a cohort contrast
   smaller than that is “no measured contrast”, not a small improvement. The p95 is also reported.

## File growth

For each production Python file touched by at least five included merges, record initial-parent LOC,
final LOC after its last included merge, number of touches, additions, deletions, and which deltas came
from explicit tasks. Growth is descriptive only: it becomes simplification failure only where the AST
reachability/clone metric identifies removable structure. Feature growth alone is not labelled bloat.

## Gate check and cost accounting

Search the merge/admission owners (`app/workspace.py`, `app/diff_budget.py`,
`app/merge_operations.py`, `app/mcp_stdio.py`, `scripts/`, and their tests) for the prompt anchors and
for complexity/dead-code/clone tooling. A delivery-only prompt test and the 2,000-insertion ceiling are
reported separately from a simplification oracle.

Cost estimates are expressed in model turns, not dollars: deterministic check embedded in an existing
merge attempt = zero extra model turns; a separate reviewer/agent judgement = at least one extra model
turn and is not a mechanical predicate.
