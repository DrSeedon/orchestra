"""V-910 arm B: index the corpus with Kesha's rag.py (imported read-only) into a separate DB. Run in the bot venv."""
import sqlite3, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, "/opt/kesha-bot")
import rag
OUT = Path("/home/kesha/bench910/b"); OUT.mkdir(exist_ok=True, parents=True)
C = Path("/home/kesha/bench910/corpus")
stub = OUT / "stub_messages.db"
c = sqlite3.connect(stub)
c.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT, timestamp TEXT)"); c.commit(); c.close()
db = OUT / "vec.db"
r = rag.RagMemory(path=db, msg_db=stub)
files = sorted(p for p in C.rglob("*.md"))
t0 = time.time(); n = 0
for i, p in enumerate(files):
    k = r.index_file(str(p.relative_to(C)), p.read_text(encoding="utf-8"))
    n += k
    print(i, len(files), n, round(time.time() - t0), flush=True)
print("DONE chunks", n, "files", len(files), "sec", round(time.time() - t0), flush=True)
