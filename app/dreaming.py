"""Deterministic idle memory curation. No provider, CLI or LLM calls."""
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from app import db
from app.always_on import start_loop
from app.prompting import WORKER_MEMORY_L1_BUDGET_CHARS

_POINTERS = re.compile(r"^## Active Progress Pointers\n.*?(?=^## |\Z)",re.M | re.S)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _open_pointers(scope,worker="",session_id=""):
    with db._conn() as c:
        rows = c.execute("""SELECT t.id,t.title,t.status FROM tm_tasks t
            JOIN tm_projects p ON p.id=t.project_id WHERE p.scope=?
            AND t.status NOT IN ('done','paid','cancelled')
            AND (?='' OR t.assignee=? OR (?!='' AND t.worker_session_id=?))
            ORDER BY t.updated_at DESC LIMIT 8""",
            (scope,worker,worker,session_id,session_id)).fetchall()
    return "## Active Progress Pointers\n" + (
        "\n".join(f"- tm_tasks:{r['id']} [{r['status']}] {r['title'][:160]}" for r in rows)
        or "- No open assigned tasks."
    ) + "\n"


def _compact(text,pointers):
    text = _POINTERS.sub("",text).strip()
    budget = WORKER_MEMORY_L1_BUDGET_CHARS - len(pointers) - 2
    # Retain section structure and the most recent bullets in each section.
    sections = []
    for line in text.splitlines():
        if line.startswith("#") or not sections:
            sections.append([line[:200],[]])
        elif line.strip():
            sections[-1][1].append(line[:500])
    headings = "\n".join(s[0] for s in sections)
    if len(headings) > budget:
        headings = headings[:budget]
        return headings + "\n\n" + pointers
    remaining = budget-len(headings)
    selected = [[] for _ in sections]
    # Round-robin from the latest sections prevents an early verbose section
    # from crowding out recent findings.
    for depth in range(max((len(s[1]) for s in sections),default=0)):
        for i in reversed(range(len(sections))):
            bullets = sections[i][1]
            if depth < len(bullets):
                line = bullets[-depth-1]
                if len(line)+1 <= remaining:
                    selected[i].insert(0,line)
                    remaining -= len(line)+1
    body = "\n".join("\n".join([s[0],*selected[i]]) for i,s in enumerate(sections))
    return body + "\n\n" + pointers


def _record(kind,ref,source_hash,output,now):
    with db._conn() as c:
        c.execute("""INSERT OR IGNORE INTO dreaming_runs
            (target_kind,target_ref,source_hash,output_ref,created_at) VALUES (?,?,?,?,?)""",
            (kind,ref,source_hash,str(output),now))


def _seen(kind,ref,source_hash):
    with db._conn() as c:
        return c.execute("SELECT 1 FROM dreaming_runs WHERE target_kind=? AND target_ref=? AND source_hash=?",
                         (kind,ref,source_hash)).fetchone() is not None


def _write(path,text):
    temporary = path.with_suffix(".dreaming-tmp")
    temporary.write_text(text,encoding="utf-8")
    temporary.replace(path)


def run_dreaming_pass(manager=None, *,now=None):
    if manager is not None and any(str(getattr(s.status,"value",s.status)) == "running"
                                   for s in manager.sessions.values()):
        return {"worker_memories":0,"session_digests":0,"skipped_busy":True}
    now = time.time() if now is None else now
    result = {"worker_memories":0,"session_digests":0,"skipped_busy":False}
    with db._conn() as c:
        scopes = [r[0] for r in c.execute("SELECT scope FROM tm_projects WHERE scope IS NOT NULL AND scope!=''")]
        archived = c.execute("""SELECT * FROM sessions WHERE status='archived' AND total_turns>=12
            AND julianday(COALESCE(finished_at,created_at)) >= julianday(?) - 30""",
            (datetime.fromtimestamp(now,timezone.utc).isoformat(),)).fetchall()
    for scope in scopes:
        root = Path(scope)/".orchestra"/"workers"
        if not root.is_dir() or root.is_symlink() or root.parent.is_symlink():
            continue
        for path in sorted(root.glob("*.md")):
            if path.is_symlink():
                continue
            raw = path.read_bytes()
            text = raw.decode("utf-8",errors="replace")
            pointers = _open_pointers(scope,path.stem)
            current = _POINTERS.search(text)
            no_open = "- No open assigned tasks." in pointers
            if len(text) <= WORKER_MEMORY_L1_BUDGET_CHARS:
                if current and current.group() == pointers:
                    continue
                if current is None and no_open:
                    continue
            source_hash = _hash(raw)
            # A known input is skipped only if its pointers are still current.
            if _seen("worker_memory",str(path),source_hash) and current and current.group() == pointers:
                continue
            archive_dir = root/"archive"
            if archive_dir.is_symlink():
                continue
            archive_dir.mkdir(exist_ok=True)
            archive = archive_dir/f"{path.stem}-{int(now)}-{source_hash[:8]}.md"
            if not archive.exists():
                archive.write_bytes(raw)
            compacted = _compact(text,pointers)
            _write(path,compacted)
            _record("worker_memory",str(path),source_hash,archive,now)
            result["worker_memories"] += 1
    for row in archived:
        if row["scope"] not in scopes:
            continue
        digest_hash = _hash(str(tuple(row[k] for k in ("id","last_summary","branch","total_turns","task_id"))).encode())
        if _seen("archived_session",row["id"],digest_hash):
            continue
        root = Path(row["scope"])/".orchestra"/"workers"
        digest_dir = root/"digests"
        if root.is_symlink() or root.parent.is_symlink() or digest_dir.is_symlink():
            continue
        digest_dir.mkdir(parents=True,exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]","-",Path(row["scope"]).name)[:60]
        digest = digest_dir/f"{slug}-{_hash(row['scope'].encode())[:8]}.md"
        if digest.is_symlink():
            continue
        text = (f"## {row['name']} ({row['id']})\n"
                f"- task_id: {row['task_id']}; branch: {row['branch']}; turns: {row['total_turns']}\n"
                f"- Summary: {row['last_summary'][:2000]}\n"
                + _open_pointers(row["scope"],row["name"],row["id"]) + "\n")
        previous = digest.read_text() if digest.exists() else ""
        # Keep newest records first; trim by UTF-8 bytes, not characters.
        merged = (text+previous).encode()[:8192].decode("utf-8",errors="ignore")
        _write(digest,merged)
        _record("archived_session",row["id"],digest_hash,digest,now)
        result["session_digests"] += 1
    return result


def list_runs(limit=100):
    with db._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM dreaming_runs ORDER BY id DESC LIMIT ?",
                                         (max(1,min(limit,1000)),))]


def start_dreaming_loop(manager):
    import asyncio
    async def run():
        if manager is not None and any(str(getattr(s.status,"value",s.status)) == "running"
                                       for s in manager.sessions.values()):
            return
        await asyncio.to_thread(run_dreaming_pass, None)
    return start_loop("memory-dreaming",run,300.0)
