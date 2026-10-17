## Summary

The pinned diff changes every fresh, resumed, and fallback Codex review command to `danger-full-access`, and adds a text-pattern check intended to reject reviews that could not run workspace commands. I found a security issue in the new execution policy.

## Findings (blocking/suggestion/question)

- **blocking — Codex reviews can access files and network beyond the worktree:** The commands now use `-s danger-full-access -a never` for all review paths ([app/mcp_stdio.py](/home/kesha/v909-work/v909-clean-179-1_7fk318/app/mcp_stdio.py:2083), [app/mcp_stdio.py](/home/kesha/v909-work/v909-clean-179-1_7fk318/app/mcp_stdio.py:2131)). This removes Codex’s sandbox while running under the Orchestra account. A review can therefore read or modify that account’s files outside the selected worktree, access other projects or available credentials, and make network requests. In a distributed multi-project production service, that breaks project isolation and exposes secrets to the review process. The host’s Unix permissions do not constrain access to files already readable or writable by the shared account. Use an execution boundary that restores command availability while still restricting each review to its intended workspace and required resources.

## Verdict

NEEDS WORK