# #315 — canonical namespace and record schema

This is a concrete proposal, not an implemented contract. Logical URI examples use <code>orch://</code>;
the initial Git layout remains ordinary project files so clone/review/merge continue to work.

## One namespace, distinct contracts

<pre>
orch://project/{project_id}/
├── tasks/{task_uuid}/
│   ├── state.json                 # operational task state; mutable by task facade
│   ├── evidence/refs/*.json       # immutable references, never evidence body
│   └── events/{event_id}.json     # append-only task events
├── knowledge/topics/{topic_slug}/
│   ├── topic.md                   # curated human-readable topic body
│   ├── facts/{fact_key}/{fact_id}.json
│   └── events/{event_id}.json     # promotion/supersession/dispute events
├── sessions/{session_uuid}/
│   ├── manifest.json
│   └── history/{archive_id}/messages.jsonl
├── resources/{resource_uuid}/     # source material or pointer, not task state
└── skills/{skill_uuid}/           # SKILL.md + scripts, separate privacy contract

orch://project/{project_id}/projections/
├── sqlite/{projection_name}.json  # receipts/metadata only; DB rows are derived
├── fts/{generation}.json
└── vector/{generation}.json
</pre>

The initial physical mapping is intentionally boring: task state/evidence under <code>docs/tasks</code>,
topic records under <code>docs/kb</code>, sessions/logs in SQLite plus exported cold history, and
skills/resources in their existing owners. The URI is a stable resolver and identity vocabulary, not
permission to duplicate a body in another format.

## Common envelope

Every record has the following fields, with domain-specific extensions:

<pre>
{
  "record_type": "task.state|task.evidence|knowledge.fact|session.history|resource|skill",
  "schema_version": 1,
  "stable_id": "uuid-or-ulid",
  "uri": "orch://project/orchestra/knowledge/topics/repo-ops/facts/merge-wip/f-01",
  "project_id": "orchestra",
  "created_at": "2026-08-24T00:00:00Z",
  "updated_at": "2026-08-24T00:00:00Z",
  "canonical_head": "git:abcdef...",
  "projection_head": null,
  "indexed_head": null,
  "status": "current",
  "private_fields": [],
  "tombstone": false,
  "retention": "project-default"
}
</pre>

<code>canonical_head</code> is the Git commit/blob or event generation that owns the body.
<code>projection_head</code> is the SQLite/FTS current projection generation. <code>indexed_head</code>
is the vector/log index generation. A null or older head is explicit debt, never a not-found result.

## Operational task state

<pre>
{
  "record_type": "task.state",
  "stable_id": "01J8TASK-6V5K4J6H7Q",
  "project_id": "orchestra",
  "display_number": 315,
  "display_ref": "#315",
  "title": "Synthesize information architecture",
  "status": "in_progress",
  "priority": 1,
  "assignee": "synthesize-information-architecture",
  "scope": "/mnt/data/Projects/Python/orchestra",
  "worker_session_id": "session-uuid",
  "acceptance": {"command": "", "manifest_paths": [], "required": false},
  "evidence_refs": ["orch://project/orchestra/tasks/01J8TASK-6V5K4J6H7Q/evidence/research"],
  "git_commit_refs": [],
  "valid_from": "2026-08-24T00:00:00Z",
  "supersedes": null,
  "canonical_head": "git:..."
}
</pre>

<code>display_number</code> is project-scoped and preserved for human/API compatibility; it is not the
stable identity. Allocation may have gaps across two contours. A task facade is the only writer;
branch names, MCP and HTTP adapters resolve to <code>stable_id</code> through that facade.

## Immutable/reviewable task evidence

<pre>
{
  "record_type": "task.evidence",
  "stable_id": "evidence-315-research",
  "task_id": "01J8TASK-6V5K4J6H7Q",
  "kind": "research",
  "canonical_path": "docs/tasks/315/research.md",
  "git_commit": "abcdef1234567890",
  "blob_sha": "sha256:...",
  "anchor": "## Findings / ### 4. Architecture conclusion",
  "captured_at": "2026-08-24T00:00:00Z",
  "author_session_id": "session-uuid",
  "source_urls": ["https://docs.openviking.ai/en/concepts/01-architecture"],
  "content_sha256": "sha256:...",
  "tombstone": false
}
</pre>

Evidence bodies stay in Git/Markdown or immutable measurement files. A promoted fact must reference an
existing evidence record and a resolvable anchor in the same canonical generation.

## Curated topic and typed fact

<pre>
{
  "record_type": "knowledge.fact",
  "stable_id": "fact-01J8FACT-...",
  "topic_slug": "repo-ops",
  "fact_key": "merge-worker-wip-phantom-diff",
  "claim": "worker_wip row deltas can contain phantom deletions; commit list is the reliable scope check",
  "status": "current",
  "confidence": "confirmed",
  "valid_from": "2026-08-14T00:00:00Z",
  "valid_to": null,
  "observed_at": "2026-08-14T00:00:00Z",
  "refresh_after": "2026-09-14T00:00:00Z",
  "provenance": [{
    "task_id": "task-...",
    "evidence_uri": "orch://project/orchestra/tasks/task-.../evidence/report",
    "path": "docs/kb/repo-ops.md",
    "anchor": "worker_wip",
    "git_commit": "...",
    "measurement": "command + output hash"
  }],
  "supersedes": [],
  "disputed_by": [],
  "private_fields": [],
  "canonical_head": "git:...",
  "tombstone": false
}
</pre>

Topic <code>topic.md</code> contains a generated registry plus human-readable sections; the typed fact
record is the machine query contract. <code>status</code> values are <code>current</code>,
<code>historical</code>, <code>rejected</code>, <code>disputed</code>, or
<code>stale-needs-validation</code>. Superseded is represented by a retained event/edge and a
non-current record, not deletion. <code>refresh_after</code> creates validation debt only.
<code>valid_from/valid_to</code> answer as-of queries; unknown time stays null.

## Session/cold history

<pre>
{
  "record_type": "session.history",
  "stable_id": "session-uuid/archive-0007",
  "session_id": "session-uuid",
  "archive_id": "archive-0007",
  "canonical_path": "data/orchestra-history/session-uuid/archive-0007/messages.jsonl",
  "source_log_ids": [12345, 12346],
  "summary_ref": "orch://project/orchestra/sessions/session-uuid/history/archive-0007/summary",
  "retention": "90d-cold",
  "private_fields": ["message.content"],
  "status": "historical"
}
</pre>

Session history is immutable/cold and may be compacted for delivery. It does not become a current fact
without an explicit, evidence-backed promotion event. Existing <code>logs</code> insertion order must
not stand in for event time; pair/sequence by timestamp as established in #340.

## Skills and resources

Resources are source documents or repositories with <code>source_uri</code>,
<code>content_sha256</code>, scope and import provenance. Skills have <code>skill_name</code>,
<code>SKILL.md</code> body, scripts, runtime compatibility and privacy metadata. Their bodies remain in
current owners (<code>pipelines/</code>, <code>.codex/skills/</code>, repo resources) until a separate
delivery migration. A namespace reference is not a second body.

## Links and provenance

<pre>
task.state --has-evidence--> task.evidence
task.evidence --supports--> knowledge.fact
knowledge.fact --supersedes--> knowledge.fact
knowledge.fact --disputed-by--> task.evidence|fact
session.history --promoted-by--> task.evidence (explicit only)
resource|skill --source-of--> task.evidence (when imported)
</pre>

No source-less promoted fact is valid. A fact can have many evidence refs, but each ref must identify
task, path, anchor and canonical commit/blob. A task can have many evidence records, but evidence does
not inherit task state as its own status.

## Tombstones, retention and private boundary

- Normal delete writes a tombstone event with stable ID, prior head, actor and reason; projections remove
  the active row after observing the tombstone.
- Retention expiry removes/archives the body according to policy while keeping a non-sensitive audit
  tombstone where policy permits. A tombstone is not legal erasure or history rewrite.
- <code>private_fields</code> are excluded from hot prompt, FTS, vector metadata and cross-project
  results. Secret values are either absent from canonical Git or protected by a separately approved
  encrypted store.
- YouGile/payment data is not migrated; if deletion is approved, first produce a fresh manifest and
  complete reader/import/secret checks, then remove it under the #299 plan.

## No-dual-truth rule (exact)

> For every stable ID, exactly one canonical record body and one canonical event history exist. SQLite,
> FTS, vector, hot registry, prompt mirrors and API responses may project or cache that record, but they
> MUST NOT accept independent edits or claims. A projection must carry the canonical generation it read;
> if its head is older, the reader MUST disclose debt and read the canonical record directly. A source
> path, log chunk, embedding, summary or external mirror is never a second canonical fact.

## Schema invariants

1. <code>stable_id</code> is immutable and globally unique within the project namespace.
2. <code>(project_id, display_number)</code> is unique and never reused while the task evidence directory exists.
3. <code>(project_id, topic_slug, fact_key, canonical generation)</code> is the candidate fact identity.
4. Identical event payload + same idempotency key is a no-op; same-key different claim requires explicit
   supersedes or disputed, never LWW.
5. Every current/rejected/superseded fact is queryable with provenance and status.
6. <code>canonical_head</code>, <code>projection_head</code> and <code>indexed_head</code> are reported
   separately; ordering is not assumed.
7. A missing projection row is debt, not proof that canonical content is absent.
8. Restore/import validates manifest, scope, checksums and schema before writing.
