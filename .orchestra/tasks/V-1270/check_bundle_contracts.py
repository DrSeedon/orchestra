"""Offline research probe: execute one pure function, never import app or a provider.

This is not the project's pytest/uv acceptance suite and does not exercise macOS.
Run from the supplied source bundle with a standard-library-only interpreter.
"""

import ast
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "app/harness/mcp.py"


def function(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)


def main():
    print("interpreter=" + sys.executable)
    print("source=" + str(SOURCE))
    print("imported_app=NONE; mode=offline isolated AST/pure-function probe")
    node = function(SOURCE, "_extract_text")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    extract = namespace["_extract_text"]
    # The image sentinel is intentionally not a real screenshot or credential.
    image = {"type": "image", "data": "RESEARCH_IMAGE_SENTINEL", "mimeType": "image/jpeg"}
    cases = [
        ("text preserved", {"content": [{"type": "text", "text": "ready"}]}, "ready"),
        ("MCP image loses payload", {"content": [image]}, "[image]"),
        ("terminal-mac-shaped image+text", {"content": [image, {"type": "text", "text": "Screen: 1280×800. Use these pixel coordinates."}]},
         "[image]\nScreen: 1280×800. Use these pixel coordinates."),
        ("MCP error preserved", {"isError": True, "content": [{"type": "text", "text": "guest unavailable"}]},
         "[mcp error] guest unavailable"),
        ("empty result", {}, "(no output)"),
    ]
    for label, value, expected in cases:
        actual = extract(value)
        if actual != expected:
            raise AssertionError((label, expected, actual))
        print("PASS " + label + ": " + json.dumps(actual, ensure_ascii=False))

    # This checks the supplied source shape, not a running Hub/T3 service.
    hub_factory = function(ROOT / "app/runtime_registry.py", "_hub_factory")
    constructor = next(node for node in ast.walk(hub_factory)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "HubBackend")
    if any(keyword.arg == "mcp_servers" for keyword in constructor.keywords):
        raise AssertionError("Hub MCP forwarding contract has changed; re-review source")
    print("PASS source shape: _hub_factory has no mcp_servers keyword")
    print("RESULT 6/6 probe checks passed; confirmed harness image limitation; no app/runtime acceptance performed")


if __name__ == "__main__":
    main()
