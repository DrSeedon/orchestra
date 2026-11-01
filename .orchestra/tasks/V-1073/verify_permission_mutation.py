"""Exercise the real shell errno regression and a process-local old-predicate mutant."""
import subprocess
import sys

selectors = [
    'tests/test_hub_file_policy_v1073.py::test_actual_shell_unreadable_parent_is_not_missing',
    'tests/test_hub_file_policy_v1073.py::test_actual_shell_missing_and_clean_copies_stay_allowed',
]
old_predicate = '''
async def unsafe_predicate(self, remote_dir):
    hw._check_remote(remote_dir)
    q = shlex.quote(remote_dir)
    found = await self.run(
        f"if test -L {q}; then printf x; elif test -e {q}; then "
        f"test -d {q} && find {q} -iname {hw._COMPANY_FILE} -printf x -quit; fi")
    if found:
        raise hw.HubFilePolicyError(hw._COMPANY_REFUSAL)
hw.HubSsh.assert_file_policy = unsafe_predicate
'''
for label, mutation, expected in [('control', '', 0), ('old test-e predicate mutant', old_predicate, 1)]:
    code = (
        'import pytest, shlex; from app import hub_workspace as hw; '
        + 'exec(' + repr(mutation) + '); '
        + 'raise SystemExit(pytest.main(' + repr([*selectors, '-q']) + '))'
    )
    print(f'\n{label}', flush=True)
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    print(result.stdout, end='', flush=True)
    print(result.stderr, end='', flush=True)
    print(f'exit={result.returncode}, expected={expected}', flush=True)
    if result.returncode != expected:
        raise SystemExit('unexpected permission-regression outcome')
    if expected and ('DID NOT RAISE' not in result.stdout or '2 failed, 3 passed' not in result.stdout):
        raise SystemExit('mutant did not fail both real permission assertions')
print('\nControl passes; old-predicate mutant fails both actual shell permission cases.')
