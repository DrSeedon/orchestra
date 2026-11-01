"""Limited offline check for the sparse worker copy; not the required test run.

app.db and app.secret_mask were not supplied. Stub only those imports, and skip
the global conftest that requires the rest of app/. Secret masking, global test
isolation and full repository integration are NOT validated by this check.
"""

from pathlib import Path
import sys
from types import ModuleType

import pytest


root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
db = ModuleType("app.db")
db.DB_PATH = root / ".orchestra/tasks/V-1103/unused.db"
secret_mask = ModuleType("app.secret_mask")
secret_mask.mask_secrets = lambda value: value
sys.modules["app.db"] = db
sys.modules["app.secret_mask"] = secret_mask

from app import error_watch

print(f"Imported app.error_watch: {error_watch.__file__}", flush=True)
selection = sys.argv[1] if len(sys.argv) > 1 else "merge_full_sha_refusal or other_merge_failures"
raise SystemExit(pytest.main([
    "--noconftest", "tests/test_error_watch.py", "-q", "-k",
    selection,
]))
