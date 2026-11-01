"""Offline fallback for this source-only copy; NOT the full-checkout pytest gate.

app.db and app.secret_mask were not supplied. Only their import contracts are
stubbed. Secret masking, application fixtures and production integration are
therefore unverified. Use only synthetic data; the credential test is excluded
from the optional wider run because identity masking cannot verify it.
"""

from pathlib import Path
import re
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
(ROOT / ".orchestra/tasks/V-1189/tmp").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
db = ModuleType("app.db")
db.DB_PATH = ROOT / ".orchestra/tasks/V-1189/unused-synthetic.db"
mask = ModuleType("app.secret_mask")
mask.mask_secrets = lambda message: message
sys.modules["app.db"] = db
sys.modules["app.secret_mask"] = mask

from app import error_watch as watch  # noqa: E402

print(f"Imported app.error_watch: {Path(watch.__file__).resolve().relative_to(ROOT)}", flush=True)
print("ISOLATED: stub DB_PATH and identity mask_secrets; repository conftest disabled", flush=True)
arguments = sys.argv[1:]
if "--simulate-before" in arguments:
    arguments.remove("--simulate-before")
    # Restore only the two defective behaviors to check test sensitivity.
    watch._canonicalize_connector_errors = lambda value: value
    watch._NOISE = tuple(
        (label, re.compile(r"^During handling of the above exception, another exception occurred:$", re.I))
        if label == "traceback chaining line" else (label, pattern)
        for label, pattern in watch._NOISE
    )
    print("SIMULATED BEFORE: original chaining filter and order-sensitive connector signatures", flush=True)

raise SystemExit(pytest.main([
    "--noconftest", "tests/test_error_watch.py", "-q",
    "--basetemp", str(ROOT / ".orchestra/tasks/V-1189/tmp/isolated-pytest"),
    *(arguments or ["-k", "v1189"]),
]))
