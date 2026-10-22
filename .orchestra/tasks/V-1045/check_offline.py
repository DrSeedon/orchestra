"""Run V-1045 tests against the complete source module in this partial hub copy.

Only unavailable imports are stubbed. Tests use real SQLite, the actual backfill,
failure recording and asynchronous notice drain; manager.send is an AsyncMock.
This does not replace the required uv/pytest run in the complete repository.
"""

import importlib
import io
import resource
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


def stub(name, **attributes):
    module = ModuleType(name)
    module.__dict__.update(attributes)
    sys.modules[name] = module
    return module


@dataclass
class MessageProvenance:
    origin: str
    senders: tuple
    subtype: str
    ref: str


@dataclass
class InjectedMessage:
    text: str
    provenance: MessageProvenance
    event_id: str


def unavailable(*args, **kwargs):
    raise AssertionError("Unavailable dependency was unexpectedly called")


stub("app.db", _conn=unavailable)
stub("app.errtext", err_text=str)
stub("app.events", MessageProvenance=MessageProvenance, InjectedMessage=InjectedMessage)
stub("app.quota_queue", quota_wait_action=unavailable, wait_error=unavailable)
deliveries = importlib.import_module("app.message_deliveries")
print(f"Imported app directory: {Path(deliveries.__file__).resolve().parent}", flush=True)
print(f"Complete source module: {deliveries.__file__}", flush=True)


def suite():
    return unittest.defaultTestLoader.discover(
        str(ROOT / "tests"), pattern="test_message_failure_backfill_1045.py",
    )


if "--mutations" not in sys.argv:
    result = unittest.TextTestRunner(verbosity=2).run(suite())
    raise SystemExit(not result.wasSuccessful())

source = Path(deliveries.__file__).read_text()
mutations = {
    "remove-age-filter": (
        "if not now - FAILURE_NOTICE_BACKFILL_MAX_AGE <= updated_at <= now:",
        "if False:",
    ),
    "remove-archived-target-filter": (
        'elif target["status"] == "archived":', 'elif False:',
    ),
    "remove-missing-target-filter": (
        'if target is None:\n                reason = "target_missing"',
        'if target is None:\n                continue',
    ),
    "skip-without-durable-ack": (
        '(now.isoformat(), json.dumps(details, ensure_ascii=False), row["delivery_id"]),',
        '(None, json.dumps(details, ensure_ascii=False), row["delivery_id"]),',
    ),
    "suppress-fresh-notices-too": ('            if reason:\n', '            if True:\n'),
    "filter-already-recorded-live-notices": (
        'AND (n.delivery_id IS NULL\n',
        'AND (n.delivery_id IS NULL OR n.delivered_at IS NULL\n',
    ),
}
for name, (before, after) in mutations.items():
    if source.count(before) != 1:
        raise AssertionError(f"Mutation anchor is not unique: {name}")
    # Execute the entire module again, with just the selected guard changed in
    # memory. Production files and the tests are never rewritten by this runner.
    exec(compile(source.replace(before, after), deliveries.__file__, "exec"), deliveries.__dict__)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite())
    (Path(__file__).parent / f"mutation-{name}.log").write_text(output.getvalue())
    if result.wasSuccessful():
        raise AssertionError(f"Mutation survived: {name}")
    print(f"KILLED {name}: {len(result.failures)} failures, {len(result.errors)} errors", flush=True)
print(f"All {len(mutations)} mutations killed; source files were not changed.")
