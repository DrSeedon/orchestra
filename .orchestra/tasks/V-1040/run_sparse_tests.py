"""Import-only stand-ins for modules omitted from this worker's private repository copy.

Run the real changed modules and MockTransport tests. In a full checkout use pytest directly.
The omitted MCP registration test cannot run here; none of its code is replaced or weakened.
"""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))


def absent_module(name, **attributes):
    if importlib.util.find_spec(name) is None:
        module = ModuleType(name)
        module.__dict__.update(attributes)
        sys.modules[name] = module
        print(f"Sparse import stand-in: {name}")


class WorkspaceError(RuntimeError):
    pass


absent_module("app.hub_workspace", HubWorkspaceError=WorkspaceError, HubSsh=object,
              WorkspaceState=object, UploadPlan=object, ProjectOptions=object)
absent_module("app.hub_activity", HubActivityStream=object)
absent_module("app.hub_outbox", OUTBOX_NAME=".orchestra-outbox.jsonl", OutboxReport=object,
              parse_outbox=lambda _: None)
absent_module("app.events", AgentEvent=object)
absent_module("app.usage_contract", AggregateUsage=object, TurnUsage=object,
              current_context=lambda *_: None)

import app
from app import backend_hub, multicode_client

print(f"Imported app namespace: {list(app.__path__)}")
print(f"Imported app.backend_hub: {backend_hub.__file__}")
print(f"Imported app.multicode_client: {multicode_client.__file__}")
raise SystemExit(pytest.main(sys.argv[1:]))
