"""Copy the final runtime snapshot after stopping the old service; never installs it."""
import argparse
import json
from pathlib import Path

from app.task_migration import finalize_migration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-db', 'source-repo', 'registry-path', 'prepared', 'destination'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--mapping-path', type=Path)
    parser.add_argument('--origin', choices=['', 'V'], required=True)
    print(json.dumps(finalize_migration(**vars(parser.parse_args()))))


if __name__ == '__main__':
    main()
