"""Run transport unit tests in this deliberately partial hub copy.

Import-only dependencies of the two supplied hub modules are absent. Their publication/outbox/provider
APIs are not exercised by these tests. Stub just those imports, disable the global
application fixtures, and test the actual HubSsh provisioning methods and shell commands.
This does NOT replace the required suite with full application fixtures.
"""
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
for name, attributes in (
    ("app.hub_outbox", {"MAX_OUTBOX_BYTES": 1_000_000, "OUTBOX_NAME": ".orchestra-outbox.jsonl",
                         "OutboxReport": object, "parse_outbox": None}),
    ("app.publication_secrets", {"HUB_SECRET_SHAPES": ()}),
    ("app.hub_activity", {"HubActivityStream": object}),
    ("app.events", {"AgentEvent": object}),
    ("app.multicode_client", {"MultiCodeClient": object, "MultiCodeError": type("MultiCodeError", (Exception,), {}),
                               "_last_assistant_text": None}),
    ("app.usage_contract", {"AggregateUsage": object, "TurnUsage": object, "current_context": None}),
):
    if not (root / (name.replace('.', '/') + '.py')).exists():
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        sys.modules[name] = module

if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([
        '--noconftest', '--basetemp', str(root / '.orchestra/tasks/V-1055/runtime/pytest'),
        'tests/test_hub_uv.py', '-q',
    ]))
