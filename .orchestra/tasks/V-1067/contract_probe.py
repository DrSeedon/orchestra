"""V-1067 offline observation only. No API, provider, SSH, git or database calls."""
import asyncio
import ast
import inspect
import json
from pathlib import Path
import textwrap
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import app
from app.backend_hub import HubBackend, hub_preamble
from app.hub_outbox import Identity, execute, parse_outbox
from app.manager import _roles_catalog_from_manifest
from app.pipeline import get_role, validate_spawn
from app.runtime_registry import get_runtime


async def main():
    imported = Path(app.__file__).resolve()
    assert imported == ROOT / "app/__init__.py"
    print("imported_app=/remote/workspace/" + str(imported.relative_to(ROOT)))
    print("path_normalization=checkout root replaced by /remote/workspace")
    roles = ("worker", "full-cycle", "orchestrator", "sub-orchestrator")
    texts = []
    for role in roles:
        who = Identity("probe-id", "probe", "/probe", parent_name="parent", role=role,
                       branch="task-V-1067/probe", pipeline="default")
        text = hub_preamble(who, "V-1067", has_link=True)
        texts.append(text)
        print(f"preamble role={role}: worker_heading={'## Role: Worker (hub copy)' in text}; "
              f"full_cycle_heading={'## Role: Full-Cycle Worker' in text}; "
              f"outbox={'<orchestra-link>' in text}")
    assert len(set(texts)) == 1
    print("all_four_role_preambles_identical=True")
    for op in ("worker_wip", "merge_worker", "spawn_worker", "send_message"):
        entries, dropped = parse_outbox(json.dumps({"tool": op, "args": {"message": "probe"}}).encode())
        print(f"parse {op}: accepted={len(entries)}; dropped={json.dumps(dropped)}")
    for parent in ("parent", ""):
        calls = []
        async def capture(method, path, body):
            calls.append((method, path, sorted(body), body["sender"], body["scope"]))
            return {"ok": True, "delivery_state": "SUBMITTED"}
        who = Identity("probe-id", "probe", "/probe", parent_name=parent, role="full-cycle")
        result = await execute([{"tool": "send_message", "args": {
            "to": "foreign", "message": "probe", "file_path": "/not-read", "scope": "/foreign",
        }}], who, capture)
        print(f"send parent={parent!r}: calls={json.dumps(calls)}; done={result.done}; dropped={result.dropped}")
    for role in ("worker", "full-cycle"):
        spec = get_role("default", role)
        print(f"manifest {role}: is_orchestrator={spec.is_orchestrator}; can_spawn={spec.can_spawn}; disabled_tools={spec.disabled_tools}")
        try:
            validate_spawn("default", role, "worker")
        except ValueError as exc:
            print(f"validate_spawn {role}->worker: {exc}")
        else:
            print(f"validate_spawn {role}->worker: allowed")
    print("role_catalog_mentions_full_cycle_children=" + str(
        "can spawn sub-workers" in _roles_catalog_from_manifest("default", "orchestrator")))
    init = ast.parse(textwrap.dedent(inspect.getsource(HubBackend.__init__)))
    loads = [node.id for node in ast.walk(init) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)]
    print("HubBackend.__init__ system_prompt_body_loads=" + str(loads.count("system_prompt")))
    print("hub_runtime_subagents=" + str(get_runtime("hub").capabilities.subagents))
    print("OFFLINE PROBE PASSED")


if __name__ == "__main__":
    asyncio.run(main())
