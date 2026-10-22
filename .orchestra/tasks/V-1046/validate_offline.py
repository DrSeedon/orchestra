"""Limited offline check when uv/pytest and the rest of app are absent.

This is NOT the required pytest run. app.db and app.secret_mask are unavailable
in the supplied cone: only their imports are substituted. Secret masking itself
is not tested. Test functions run unchanged with small fixture substitutes.
"""

import ast
from contextlib import redirect_stdout
import importlib
import inspect
import io
import os
from pathlib import Path
import resource
import sys
import tempfile
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.nice(15)
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
sys.dont_write_bytecode = True

db_stub = ModuleType("app.db")
db_stub.DB_PATH = ARTIFACTS / "unused.db"
mask_stub = ModuleType("app.secret_mask")
mask_stub.mask_secrets = lambda message: message
sys.modules["app.db"] = db_stub
sys.modules["app.secret_mask"] = mask_stub
app = importlib.import_module("app")
watch = importlib.import_module("app.error_watch")
print(f"app namespace: {list(app.__path__)}")
print(f"error_watch imported from: {watch.__file__}")
print("LIMITATION: DB_PATH stub; mask_secrets identity stub; no real pytest fixtures/plugins")

test_path = ROOT / "tests/test_error_watch.py"
tests = {"__name__": "offline_error_watch_tests", "__file__": str(test_path)}
exec(compile(test_path.read_text(), str(test_path), "exec"), tests)
test_names = sorted(name for name in tests if name.startswith("test_"))
regression_names = [name for name in test_names if name.startswith((
    "test_hub_", "test_expected_hub_", "test_real_hub_",
))]


class MonkeyPatch:
    def __init__(self):
        self.saved = []

    def setattr(self, obj, name, value):
        self.saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def undo(self):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)


class Capture(io.StringIO):
    def readouterr(self):
        result = SimpleNamespace(out=self.getvalue(), err="")
        self.seek(0)
        self.truncate(0)
        return result


def run(names):
    failures = []
    for name in names:
        patch = MonkeyPatch()
        capture = Capture()
        with tempfile.TemporaryDirectory(prefix="offline-check-", dir=ARTIFACTS) as directory:
            fixtures = {"tmp_path": Path(directory), "monkeypatch": patch, "capsys": capture}
            try:
                with redirect_stdout(capture):
                    tests[name](**{key: fixtures[key] for key in inspect.signature(tests[name]).parameters})
            except Exception as error:
                failures.append(name)
                print(f"FAIL {name}: {type(error).__name__}: {error}".rstrip())
            finally:
                patch.undo()
    return failures


failures = run(test_names)
print(f"Offline baseline: {len(test_names) - len(failures)}/{len(test_names)} passed")
if failures:
    raise SystemExit(1)


def mutated_watch(*, normalization=False, post_fix=False, noise=False):
    tree = ast.parse(Path(watch.__file__).read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "normalize_signature" and normalization:
            # Restore the old path: mask_secrets followed directly by _SECRET_MARK.
            start = next(i for i, statement in enumerate(node.body) if (
                isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and isinstance(statement.value.func.value, ast.Name)
                and statement.value.func.value.id == "_SECRET_MARK"
            ))
            node.body = node.body[:2] + node.body[start:]
        if isinstance(node, ast.FunctionDef) and node.name == "post_fix_verdict" and post_fix:
            for child in ast.walk(node):
                if isinstance(child, ast.comprehension):
                    child.ifs = [condition for condition in child.ifs if not any(
                        isinstance(part, ast.Name) and part.id == "_EXPECTED_HUB_NOISE"
                        for part in ast.walk(condition)
                    )]
    mutant = ModuleType("offline_mutant")
    mutant.__file__ = watch.__file__
    namespace = mutant.__dict__
    exec(compile(tree, watch.__file__, "exec"), namespace)
    if noise:
        mutant._NOISE = tuple(item for item in namespace["_NOISE"] if item[0] not in namespace["_EXPECTED_HUB_NOISE"])
        namespace["_NOISE"] = mutant._NOISE
    return mutant


for label, options, names in [
    ("whole fix reverted", {"normalization": True, "post_fix": True, "noise": True}, regression_names),
    ("post-fix exclusion reverted", {"post_fix": True}, [
        "test_expected_hub_failures_never_count_as_post_fix_recurrences",
    ]),
]:
    tests["watch"] = mutated_watch(**options)
    failures = run(names)
    print(f"Mutation ({label}): {len(failures)}/{len(names)} tests rejected the regression")
    if set(failures) != set(names):
        raise SystemExit(1)
