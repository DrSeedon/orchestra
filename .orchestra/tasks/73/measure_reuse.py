"""#73 — цена переиндексации CHANGELOG.md до и после переиспользования эмбеддингов.

Данные РЕАЛЬНЫЕ: две соседние версии файла из git. Синтетика тут дала бы неверную цену —
эмбеддинг стоит пропорционально тексту, а повторяющийся текст ещё и меняет границы чанков.

Плечи считаются от ОДНОГО и того же состояния индекса: v1 индексируется один раз, база
копируется, дальше каждое плечо доиндексирует v2 на своей копии.

Запуск: /home/kesha/orchestra/.venv/bin/python docs/tasks/73/measure_reuse.py [rev1] [rev2]
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/back")

from app import rag  # noqa: E402

REPO = "/home/kesha/orchestra"
BASE = Path("/tmp/back73_base.db")
ARM = Path("/tmp/back73_arm.db")


def version(rev: str) -> str:
    return subprocess.run(["git", "-C", REPO, "show", f"{rev}:CHANGELOG.md"],
                          capture_output=True, text=True).stdout


def fresh(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()


def main() -> None:
    rev1 = sys.argv[1] if len(sys.argv) > 1 else "9122839"
    rev2 = sys.argv[2] if len(sys.argv) > 2 else "114167a"
    v1, v2 = version(rev1), version(rev2)
    c1, c2 = rag._chunk_file("CHANGELOG.md", v1), rag._chunk_file("CHANGELOG.md", v2)
    new_texts = len([c for c in c2 if c not in set(c1)])
    print(f"{rev1} → {rev2}: чанков {len(c1)} → {len(c2)}, новых по тексту {new_texts}", flush=True)

    fresh(BASE)
    mem = rag.RagMemory(path=BASE)
    started = time.monotonic()
    mem.index_file(REPO, "CHANGELOG.md", v1)
    print(f"подготовка (индексация {rev1} с нуля): {time.monotonic() - started:.0f} с", flush=True)
    mem.conn.close()

    for label, reuse in (("после (переиспользование)", True), ("до (как было)", False)):
        fresh(ARM)
        shutil.copy(BASE, ARM)
        arm = rag.RagMemory(path=ARM)
        if not reuse:
            arm._reusable_vectors = lambda _file_id: {}
        started = time.monotonic()
        n = arm.index_file(REPO, "CHANGELOG.md", v2)
        print(f"{label}: {time.monotonic() - started:.0f} с на {n} чанков", flush=True)
        arm.conn.close()


if __name__ == "__main__":
    main()
