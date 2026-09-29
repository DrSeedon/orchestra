from pathlib import Path
import shutil
import subprocess

REPO = Path('/home/kesha/orchestra')
RUNS = Path('/home/kesha/orchestra/data/v656-bench/runs')
TREES = Path('/home/kesha/orchestra/data/v656')
TEMP = Path('/home/kesha/orchestra/data/v656-bench/work-V-667/model-tests')
OUT = Path(__file__).parent / 'raw'
PYTHON = '/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python'
BASE = {
    'pidfd': '1fc6beb6',
    'steer': '09d249ee',
    'costbase': 'd80ec7d9',
    'stall': '429d26d1',
    'ident': '13648c8f',
}


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)


def test_paths(patch_path):
    return sorted({line[6:] for line in patch_path.read_text(errors='replace').splitlines()
                   if line.startswith('+++ b/tests/') and line.endswith('.py')
                   and Path(line[6:]).name.startswith('test')})


def main():
    TEMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for run_dir in sorted(RUNS.glob('*-r2')):
        label = run_dir.name
        task = label.split('-', 1)[0]
        tests = test_paths(run_dir / 'diff.patch')
        log = OUT / f'model-tests-base-{label}.txt'
        meta = OUT / f'model-tests-base-{label}.meta'
        if not tests:
            log.write_text('NO MODEL-AUTHORED TEST FILES IN diff.patch\n')
            meta.write_text('pytest not run; no changed test file.\n')
            continue
        worktree = TEMP / label
        added = run(['git', 'worktree', 'add', '--detach', str(worktree), BASE[task]], REPO)
        if added.returncode:
            raise RuntimeError(f'worktree add failed for {label}: {added.stdout}')
        try:
            applied = run(['git', 'apply', '--exclude=app/**', str(run_dir / 'diff.patch')], worktree)
            if applied.returncode:
                raise RuntimeError(f'non-app diff did not apply for {label}: {applied.stdout}')
            for rel in tests:
                source = TREES / label / rel
                if not source.exists():
                    raise FileNotFoundError(source)
                dest = worktree / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            command = ['nice', '-n', '15', PYTHON, '-m', 'pytest', '-q', *tests]
            result = run(command, worktree)
            log.write_text(result.stdout)
            meta.write_text(f'cwd={worktree}\ncommand={" ".join(command)}\n'
                            f'changed_tests={", ".join(tests)}\npytest_rc={result.returncode}\n')
            print(f'{label}: pytest rc={result.returncode}; {tests}', flush=True)
        finally:
            removed = run(['git', 'worktree', 'remove', '--force', str(worktree)], REPO)
            if removed.returncode:
                raise RuntimeError(f'worktree cleanup failed for {label}: {removed.stdout}')


if __name__ == '__main__':
    main()
