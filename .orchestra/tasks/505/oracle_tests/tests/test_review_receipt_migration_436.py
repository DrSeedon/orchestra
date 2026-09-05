import json
import subprocess
import sys


def test_migration_keeps_derived_model_and_unknown_outcome_distinct(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "artifacts": [
            {
                "path": ".orchestra/tasks/436/old-review.md",
                "sha256": "0" * 64,
                "size_bytes": 11,
                "model": "gpt-5.6-sol",
                "model_source": "inferred_historical_default",
                "outcome": "unknown",
                "outcome_source": "unknown",
            },
        ],
    }) + "\n")
    db_path = tmp_path / "migration.db"
    script = "scripts/migrate_review_receipts.py"
    result = subprocess.run(
        [sys.executable, script, "--dry-run", "--manifest", str(manifest),
         "--db", str(db_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "T4 migration dry-run must exist and classify the frozen manifest"
    )
    payload = json.loads(result.stdout)
    assert payload["artifacts"][0]["model_source"] == "derived"
    assert payload["artifacts"][0]["outcome"] == "unknown"
    assert payload["artifacts"][0]["outcome_source"] == "unknown"


def test_apply_writes_the_full_receipt_row_for_every_declared_column(tmp_path):
    """#474 — покрытие ПРИМЕНЕНИЯ, а не только dry-run.

    `_receipt` перечисляет колонки квитанции ДОСЛОВНО, а `_apply_receipts` вставляет
    `receipt.get(key)` по `_REVIEW_RECEIPT_COLUMNS`. Это два владельца одного перечня: колонка,
    добавленная в схему и забытая здесь, даёт `None` в `NOT NULL` — и падает только на
    применении. До #474 применение не было покрыто ничем, поэтому дыра и дожила: dry-run
    зелен при любом расхождении, потому что в базу не пишет.
    """
    import hashlib
    import sqlite3

    from app.db import _REVIEW_RECEIPT_COLUMNS

    root = tmp_path / "root"
    (root / ".orchestra" / "tasks" / "436").mkdir(parents=True)
    artifact = root / ".orchestra" / "tasks" / "436" / "old-review.md"
    artifact.write_bytes(b"legacy review\n")
    payload = artifact.read_bytes()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "artifacts": [
            {
                "path": ".orchestra/tasks/436/old-review.md",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "model": "gpt-5.6-sol",
                "model_source": "inferred_historical_default",
                "outcome": "unknown",
                "outcome_source": "unknown",
                "round": 1,
            },
        ],
    }) + "\n")
    db_path = tmp_path / "apply.db"

    result = subprocess.run(
        [sys.executable, "scripts/migrate_review_receipts.py",
         "--apply", "--confirm-live",
         "--manifest", str(manifest), "--db", str(db_path), "--root", str(root)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT * FROM review_receipts").fetchall()
    finally:
        connection.close()
    assert len(rows) == 1, "applied migration must land exactly one receipt row"
    stored = dict(rows[0])
    # Каждая объявленная колонка обязана быть записана значением, а не NULL: пропуск в
    # дословном перечне `_receipt` виден только так.
    missing = [key for key in _REVIEW_RECEIPT_COLUMNS
               if key not in {"round", "completed_at", "return_code"}
               and stored.get(key) is None]
    assert missing == [], f"migration left NULL in declared columns: {missing}"
