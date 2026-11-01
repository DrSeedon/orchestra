"""Sequential offline acceptance/mutation runs, retaining every stdout/stderr byte."""
from pathlib import Path
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent
uv = Path.home() / '.local/share/orchestra/tools/uv/0.11.28/bin/uv'
commands = [
    (f'mutation-{mode}', [str(TASK / 'run_mutation.py'), mode], 1)
    for mode in ('baseline', 'global-day-index', 'single-day-session', 'snapshot',
                 'scope', 'payload-prefix', 'candidate-cap', 'inline')
]
paths = [
    'tests/test_log_search_v1001.py', 'tests/test_log_search_v1078.py',
    'tests/test_log_search_v1089.py', 'tests/test_db.py',
    'tests/test_db_connection_ownership.py', 'tests/test_mcp_stdio.py',
    'tests/test_session_logs_conditional.py', 'tests/test_instruction_contract.py',
    'tests/test_mcp_proof.py', 'tests/test_mcp_config_isolation.py',
    'tests/test_mcp_resolve_operation_423.py',
]
commands += [
    ('final-tests', ['-m', 'pytest', *paths, '-q', '--tb=short',
                     '--basetemp=.orchestra/tasks/V-1089/tmp/final'], 0),
    ('instruction-contract', ['-c', 'import runpy; runpy.run_path("tests/conftest.py"); '
                              'runpy.run_path("scripts/check_instruction_contract.py", run_name="__main__")'], 0),
]
results = []
for name, args, expected in commands:
    command = [str(uv), 'run', '--frozen', 'python', *args]
    with (TASK / 'private/raw' / (name + '.txt')).open('wb') as output:
        run = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    record = {'name': name, 'command': ['uv', 'run', '--frozen', 'python', *args],
              'exit_code': run.returncode, 'expected_exit': expected}
    results.append(record)
    # Commands and their exact paths stay private; publish only the outcome here.
    print(json.dumps({'name': name, 'exit_code': run.returncode}), flush=True)
(TASK / 'private/raw/checks.json').write_text(json.dumps(results, indent=2) + '\n')
raise SystemExit(0 if all(r['exit_code'] == r['expected_exit'] for r in results) else 1)
