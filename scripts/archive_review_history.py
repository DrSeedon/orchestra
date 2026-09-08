"""Export review history to Markdown beside its private DB, without modifying the DB."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def archive(database: Path) -> tuple[Path, int]:
    database = database.resolve(strict=True)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        rows = [dict(row) for row in connection.execute('SELECT * FROM review_receipts ORDER BY requested_at,receipt_id')]
        operations = [dict(row) for row in connection.execute(
            "SELECT operation_id,accepted_admission_json FROM merge_operations WHERE accepted_admission_json LIKE '%review_coverage%' ORDER BY created_at"
        )]
    now = datetime.now(timezone.utc)
    body = ('# Review history — archived data\n\n'
            f'Snapshot UTC: {now.isoformat()}\n\n'
            'Historical records only. These records do not authorize or block merges.\n\n'
            '## Review and task-run records\n\n```json\n'
            + json.dumps(rows, ensure_ascii=False, indent=2)
            + '\n```\n\n## Historical merge admission snapshots\n\n```json\n'
            + json.dumps(operations, ensure_ascii=False, indent=2) + '\n```\n')
    folder = database.parent / 'archive'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"review-history-{now.strftime('%Y%m%dT%H%M%S%fZ')}.md"
    with path.open('x', encoding='utf-8') as target:
        target.write(body)
    assert path.read_text(encoding='utf-8') == body
    return path, len(rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    path, count = archive(args.database)
    print(f'Archive: {path}; records: {count}; sha256: {hashlib.sha256(path.read_bytes()).hexdigest()}')
