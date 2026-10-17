## Summary

Reviewed the complete diff between `ca84106cd1615fc7402e11fb4113683f5a694847` and `59100bdfe343e7425e747b2b769f0263ba3cd232`. I did not edit files.

## Findings

### Suggestion

- **Transcript lookup uses the session’s current SDK ID instead of the sub-agent’s stored SDK ID.** The Task events persist `sdk_session_id` per sub-agent, but both transcript endpoints read `sessions.session_id` and pass that to the SDK. If the session resumes with a different SDK ID, earlier sub-agent transcripts can become inaccessible. Use the sub-agent’s stored SDK ID when looking up its transcript. [subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r0-lr00nrza/app/routes/subagent.py:54) [session.py](/home/kesha/v918-work/v918-bad-cand-21.r0-lr00nrza/app/session.py:984)

- **Transcript endpoints do not apply the session’s Claude profile.** Sessions store a profile, and the backend sets `CLAUDE_CONFIG_DIR` for that profile, but these routes call SDK transcript helpers without that environment. For sessions using a custom profile, listing or reading transcripts may look in the wrong store and return no results. [subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r0-lr00nrza/app/routes/subagent.py:40) [db.py](/home/kesha/v918-work/v918-bad-cand-21.r0-lr00nrza/app/db.py:61)

- **Telemetry rows are not linked to transcript IDs.** The telemetry table is keyed by Task `task_id`; transcript routes require SDK `agent_id`. The implementation notes these IDs may differ, but persists no mapping between them. That prevents reliably opening a transcript from its telemetry row when the IDs do differ. [subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r0-lr00nrza/app/routes/subagent.py:5) [db.py](/home/kesha/v918-work/v918-bad-cand-21.r0-lr00nrza/app/db.py:682)

## Verdict

NEEDS WORK — transcript lookup can fail for resumed sessions and custom profiles, and telemetry cannot reliably identify its corresponding transcript.