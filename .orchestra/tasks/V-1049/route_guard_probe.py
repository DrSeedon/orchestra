"""Offline fallback: execute the actual delete handler body without FastAPI imports.

This checks its Git guard with a fake session manager, not HTTP routing/initialization.
Run from the repository root; TMPDIR must point inside the task artifacts directory.
"""
import ast
import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))

from app import private_folder

spec = importlib.util.spec_from_file_location(
    "regressions", root / "tests/test_private_symlink_dirty_v1049.py")
regressions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regressions)

source = root / "app/routes/sessions.py"
handler = next(node for node in ast.parse(source.read_text()).body
               if isinstance(node, ast.AsyncFunctionDef) and node.name == "delete_session")
handler.decorator_list = []


class Response:
    def __init__(self, payload, status_code):
        self.payload, self.status_code = payload, status_code


case = regressions.PrivateSymlinkDirtyTests("test_reinclude_with_missing_generated_ignore")
case.setUp()
try:
    case.expose_link()
    found = SimpleNamespace(id="worker-id", loaded=False, scope=str(case.repo),
                            worktree_path=str(case.wt))
    manager = SimpleNamespace(get_by_name=lambda *args: found,
                              _live_children=lambda *args: [], remove=AsyncMock())
    namespace = {"asyncio": asyncio, "Path": Path, "JSONResponse": Response,
                 "manager": manager, "_session_base_branch": lambda session: "main",
                 "logger": logging.getLogger("route-guard-probe")}
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), "exec"), namespace)

    def invoke():
        return asyncio.run(namespace["delete_session"]("worker", str(case.repo)))

    assert invoke() == {"ok": True}
    manager.remove.assert_awaited_once_with("worker-id")
    manager.remove.reset_mock()

    user_file = case.wt / ".orchestra/user.txt"
    user_file.write_text("keep\n")
    refused = invoke()
    assert refused.status_code == 400 and ".orchestra/user.txt" in refused.payload["error"]
    manager.remove.assert_not_awaited()
    user_file.unlink()

    with patch.object(private_folder, "filter_worktree_status", side_effect=lambda path, status: status):
        refused = invoke()
        assert refused.status_code == 400 and ".orchestra/private" in refused.payload["error"]
        manager.remove.assert_not_awaited()

    case.link.unlink()
    other = case.root / "other"
    other.mkdir()
    case.link.symlink_to(other)
    refused = invoke()
    assert refused.status_code == 400 and ".orchestra/private" in refused.payload["error"]
    manager.remove.assert_not_awaited()

    case.link.unlink()
    case.link.symlink_to(case.shared)
    regressions.git(case.wt, "add", private_folder.PRIVATE_REL)
    refused = invoke()
    assert refused.status_code == 400 and ".orchestra/private" in refused.payload["error"]
    manager.remove.assert_not_awaited()
    print("PASS: actual delete handler body permits the shared untracked link; rejects a user file,")
    print("a wrong-target link and a staged link. Disabling the filter restores the erroneous refusal.")
    print("HTTP routing and full application imports were not exercised.")
finally:
    case.doCleanups()
