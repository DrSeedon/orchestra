## Summary

Reviewed the complete diff between the pinned commits. No blocking crash, corruption, or security issue found.

## Findings

### Suggestion

- **Transcript routes use the process’s Claude config instead of the session’s profile.** Both transcript endpoints call the SDK using only the session’s `cwd` ([subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r1-rrzm_6bw/app/routes/subagent.py:40), [subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r1-rrzm_6bw/app/routes/subagent.py:60)). Sessions can use a profile-specific `config_dir`, but these helpers run in the server process and don’t receive that directory. For sessions using a nondefault profile, listing or fetching transcripts can therefore look in the wrong store and return no data. Resolve the session’s profile and use its Claude store when calling the SDK.

### Question

- **Should transcript lookup cover older SDK session IDs?** The routes use only the session’s current `session_id` ([subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r1-rrzm_6bw/app/routes/subagent.py:37), [subagent.py](/home/kesha/v918-work/v918-bad-cand-21.r1-rrzm_6bw/app/routes/subagent.py:57)), while telemetry stores the SDK session ID from each Task event ([backend_claude.py](/home/kesha/v918-work/v918-bad-cand-21.r1-rrzm_6bw/app/backend_claude.py:323), [session.py](/home/kesha/v918-work/v918-bad-cand-21.r1-rrzm_6bw/app/session.py:984)). If a session’s SDK ID changes, older sub-agent transcripts may no longer be reachable through these routes.

## Verdict

APPROVED — with the profile lookup improvement noted above.