"""Run available stdlib V-1047 regressions without pytest or runtime modules."""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('existing_gate_tests', ROOT / 'tests/test_publication_gate_v1047.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ARTIFACTS = Path(__file__).resolve().parent / 'existing-sandboxes'
excluded = {
    'test_hub_pem_header_mentions_pass_but_body_requires_40_characters',
    'test_hub_reuses_literal_inventory',
    'test_secret_mask_uses_shared_names_and_length',
    'test_merge_worker_blocks_literal_without_changing_refs',
    'test_merge_worker_allows_shape_mentions',
    'test_registered_scopes_install_and_foreign_scope_reports_error',
}
names = [name for name in unittest.defaultTestLoader.getTestCaseNames(module.GateTests) if name not in excluded]
suite = unittest.TestSuite(module.GateTests(name) for name in names)
result = unittest.TextTestRunner(verbosity=2).run(suite)
module.ARTIFACTS.rmdir()
raise SystemExit(not result.wasSuccessful())
