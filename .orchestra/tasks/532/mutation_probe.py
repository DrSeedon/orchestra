"""Prove both committed dispatch arms detect regressions; always restore source."""
from pathlib import Path
import subprocess
import sys

source = Path('app/mcp_stdio.py')
original = source.read_text()
try:
    for label, replacement in [('deny_removed', 'if False:'), ('deny_everything', 'if True:')]:
        source.write_text(original.replace('if name in DISABLED_TOOLS:', replacement, 1))
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/test_tool_scoping.py::test_role_dispatch_both_arms', '-q'],
            capture_output=True, text=True, timeout=45,
        )
        print(f'=== {label}: rc={result.returncode} ===')
        print(result.stdout)
        print(result.stderr)
        assert result.returncode == 1
finally:
    source.write_text(original)
