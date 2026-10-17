## Summary

Reviewed the complete diff between the pinned commits. It limits Claude’s available tools for `worker`, `reviewer`, and `watcher` roles.

## Findings

### Suggestion

[app/backend_claude.py](/home/kesha/v909-work/v909-bad-51-dcler0nj/app/backend_claude.py:161): The explicit `options.tools` list omits Orchestra’s MCP tools. The worker prompt requires agents to use `send_message` for communication, so lean workers may be unable to report progress or results through the required channel. The Claude SDK documents `tools` as selecting the available toolset; MCP tools are not retained automatically when a smaller list is supplied. [SDK documentation](https://github.com/anthropics/claude-agent-sdk-python)

Keep the required communication MCP tools available to lean roles, or provide another supported reporting path.

## Verdict

NEEDS WORK