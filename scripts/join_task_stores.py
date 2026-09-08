"""Join two prepared private task histories, refusing every unresolved collision."""
import argparse
import json
from pathlib import Path
import subprocess
from app.task_store import TaskStore


def join(laptop: Path, vps: Path, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(destination)
    subprocess.run(['git', 'clone', '--no-hardlinks', str(laptop), str(destination)],
                   check=True, capture_output=True, timeout=120)
    store = TaskStore(destination, origin='')
    store._git('remote', 'remove', 'origin')
    store._git('fetch', str(vps), 'HEAD')
    result = store._git('merge', '--allow-unrelated-histories', '--no-ff', '--no-commit', 'FETCH_HEAD', check=False)
    if result.returncode:
        store._git('merge', '--abort', check=False)
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    try:
        # The initial two histories have no common root. Validate the proposed index
        # before accepting a merge, just as ordinary sync validates its merge tree.
        tree = store._git('write-tree').stdout.strip()
        merged = store._tree_records(tree)
        local = store._tree_records('HEAD')
        remote = store._tree_records('MERGE_HEAD')
        if len(merged) != len(local) + len(remote):
            raise RuntimeError('initial histories still share task IDs; inspect before joining')
        store._git('commit', '-m', 'Join preserved laptop and VPS task histories')
    except BaseException:
        store._git('merge', '--abort', check=False)
        raise
    return store.head


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--laptop', type=Path, required=True)
    parser.add_argument('--vps', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'head': join(**vars(args))}))


if __name__ == '__main__':
    main()
