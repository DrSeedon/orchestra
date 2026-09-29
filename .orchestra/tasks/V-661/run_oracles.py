from pathlib import Path
import shutil
import subprocess
import sys


REPO = Path('/home/kesha/orchestra')
DATA = Path('/home/kesha/orchestra/data/v656')
OUT = Path('/home/kesha/orchestra/worktrees/home-kesha-orchestra/grade-bench/.orchestra/tasks/V-661/raw')
PYTHON = '/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python'
CASES = {
    'pidfd': ('1fc6beb6', '180a5a4f', 'tests/test_pidfd_leaks.py'),
    'steer': ('09d249ee', 'b15940ba', 'tests/test_durable_steering_562.py'),
    'costbase': ('d80ec7d9', '2dcbfba9', 'tests/test_p4_cost.py'),
    'stall': ('429d26d1', '4cc2e45c', 'tests/test_stall_signals_642.py'),
    'ident': ('13648c8f', '0c3c0fcb', 'tests/test_identity_drift.py'),
}


def run(cmd, *, cwd=None):
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    temp_root = Path('/home/kesha/orchestra/data/v656-bench/work-V-661/oracles')
    temp_root.mkdir(parents=True, exist_ok=True)
    for task, (base, reference, test) in CASES.items():
        source_test = next((DATA / f'{task}-{model}-{eff}' / test for model in ('o55', 's55') for eff in ('medium', 'high', 'max') if (DATA / f'{task}-{model}-{eff}' / test).exists()), None)
        if source_test is None:
            raise FileNotFoundError(f'no oracle source for {task}: {test}')
        for kind, commit in (('base', base), ('reference', reference)):
            path = temp_root / f'{kind}-{task}'
            log = OUT / f'oracle-{kind}-{task}.txt'
            if path.exists():
                raise FileExistsError(path)
            add = run(['git', 'worktree', 'add', '--detach', str(path), commit], cwd=REPO)
            if add.returncode:
                log.write_text(add.stdout)
                raise RuntimeError(f'worktree add failed for {task}/{kind}: {add.stdout}')
            try:
                dest = path / test
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_test, dest)
                result = run(['nice', '-n', '15', PYTHON, '-m', 'pytest', test, '-q'], cwd=path)
                log.write_text(result.stdout)
                (OUT / f'oracle-{kind}-{task}.rc').write_text(f'{result.returncode}\n')
            finally:
                removal = run(['git', 'worktree', 'remove', '--force', str(path)], cwd=REPO)
                if removal.returncode:
                    raise RuntimeError(f'worktree cleanup failed for {path}: {removal.stdout}')
    print('oracle checks complete')


if __name__ == '__main__':
    main()
