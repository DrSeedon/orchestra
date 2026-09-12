"""Run each restored defect against committed regression tests, restoring files in finally."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
CASES = [
    ('catalog', 'app/mcp_stdio.py', '\n_ORCH_ROLES =',
     '\n@mcp.tool()\nasync def run' + '_fan() -> str:\n    return "returned"\n\n_ORCH_ROLES =',
     'tests/test_dynamic_workflows.py::test_removed_tool_is_absent_and_cannot_dispatch'),
    ('module', '.orchestra/pipelines/default/pipeline.yaml', 'dynamic-workflows, ', '',
     'tests/test_dynamic_workflows.py::test_workflow_module_reaches_launching_roles'),
    ('routing', 'scripts/wf_run.py', '        else:\n            candidates = ["luna"]',
     '        elif purpose == "verify" or escalate:\n            candidates = ["sol"]\n        else:\n            candidates = ["luna"]',
     'tests/test_dynamic_workflows.py::test_default_dispatch_uses_default_subscription_model'),
    ('target', 'scripts/wf_run.py', '        workspace_repo=args.repo,', '        workspace_repo=None,',
     'tests/test_dynamic_workflows.py::test_cli_parallel_uses_target_repository_and_resume_preserves_it'),
    ('resume', 'scripts/wf_run.py', '            *(["--repo", str(self.workspace_repo)] if self.workspace_repo is not None else []),', '',
     'tests/test_dynamic_workflows.py::test_cli_parallel_uses_target_repository_and_resume_preserves_it'),
]
for name, relative, old, new, test in CASES:
    path = ROOT / relative
    original = path.read_text()
    assert old in original, name
    try:
        path.write_text(original.replace(old, new))
        run = subprocess.run([sys.executable, '-m', 'pytest', test, '-q'], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        print(f'=== {name}: exit={run.returncode} ===\n{run.stdout}', flush=True)
        assert run.returncode == 1 and 'failed' in run.stdout, name
    finally:
        path.write_text(original)
print('All five restored defects rejected.')
