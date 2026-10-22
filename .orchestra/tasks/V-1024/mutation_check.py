"""Run sequential behavior mutations, restoring every source file even on failure."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
POOL = 'app/hub_pool.py'
BACKEND = 'app/backend_hub.py'
MUTATIONS = [
    ('M1 active account only', POOL,
     'sum(state is True for state in capacity)', 'int(_usable(active, threshold) is True)',
     ['tests/test_hub_pool.py', '-k', 'admission_checks_the_whole_pool']),
    ('M2 either window suffices', POOL,
     'return all(value < threshold for value in values)', 'return any(value < threshold for value in values)',
     ['tests/test_hub_pool.py', '-k', 'both_windows']),
    ('M3 threshold inclusive', POOL, 'return all(value < threshold for value in values)', 'return all(value <= threshold for value in values)',
     ['tests/test_hub_pool.py', '-k', 'threshold_boundary']),
    ('M4 unavailable relay blocks', POOL,
     'return decision.reason if decision.state == "unknown" else None',
     'raise RuntimeError("relay unavailable") if decision.state == "unknown" else RuntimeError("mutant")',
     ['tests/test_hub_pool.py', '-k', 'unavailable_pool_warns']),
    ('M5 session admission bypasses hub', 'app/quota_gate.py',
     'if provider_for_model(model) is not None:', 'if False:',
     ['tests/test_hub_pool.py', '-k', 'session_preflight']),
    ('M6 spawn bypasses gate', 'app/manager.py',
     'await require_hub_capacity(model)', 'None',
     ['tests/test_quota_admission_e2e.py', '-k', 'hub_spawn_checks']),
    ('M7 model switch bypasses gate', 'app/session.py',
     'await require_hub_capacity(new_model)', 'None',
     ['tests/test_quota_admission_e2e.py', '-k', 'hub_model_change']),
    ('M8 backend turn bypasses gate', BACKEND,
     'warning = await require_hub_capacity(self.model)', 'warning = None',
     ['tests/test_hub_workspace.py', '-k', 'pool_refusal_prevents']),
    ('M9 reply limit ignored', BACKEND,
     'self._watch_limit or _provider_limit(reply, failed=status == "failed")', 'self._watch_limit',
     ['tests/test_hub_workspace.py', '-k', 'provider_limit_fails_turn and reply']),
    ('M10 status limit ignored', BACKEND,
     'self._watch_limit or status_limit or _provider_limit(waited)', 'None',
     ['tests/test_hub_workspace.py', '-k', 'provider_limit_fails_turn and status']),
    ('M11 parent notice omitted', BACKEND,
     'if self._bridge is not None:', 'if False and self._bridge is not None:',
     ['tests/test_hub_workspace.py', '-k', 'provider_limit_fails_turn']),
    ('M12 dashboard counts loaded credentials', 'app/static/js/usage.js',
     'usable: p.usable', 'usable: p.creds_loaded', ['tests/test_hub_pool_frontend.py']),
]

originals = {name: (ROOT / name).read_text() for _, name, *_ in MUTATIONS}
failed = []
try:
    with (HERE / 'mutations.txt').open('w') as log:
        for label, name, before, after, tests in MUTATIONS:
            source = originals[name]
            assert source.count(before) == 1, (label, source.count(before))
            (ROOT / name).write_text(source.replace(before, after, 1))
            try:
                result = subprocess.run(
                    [sys.executable, str(HERE / 'run_checks.py'), *tests], cwd=ROOT,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT)},
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
            finally:
                (ROOT / name).write_text(source)
            # pytest exit 1 means assertion failures; crashes/timeouts are not mutation kills.
            killed = result.returncode == 1 and ' failed' in result.stdout
            summary = next((line for line in reversed(result.stdout.splitlines())
                            if ' passed' in line or ' failed' in line), result.stdout[-500:])
            line = f'{label}: {"KILLED" if killed else "NOT KILLED"} — {summary}'
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()
            if not killed:
                failed.append(label)
                (HERE / 'mutation-failure.txt').write_text(result.stdout.replace(str(ROOT), "."))
finally:
    for name, source in originals.items():
        (ROOT / name).write_text(source)
assert not failed, failed
print('All source files restored.', flush=True)
