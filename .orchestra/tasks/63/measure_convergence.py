"""#63 — сходится ли бэкфилл после правки. Замер на КОПИИ живого vec.db и живом корпусе.

Повторяет цикл `rag_service.backfill_scope` один в один (тот же порядок слоёв, тот же
раздел бюджета), но без executors: write-executor всё равно однопоточный.

Запуск: /home/kesha/orchestra/.venv/bin/python docs/tasks/63/measure_convergence.py [проходов]
Пишет в stdout по строке на проход. Прод не трогает — работает по копии индекса.
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/back")

from app import rag  # noqa: E402

PROJECT = "/home/kesha/orchestra"
ROOT = Path(PROJECT)
ORCHESTRA_DB = Path("/home/kesha/orchestra/data/orchestra.db")
SRC = Path("/home/kesha/orchestra/data/vec.db")
COPY = Path("/tmp/back63_vec.db")
BUDGET = 300.0
FILE_SLICE = 5
LOG_SLICE = 100


def one_pass(mem) -> tuple[int, int, float]:
    files = logs = 0
    deadline = time.monotonic() + BUDGET
    started = time.monotonic()
    while True:
        now = time.monotonic()
        f = mem.backfill_files(PROJECT, ROOT, FILE_SLICE, now + (deadline - now) / 2)
        l = mem.backfill_logs(PROJECT, ORCHESTRA_DB, LOG_SLICE, None, deadline)
        files += f
        logs += l
        if (f == 0 and l == 0) or time.monotonic() >= deadline:
            break
    return files, logs, time.monotonic() - started


def main() -> None:
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(COPY) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy(SRC, COPY)
    mem = rag.RagMemory(path=COPY)
    print(f"старт: долг {mem.pending_files(PROJECT, ROOT)} файлов", flush=True)
    for i in range(1, passes + 1):
        files, logs, elapsed = one_pass(mem)
        pending = mem.pending_files(PROJECT, ROOT)
        print(f"проход {i}: {files} файлов, {logs} логов, {elapsed:.0f} с, долг {pending}",
              flush=True)


if __name__ == "__main__":
    main()
