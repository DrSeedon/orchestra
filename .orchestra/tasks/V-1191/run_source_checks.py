"""Supplemental checks for this partial copy; never a full-checkout gate.

Run with the provisioned uv and --stub-missing-imports explicitly. Only missing
import boundaries are stubbed: DB_PATH is unused (all tests pass synthetic paths),
and mask_secrets is identity. No claim about application DB/config or masking.
Tests needing the missing HubActivityStream or credential masking are deselected.
"""

import argparse
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


class PartialCopySelection:
    def pytest_collection_modifyitems(self, config, items):
        excluded = [
            item for item in items
            if "hub_finish_row" in item.fixturenames
            or item.originalname == "test_normalization_removes_credentials_urls_and_email_addresses"
        ]
        if excluded:
            items[:] = [item for item in items if item not in excluded]
            config.hook.pytest_deselected(items=excluded)
            print(f"Partial-copy exclusions: {len(excluded)} cases (hub_activity / real secret_mask)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stub-missing-imports", action="store_true", required=True)
    _, pytest_args = parser.parse_known_args()
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    for name, attributes in (
        ("app.db", {"DB_PATH": root / ".orchestra/tasks/V-1191/unused.db"}),
        ("app.secret_mask", {"mask_secrets": lambda value: value}),
    ):
        if importlib.util.find_spec(name) is not None:
            raise RuntimeError(f"{name} exists: use the required direct pytest command without stubs")
        module = ModuleType(name)
        module.__dict__.update(attributes)
        sys.modules[name] = module
        print(f"PARTIAL COPY: explicit import-only stub for {name}")
    from app import error_watch

    print(f"Imported app root: {Path(error_watch.__file__).resolve().parent}")
    print("Live I/O is replaced in tests; secret masking and full application imports are UNVERIFIED")
    return pytest.main([
        "tests/test_error_watch.py", "-q",
        "--basetemp=.orchestra/tasks/V-1191/pytest-tmp",
        *pytest_args,
    ], plugins=[PartialCopySelection()])


if __name__ == "__main__":
    raise SystemExit(main())
