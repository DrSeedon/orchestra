"""Diagnostic only: run synthetic capacity tests without missing copied dependencies.

This is NOT the required production-import pytest run. DB_PATH is an unused
sentinel and mask_secrets is an identity stand-in, so masking/integration remain
unverified. No missing application source files are fabricated on disk.
"""

from pathlib import Path
import sys
from types import ModuleType

import pytest


root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
db = ModuleType("app.db")
db.DB_PATH = root / ".orchestra/tasks/V-1146/unused.db"
mask = ModuleType("app.secret_mask")
mask.mask_secrets = lambda message: message
sys.modules[db.__name__] = db
sys.modules[mask.__name__] = mask

from app import error_watch as watch

print(f"Diagnostic app.error_watch import: {watch.__file__}")
print("Stand-ins: app.db.DB_PATH (unused); app.secret_mask.mask_secrets (identity)")
if "--without-capacity-rule" in sys.argv:
    sys.argv.remove("--without-capacity-rule")
    watch._NOISE = tuple(item for item in watch._NOISE if item[0] != "external provider capacity")
    print("In-memory negative control: capacity classification rule removed")

raise SystemExit(pytest.main([
    str(root / "tests/test_error_watch.py"), "-q",
    "-k", "capacity or quota or merge or hub_turn_failure_signatures or real_hub_transport_error",
    *sys.argv[1:],
]))
