"""Reproducible source-only synthetic profile; writes no data outside this task."""
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
runpy.run_path(str(ROOT / "tests/conftest.py"))  # isolate before importing app
from app import db
import app

TASK = Path(__file__).resolve().parent
baseline_source = (TASK / "baseline_search.py").read_text()
namespace = dict(vars(db))
exec(compile(baseline_source, "<public-baseline-search>", "exec"), namespace)
baseline = namespace["search_logs"]
connection_factory = db._conn


def measure(function, query, dates):
    phases = []
    plans = []
    vm_units = [0]

    class Observed:
        def __enter__(self):
            self.c = connection_factory()
            self.c.set_progress_handler(lambda: vm_units.__setitem__(0, vm_units[0] + 1) or 0, 100)
            return self

        def execute(self, sql, params=()):
            started = time.perf_counter()
            cursor = self.c.execute(sql, params)
            elapsed = time.perf_counter() - started
            if sql.lstrip().startswith("SELECT"):
                phases.append(elapsed)
                if len(phases) == 1:
                    plans.extend(r["detail"] for r in self.c.execute("EXPLAIN QUERY PLAN " + sql, params))
            return cursor

        def __exit__(self, *args):
            return self.c.__exit__(*args)

    db._conn = Observed
    namespace["_conn"] = Observed
    try:
        started = time.perf_counter()
        result = function(query, scope="/synthetic/own", agent="project-orchestrator",
                          date_from=dates[0], date_to=dates[1], limit=8)
        elapsed = time.perf_counter() - started
        return {
            "elapsed_ms": round(elapsed * 1000, 3),
            "first_execute_ms": round(phases[0] * 1000, 3),
            "select_count": len(phases), "vm_steps_approx": vm_units[0] * 100,
            "scanned": result["scanned"], "ids": [r["id"] for r in result["results"]],
            "plan": plans,
        }
    finally:
        db._conn = connection_factory


def main():
    print(json.dumps({
        "sqlite": sqlite3.sqlite_version,
        "app_import": "/<hub-copy>/app/__init__.py",
        "absolute_import_sha256": hashlib.sha256(str(Path(app.__file__).resolve()).encode()).hexdigest(),
        "db_import": "/<hub-copy>/app/db.py",
        "import_is_this_checkout": Path(db.__file__).resolve() == ROOT / "app/db.py",
        "baseline_sha256": hashlib.sha256(baseline_source.encode()).hexdigest(),
        "units": "milliseconds; two samples each in before/after/after/before order, not a production SLA",
    }))
    for count in (512, 2048):
        for size in (64, 65_536):
            db.DB_PATH = TASK / "tmp" / f"profile-{count}-{size}.sqlite"
            db.init_db()
            with db._conn() as c:
                c.executemany(
                    "INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES(?,?,?,?,?,?)",
                    [(sid, "project-orchestrator", scope, scope, "test", "2026-10-01")
                     for sid, scope in (("own", "/synthetic/own"), ("foreign", "/synthetic/foreign"))],
                )
                c.executemany(
                    "INSERT INTO logs(id,session_id,ts,type,content,origin) VALUES(?,?,?,?,?,?)",
                    ((i, "own", f"2026-10-{23 + i % 2}T{i % 24:02}:00:00Z", "text",
                      ("audit-marker " if i > count - 16 else "rare-end-marker " if i == 1 else "noise ")
                      + "z" * size, "unknown") for i in range(1, count + 1)),
                )
                c.executemany(
                    "INSERT INTO logs(id,session_id,ts,type,content,origin) VALUES(?,?,?,?,?,?)",
                    ((count + i, "foreign", "2026-10-24T12:00:00Z", "text", "chaff", "unknown")
                     for i in range(1, count * 2 + 1)),
                )
            for label, query, dates in (
                ("single-day", "audit-marker", ("2026-10-24", "2026-10-24")),
                ("two-day", "audit-marker", ("2026-10-23", "2026-10-24")),
                ("no-date", "audit-marker", (None, None)),
                ("rare-two-day", "rare-end-marker", ("2026-10-23", "2026-10-24")),
                ("missing-two-day", "not-present", ("2026-10-23", "2026-10-24")),
            ):
                before = measure(baseline, query, dates)
                after = measure(db.search_logs, query, dates)
                after_second = measure(db.search_logs, query, dates)
                before_second = measure(baseline, query, dates)
                for trial in (after, after_second, before_second):
                    assert before["ids"] == trial["ids"] and before["scanned"] == trial["scanned"]
                for first, second in ((before, before_second), (after, after_second)):
                    first["elapsed_samples_ms"] = [first["elapsed_ms"], second["elapsed_ms"]]
                    first["elapsed_ms"] = round(statistics.median(first["elapsed_samples_ms"]), 3)
                    first["first_execute_samples_ms"] = [first["first_execute_ms"], second["first_execute_ms"]]
                    first["first_execute_ms"] = round(statistics.median(first["first_execute_samples_ms"]), 3)
                print(json.dumps({"shape": label, "own_rows": count, "foreign_rows": count * 2,
                                  "padding_bytes_per_own_row": size, "before": before, "after": after}))
            for suffix in ("", "-wal", "-shm"):
                db.DB_PATH.with_name(db.DB_PATH.name + suffix).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
