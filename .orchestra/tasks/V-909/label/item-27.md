# item-27

Commit under review (in /home/kesha/orchestra, read-only): `a3ca2eeee50f3dc51eaa01e6373a13a00130f7c0`
Subject / date:
#264: #264: поднять Grok как рантайм воркера — снять коллизию .mcp.json и починить сверку роспуска MCP
2026-08-13

The diff reviewed is `git -C /home/kesha/orchestra show a3ca2eeee50f3dc51eaa01e6373a13a00130f7c0 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Reviewed the requested diff from `321852b…` to `efd827c…`. The removal of the colliding `.mcp.json` addresses the reported launch failure. The new startup check accepts Grok 1.0.3’s empty `servers_updated` roster and uses `init_progress.total` to detect extra servers.

## Findings (blocking/suggestion/question)

- **Blocking** — [app/backend_grok.py](app/backend_grok.py:419): When Grok omits server identities, a same-name replacement passes this check. `total` only compares the number of servers, while readiness and tool count do not establish that `orchestra` is the planned server. The report acknowledges this case when the folder is trusted; the existing identity isolation guarantee is therefore weakened. Fail closed when identity is unavailable, or add a handshake that verifies the server against the launch plan before allowing the worker to run.

## Verdict

NEEDS WORK — the reported Grok startup issue is addressed, but the MCP identity check can accept a same-name server replacement.
