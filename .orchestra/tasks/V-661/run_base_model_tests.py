from pathlib import Path
import os
import re
import shutil
import subprocess


REPO = Path('/home/kesha/orchestra')
RUNS = Path('/home/kesha/orchestra/data/v656-bench/runs')
TREES = Path('/home/kesha/orchestra/data/v656')
TEMP = Path('/home/kesha/orchestra/data/v656-bench/work-V-661/model-tests')
OUT = Path('/home/kesha/orchestra/worktrees/home-kesha-orchestra/grade-bench/.orchestra/tasks/V-661/raw')
PYTHON = '/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python'
BASE = {
    'pidfd': '1fc6beb6',
    'steer': '09d249ee',
    'costbase': 'd80ec7d9',
    'stall': '429d26d1',
    'ident': '13648c8f',
}


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def task_for(label):
    return label.split('-', 1)[0]


def test_paths(patch_path):
    paths = []
    for line in patch_path.read_text(errors='replace').splitlines():
        if line.startswith('+++ b/tests/'):
            path = line[6:]
            if path.endswith('.py') and Path(path).name.startswith('test'):
                paths.append(path)
    return sorted(set(paths))


def main():
    TEMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for run_dir in sorted(RUNS.iterdir()):
        if not run_dir.is_dir():
            continue
        label = run_dir.name
        if os.environ.get('V661_ONLY') and label != os.environ['V661_ONLY']:
            continue
        task = task_for(label)
        if task not in BASE:
            continue
        patch_path = run_dir / 'diff.patch'
        tests = test_paths(patch_path)
        log = OUT / f'model-tests-base-{label}.txt'
        metadata = OUT / f'model-tests-base-{label}.meta'
        if not tests:
            log.write_text('NO MODEL-AUTHORED TEST FILES IN diff.patch\n')
            metadata.write_text('pytest not run; no changed test file.\n')
            continue
        worktree = TEMP / label
        if worktree.exists():
            raise FileExistsError(worktree)
        added = run(['git', 'worktree', 'add', '--detach', str(worktree), BASE[task]], REPO)
        if added.returncode:
            raise RuntimeError(f'worktree add failed for {label}: {added.stdout}')
        try:
            filtered = run(['git', 'apply', '--exclude=app/**', str(patch_path)], worktree)
            if filtered.returncode:
                metadata.write_text(f'git apply rc={filtered.returncode}\n{filtered.stdout}')
                raise RuntimeError(f'non-app diff did not apply for {label}: {filtered.stdout}')
            for rel in tests:
                source = TREES / label / rel
                if not source.exists():
                    raise FileNotFoundError(f'{label}: {source}')
                dest = worktree / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            command = ['nice', '-n', '15', PYTHON, '-m', 'pytest', '-q', *tests]
            result = run(command, worktree)
            log.write_text(result.stdout)
            metadata.write_text(
                f'cwd={worktree}\n'
                f'command={" ".join(command)}\n'
                f'changed_tests={", ".join(tests)}\n'
                f'pytest_rc={result.returncode}\n'
            )
        finally:
            removed = run(['git', 'worktree', 'remove', '--force', str(worktree)], REPO)
            if removed.returncode:
                raise RuntimeError(f'worktree cleanup failed for {label}: {removed.stdout}')
    print('baseline model-test checks complete')


if __name__ == '__main__':
    main()
