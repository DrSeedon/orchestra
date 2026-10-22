"""Review regressions: single-window accounts, unknown accounts, and offline test isolation."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
MUTATIONS = [
    ('B1 absent 5h window blocks Weekly-only accounts', 'app/hub_pool.py',
     '    values = [_number(window.get("used_pct")) if isinstance(window, dict) else None',
     '    if not any(window.get("window_minutes") == 300 for window in windows if isinstance(window, dict)):\n'
     '        return False\n'
     '    values = [_number(window.get("used_pct")) if isinstance(window, dict) else None',
     'codex_and_grok_weekly_only_real_relay_shape'),
    ('B2 no reported windows grants capacity', 'app/hub_pool.py',
     '    if not isinstance(windows, list) or not windows:\n        return None',
     '    if not isinstance(windows, list) or not windows:\n        return True',
     'accounts_without_windows_stay_unknown'),
    ('B3 shared fixture no longer stubs relay fetching', 'tests/conftest.py',
     '    monkeypatch.setattr(hub_pool, "_fetch_relay_limits", available)',
     '    pass', 'shared_capacity_fixture_prevents_live_relay'),
]
originals = {name: (ROOT/name).read_text() for _,name,*_ in MUTATIONS}
failures=[]
try:
    with (HERE/'review-mutations.txt').open('w') as log:
        for label,name,before,after,selection in MUTATIONS:
            source=originals[name]
            assert source.count(before)==1, (label,source.count(before))
            (ROOT/name).write_text(source.replace(before,after,1))
            try:
                result=subprocess.run([sys.executable,str(HERE/'run_checks.py'),
                                       'tests/test_hub_pool.py','-k',selection],cwd=ROOT,
                                      env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT)},
                                      capture_output=True,text=True,timeout=30)
            finally:
                (ROOT/name).write_text(source)
            killed=result.returncode==1 and ' failed' in result.stdout
            summary=next((line for line in reversed(result.stdout.splitlines()) if ' failed' in line or ' passed' in line),
                         'unexpected test exit')
            line=f'{label}: {"KILLED" if killed else "NOT KILLED"} — {summary}'
            print(line,flush=True)
            log.write(line+'\n');log.flush()
            if not killed:
                failures.append(label)
                (HERE/'review-mutation-failure.txt').write_text((result.stdout+result.stderr).replace(str(ROOT),'.'))
finally:
    for name,source in originals.items():
        (ROOT/name).write_text(source)
assert not failures,failures
assert all((ROOT/name).read_text()==source for name,source in originals.items())
print('All mutated sources restored byte-for-byte.',flush=True)
