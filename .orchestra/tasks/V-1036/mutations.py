"""Finite, offline mutation checks; every source edit is restored in finally."""
import os
import resource
import subprocess
import sys
from pathlib import Path

TASK = Path('.orchestra/tasks/V-1036')
CORE = ['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_delivery_visible_1036.py']
EDGES = [str(TASK / 'check_offline.py')]
MUTATIONS = [
    ('initial-no-failure-record', 'app/initial_deliveries.py',
     'record_delivery_failure(connection, row, initial=True)', 'None', CORE),
    ('initial-no-immediate-wake', 'app/initial_deliveries.py',
     'await notify_message_delivery_failure(delivery_id, manager=manager)', 'None', CORE),
    ('quota-no-id', 'app/quota_queue.py',
     '"delivery_id": delivery_id,', '"omitted_id": delivery_id,', CORE),
    ('quota-no-eta', 'app/quota_queue.py',
     '"eta_at": details.get("eta_at"),', '"eta_at": None,', CORE),
    ('pending-hide-initial', 'app/message_deliveries.py',
     'ON s.name=d.sender AND s.scope=d.scope WHERE s.id=?',
     'ON s.name=d.sender AND s.scope=d.scope WHERE s.id=? AND 0', CORE),
    ('pending-leak-other-sender', 'app/message_deliveries.py',
     'FROM message_deliveries WHERE source_session_id=?',
     'FROM message_deliveries WHERE source_session_id IS NOT NULL OR source_session_id=?', CORE),
    ('mcp-discard-error-receipts', 'app/mcp_stdio.py',
     ' and not accepted_delivery:', ':', EDGES),
    ('initial-cancel-no-route-fallback', 'app/routes/sessions.py',
     'if status == 404:', 'if False:', EDGES),
    ('spawn-skip-admission', 'app/manager.py',
     'require_worker_admission(await get_worker_admission(model))', 'None', EDGES),
    ('idle-create-reads-quota', 'app/manager.py',
     'if planned_initial_turn and not is_orch:', 'if not is_orch:', EDGES),
]


def limit():
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))


failed = []
for name, path, before, after, args in MUTATIONS:
    source = Path(path)
    original = source.read_text()
    assert before in original, name
    try:
        source.write_text(original.replace(before, after))
        with (TASK / f'mutation-{name}.log').open('w') as log:
            run = subprocess.run([sys.executable, *args], stdout=log, stderr=subprocess.STDOUT,
                                 env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                                 timeout=45, preexec_fn=limit)
        killed = run.returncode == 1
        print(f'{name}: {"KILLED" if killed else "SURVIVED/ERROR"} (exit={run.returncode})', flush=True)
        if not killed:
            failed.append(name)
    finally:
        source.write_text(original)

if failed:
    raise SystemExit(f'Unexpected mutation results: {failed}')
print(f'{len(MUTATIONS)}/{len(MUTATIONS)} mutations killed; production sources restored.')
