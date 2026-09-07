from __future__ import annotations
import ast
from pathlib import Path

path = Path("tests/test_api.py")
tree = ast.parse(path.read_text())
functions = {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in ("test_send_delegates_auto_switch_to_manager", "test_send_quota_refusal_is_canonical_429"):
    assert name in functions, f"missing behavior: {name} absent"
    args = {arg.arg for arg in functions[name].args.args}
    assert "db" in args, f"missing behavior: {name} does not request isolated db fixture"
source = path.read_text()
assert 'preflight_message_delivery", AsyncMock()' in source, "missing behavior: delivery preflight not isolated"
