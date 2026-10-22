"""V-1024 follow-up: reason policy mutations, sequential and always restored."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REASONS = 'tests/test_hub_model_reason.py'
MUTATIONS = [
    ('R1 central reason rule disabled', 'app/models.py',
     'return resolve_model(model).startswith("hub-claude-")', 'return False',
     [REASONS, '-k', 'claude_exception_requires']),
    ('R2 spawn tool drops reason', 'app/mcp_stdio.py',
     '    if model_reason:\n        body["model_reason"] = model_reason\n    if mcp_servers:',
     '    if mcp_servers:', [REASONS, '-k', 'tools_forward and spawn']),
    ('R3 change tool drops reason', 'app/mcp_stdio.py',
     '    if model_reason:\n        body["model_reason"] = model_reason\n    result = await _api("POST", f"/api/sessions/{name}/change-model", json=body)',
     '    result = await _api("POST", f"/api/sessions/{name}/change-model", json=body)',
     [REASONS, '-k', 'tools_forward and change']),
    ('R4 direct spawn bypasses reason rule', 'app/manager.py',
     'model_reason = validate_model_reason(model, model_reason)', 'model_reason = ""',
     [REASONS, '-k', 'direct_spawn_cannot_bypass']),
    ('R5 session model change bypasses reason rule', 'app/session.py',
     'reason = validate_model_reason(new_model, model_reason)', 'reason = model_reason',
     [REASONS, '-k', 'direct_model_change_refuses']),
    ('R6 reason not persisted', 'app/db.py',
     'VALUES (:id, :model, :model_reason)', "VALUES (:id, :model, '')",
     [REASONS, '-k', 'spawn_reason_survives']),
    ('R7 restored session loses reason', 'app/manager.py',
     'model_reason=db_row.get("model_reason", "")', 'model_reason=""',
     [REASONS, '-k', 'spawn_reason_survives']),
    ('R8 model transition persists previous reason', 'app/session.py',
     'return pending[1] if pending and pending[0] == self.model else self.model_reason',
     'return self.model_reason', [REASONS, '-k', 'model_change_persists_reason_atomically']),
    ('R9 card hides reason', 'app/static/js/app.js',
     'const modelReason = _modelReasonBadge(s.model_reason);', 'const modelReason = null;',
     ['tests/test_hub_model_reason_frontend.py']),
    ('R10 header hides reason', 'app/static/js/app.js',
     'const modelReason = _modelReasonBadge(session.model_reason);', 'const modelReason = null;',
     ['tests/test_hub_model_reason_frontend.py']),
    ('R11 change API drops reason', 'app/routes/sessions.py',
     '{"model_reason": req["model_reason"]}', '{"model_reason": ""}',
     [REASONS, '-k', 'change_model_api_enforces']),
    ('R12 named reason bypasses pool gate', 'app/manager.py',
     'await require_hub_capacity(model)', 'None',
     [REASONS, '-k', 'named_reason_does_not_bypass and spawn']),
]
originals = {name: (ROOT / name).read_text() for _, name, *_ in MUTATIONS}
failures = []
try:
    with (HERE / 'reason-mutations.txt').open('w') as log:
        for label, name, before, after, tests in MUTATIONS:
            source = originals[name]
            assert source.count(before) == 1, (label, source.count(before))
            (ROOT / name).write_text(source.replace(before, after, 1))
            try:
                result = subprocess.run([sys.executable, str(HERE / 'run_checks.py'), *tests], cwd=ROOT,
                                        env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH':str(ROOT)},
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=90)
            finally:
                (ROOT / name).write_text(source)
            killed = result.returncode == 1 and ' failed' in result.stdout
            summary = next((line for line in reversed(result.stdout.splitlines())
                            if ' passed' in line or ' failed' in line), result.stdout[-500:])
            line = f'{label}: {"KILLED" if killed else "NOT KILLED"} — {summary}'
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()
            if not killed:
                failures.append(label)
                (HERE / 'reason-mutation-failure.txt').write_text(result.stdout.replace(str(ROOT), "."))
finally:
    for name, source in originals.items():
        (ROOT / name).write_text(source)
assert not failures, failures
assert all((ROOT / name).read_text() == original for name, original in originals.items())
print('Every source file restored byte-for-byte.', flush=True)
