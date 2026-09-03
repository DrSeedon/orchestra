"""Feed a denied tool event through the real session handler with DB writes stubbed."""

import json

from app.events import AgentEvent
from app.session import AgentSession


def main() -> None:
    logged = []
    submitted = []
    session = object.__new__(AgentSession)
    session.id = "probe-session"
    session.name = "probe-worker"
    session.scope = "/isolated/probe"
    session.backend_type = "claude"
    session._tool_names_by_id = {}
    session._turn_logs = []
    session.total_tool_calls = 0
    session._did_report = False
    session._log = lambda *args, **kwargs: logged.append(
        {"args": [str(item) for item in args], "kwargs": kwargs}
    )
    session._submit_db_write = lambda *args, **kwargs: submitted.append(
        {
            "callable": getattr(args[0], "__name__", str(args[0])),
            "args": [str(item) for item in args[1:]],
            "kwargs": kwargs,
        }
    )

    session._handle_event(
        AgentEvent(
            "tool_use",
            "mcp__probe__ping: {}",
            {"tool_name": "mcp__probe__ping", "tool_use_id": "probe-tool-use"},
        )
    )
    session._handle_event(
        AgentEvent(
            "tool_result",
            "DENIED_BY_PROBE_EXACT_MCP_TOOL",
            {"tool_use_id": "probe-tool-use", "is_error": True},
        )
    )
    print(
        json.dumps(
            {
                "logged": logged,
                "submitted_db_writes": submitted,
                "did_report_to_parent": session._did_report,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
