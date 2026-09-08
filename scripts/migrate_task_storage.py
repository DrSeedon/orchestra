"""Prepare a private task-storage migration; never modifies the source service."""
import argparse
import json
from pathlib import Path

from app.task_migration import prepare_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', type=Path, required=True)
    parser.add_argument('--source-repo', type=Path, required=True)
    parser.add_argument('--registry-path', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--mapping-path', type=Path)
    parser.add_argument('--origin', choices=['', 'V'], required=True)
    args = parser.parse_args()
    result = prepare_migration(**vars(args))
    print(json.dumps({'tasks': result['tasks'], 'differences': len(result['differences']),
                      'report': str(args.destination / 'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
