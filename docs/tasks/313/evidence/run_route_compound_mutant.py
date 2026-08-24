import importlib.util
import json
import os
import sys
import types
from pathlib import Path

os.pidfd_open = lambda *args: -1
root = Path(__file__).resolve().parents[4]
pkg = types.ModuleType("tests")
pkg.__path__ = [str(root / "tests")]
sys.modules["tests"] = pkg
spec = importlib.util.spec_from_file_location("tests.test_routes_surface", root / "tests/test_routes_surface.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
original = module.route_surface
small = original()[:1]
module.route_surface = lambda: small
snapshot = root / "docs/tasks/313/evidence/route-truncated.json"
snapshot.write_text(json.dumps(small))
module.SNAPSHOT = snapshot
import pytest
name = sys.argv[1]
raise SystemExit(pytest.main(["tests/test_routes_surface.py", "-k", name, "-q"]))
