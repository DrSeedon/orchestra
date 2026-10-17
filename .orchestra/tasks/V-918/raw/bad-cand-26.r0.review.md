## Summary

Reviewed the complete pinned diff between `7a5e126d6d56b32ebc012cfcfb9d5e3d973dacb6` and `a49c53d5039c1ff7ce5958d568bd9fc95da1df30`.

## Findings

### Suggestion

- [app/static/js/app.js](/home/kesha/v918-work/v918-bad-cand-26.r0-l7dystr8/app/static/js/app.js:3123): The new Download and Preview buttons are shown without checking whether file access is disabled on the server. They call `/api/files/raw` directly, so the previous “Disabled on server” response from `/api/open-file` is no longer surfaced in this flow. If the task is to preserve that disabled state, gate these buttons on the server setting and show the disabled message when it is off.

## Verdict

NEEDS WORK — the changed UI does not preserve the server-disabled behavior.