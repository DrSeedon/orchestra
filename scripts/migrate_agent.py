#!/usr/bin/env python3
"""Migrate an Orchestra orchestrator (with all its workers) between two servers.

Copies the FULL durable state of an agent so it resumes with intact context on the
target host: SQLite rows (sessions + logs + inbox + subagents), the CLI transcript
(~/.claude/projects/<enc-cwd>/<session_id>.jsonl [+ v2.1 <id>/ subdir]), the git
worktrees, docs/workers/<name>.md and the project CLAUDE.md.

Runs from anywhere; drives both hosts over SSH. Source paths are rewritten to the
target's orchestra root / scope root.

    python scripts/migrate_agent.py \
        --name ParsingMaxim \
        --from root@laptop --to root@158.220.127.161 \
        --from-orchestra /mnt/data/Projects/Python/orchestra \
        --to-orchestra   /home/kesha/orchestra \
        --from-scope /mnt/data/Projects/Python/Parsing \
        --to-scope   /home/kesha/projects/Parsing

Two path encodings are handled (matching the app):
  - CLI transcript dir : cwd.replace('/', '-')                      (leading '-' kept)
  - worktree subdir    : <root>/worktrees/<slugify(scope)>/<name>   (lowercased)

Everything is created over ssh as root, but Orchestra and the Claude CLI run as the
service user — so every path we write is handed over with chown and verified.

Preconditions (fail loud): the orchestrator and every non-archived worker must be IDLE.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath

# ── path encodings (mirror app/manager.py:_migrate_cli_session and app/workspace.py) ──

def enc_cli_dir(cwd: str) -> str:
    """~/.claude/projects/<this> — cwd with '/'→'-'. Case preserved.

    The leading '-' (from the leading '/') is part of the name and must stay:
    stripping it produced a directory the CLI never reads, so transcripts were
    written beside the real ones and every migrated agent silently resumed with
    no history. Verified against 23 real (cwd → dirname) pairs read out of the
    transcripts themselves: with the strip 0/23 matched, without it 23/23.
    """
    return cwd.replace("/", "-")


def slugify_scope(scope: str) -> str:
    """worktrees/<this>/<name> — app/workspace.py _slugify: non-alnum→'-', collapse, lower."""
    slug = re.sub(r"[^a-zA-Z0-9]", "-", scope).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug.lower()[:80]


def rewrite_path(path: str, src_prefix: str, dst_prefix: str) -> str:
    """Swap a leading src_prefix for dst_prefix. No-op if path doesn't start with it."""
    if not path:
        return path
    sp = src_prefix.rstrip("/")
    if path == sp:
        return dst_prefix.rstrip("/")
    if path.startswith(sp + "/"):
        return dst_prefix.rstrip("/") + path[len(sp):]
    return path


# ── SSH plumbing ──

def ssh(host: str, cmd: str, *, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", host, cmd],
        check=check, text=True,
        capture_output=capture,
    )


def scp(src: str, dst: str, *, recursive: bool = False) -> None:
    args = ["scp", "-q", "-o", "BatchMode=yes"]
    if recursive:
        args.append("-r")
    args += [src, dst]
    subprocess.run(args, check=True)


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def log(msg: str) -> None:
    print(f"  {msg}")


def target_service_user(to_host: str, to_orch: str) -> tuple[str, str]:
    """Who Orchestra actually runs as on the target, plus that user's home.

    Derived from the owner of the installation directory, NOT from the ssh login:
    we log in as root, but systemd runs the service under its own user. Anything
    left behind as root is unusable to it — git refuses with "dubious ownership",
    and '~' would resolve to /root instead of the service user's home.
    """
    user = ssh(to_host, f"stat -c %U {to_orch!r}").stdout.strip()
    if not user:
        die(f"cannot determine the owner of {to_orch} on {to_host}")
    home = ssh(to_host, f"getent passwd {user!r} | cut -d: -f6").stdout.strip()
    if not home:
        die(f"cannot determine the home directory of user '{user}' on {to_host}")
    log(f"target service user: {user} (home {home})")
    return user, home


def give_to_service_user(to_host: str, path: str, user: str) -> None:
    """Hand a freshly created path to the service user, and prove it took effect."""
    before = ssh(
        to_host, f"find {path!r} ! -user {user!r} -printf . 2>/dev/null | wc -c",
    ).stdout.strip()
    ssh(to_host, f"chown -R {user}:{user} {path!r}")
    after = ssh(
        to_host, f"find {path!r} ! -user {user!r} -printf . 2>/dev/null | wc -c",
    ).stdout.strip()
    if after != "0":
        die(f"chown -R {user} did not take on {path}: {after} entries still foreign")
    log(f"owner {path} → {user} (было чужих: {before})")


# ── DB access over SSH (sqlite3 CLI on the remote, JSON out) ──

def remote_db(orchestra_root: str) -> str:
    return f"{orchestra_root.rstrip('/')}/data/orchestra.db"


def db_query_json(host: str, db: str, sql: str) -> list[dict]:
    """Run a SELECT on the remote DB, return rows as list of dicts."""
    # -json gives an array of objects; empty result → empty string
    out = ssh(host, f"sqlite3 -json {db!r} {sql!r}").stdout.strip()
    return json.loads(out) if out else []


def db_columns(host: str, db: str, table: str) -> list[str]:
    out = ssh(host, f"sqlite3 {db!r} 'PRAGMA table_info({table})'").stdout.strip()
    # rows: cid|name|type|notnull|dflt|pk
    return [line.split("|")[1] for line in out.splitlines() if line]


def sql_value(v) -> str:
    """Render a Python value as a SQL literal (single-quote escaped)."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def db_exec_script(host: str, db: str, sql_script: str) -> None:
    """Pipe a multi-statement SQL script into remote sqlite3."""
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write(sql_script)
        local_sql = f.name
    remote_sql = f"/tmp/orch_migrate_{PurePosixPath(local_sql).name}"
    scp(local_sql, f"{host}:{remote_sql}")
    # rm must not mask sqlite3's exit code — a trailing `; rm` reports success even
    # when sqlite3 is missing, and the migration silently writes nothing
    ssh(host, f"sqlite3 {db!r} < {remote_sql}; rc=$?; rm -f {remote_sql}; exit $rc")


# ── migration steps ──

def collect_agents(host: str, db: str, orch_name: str) -> tuple[dict, list[dict]]:
    """Return (orchestrator_row, [worker_rows]) — non-archived only."""
    rows = db_query_json(
        host, db,
        f"SELECT * FROM sessions WHERE name = '{orch_name}' "
        f"OR parent_name = '{orch_name}'",
    )
    orch = next((r for r in rows if r["name"] == orch_name), None)
    if orch is None:
        die(f"orchestrator '{orch_name}' not found on source")
        raise SystemExit  # unreachable; satisfies type checker after die()
    workers = [r for r in rows
               if r["name"] != orch_name and r.get("status") != "archived"]
    return orch, workers


def assert_sqlite3(*hosts: str) -> None:
    """Fail before any mutation if a host lacks sqlite3 — the whole migration runs on it."""
    for h in hosts:
        if ssh(h, "command -v sqlite3", check=False).returncode != 0:
            die(f"sqlite3 missing on {h} — install it (apt install sqlite3) and re-run")


def assert_idle(orch: dict, workers: list[dict]) -> None:
    busy = [r["name"] for r in [orch, *workers] if r.get("status") == "running"]
    if busy:
        die(f"agents not IDLE (running): {', '.join(busy)} — stop them first")


def copy_transcript(from_host, to_host, session_id, from_cwd, to_cwd,
                    to_user: str, to_home: str, from_home: str) -> None:
    """Copy <session_id>.jsonl (+ optional <session_id>/ subdir) into target-encoded dir."""
    if not session_id:
        log("no session_id — skipping transcript (fresh agent, nothing to replay)")
        return
    # Explicit homes, never '~': we ssh as root on both ends, while the transcripts
    # live under the service user. '~' silently pointed at /root on both sides.
    src_dir = f"{from_home.rstrip('/')}/.claude/projects/{enc_cli_dir(from_cwd)}"
    dst_dir = f"{to_home.rstrip('/')}/.claude/projects/{enc_cli_dir(to_cwd)}"
    ssh(to_host, f"mkdir -p {dst_dir!r}")

    # flat transcript file
    exists = ssh(from_host, f"test -f {src_dir}/{session_id}.jsonl && echo yes || echo no").stdout.strip()
    if exists != "yes":
        log(f"⚠ transcript {session_id}.jsonl not found on source — agent will resume WITHOUT history")
        return
    _relay_file(from_host, to_host, f"{src_dir}/{session_id}.jsonl", f"{dst_dir}/{session_id}.jsonl")
    log(f"transcript {session_id}.jsonl → {enc_cli_dir(to_cwd)}/")

    # v2.1 nested artifacts (subagents/, tool-results/)
    has_sub = ssh(from_host, f"test -d {src_dir}/{session_id} && echo yes || echo no").stdout.strip()
    if has_sub == "yes":
        _relay_dir(from_host, to_host, f"{src_dir}/{session_id}", f"{dst_dir}/")
        log(f"v2.1 subdir {session_id}/ → {enc_cli_dir(to_cwd)}/")

    # relayed as root — hand the whole project dir to the user the CLI runs as
    give_to_service_user(to_host, dst_dir, to_user)


def _relay_file(from_host, to_host, src, dst) -> None:
    """from_host:src → to_host:dst via a local temp hop (no host↔host trust needed)."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tmp = tf.name
    scp(f"{from_host}:{src}", tmp)
    scp(tmp, f"{to_host}:{dst}")


def _relay_dir(from_host, to_host, src, dst) -> None:
    tmp = tempfile.mkdtemp()
    scp(f"{from_host}:{src}", tmp, recursive=True)
    local = f"{tmp}/{PurePosixPath(src).name}"
    scp(local, f"{to_host}:{dst}", recursive=True)


def migrate_git(from_host, to_host, row, from_scope, to_scope, to_orch, to_user) -> str | None:
    """Push worker branch (if any), recreate worktree on target. Returns new worktree_path or None."""
    wt = row.get("worktree_path") or ""
    branch = row.get("branch") or ""
    if not wt:
        return None  # orchestrator: works directly in scope, no worktree

    new_scope = rewrite_path(row["scope"], from_scope, to_scope)
    new_root = to_orch.rstrip("/")
    new_wt = f"{new_root}/worktrees/{slugify_scope(new_scope)}/{row['name']}"

    # Ensure the branch exists on the target scope repo. Simplest robust path:
    # bundle the worker branch from source and fetch it on target.
    if branch:
        bundle_remote = f"/tmp/orch_{row['name']}.bundle"
        # bundle from the source scope repo (worktree shares .git objects)
        ssh(from_host, f"cd {from_scope!r} && git bundle create {bundle_remote} {branch} 2>/dev/null || true")
        has_bundle = ssh(from_host, f"test -s {bundle_remote} && echo yes || echo no").stdout.strip()
        if has_bundle == "yes":
            _relay_file(from_host, to_host, bundle_remote, bundle_remote)
            ssh(to_host, f"cd {to_scope!r} && git fetch {bundle_remote} {branch}:{branch} 2>/dev/null || true")
            ssh(from_host, f"rm -f {bundle_remote}")
            ssh(to_host, f"rm -f {bundle_remote}")

    ssh(to_host, f"mkdir -p {new_root}/worktrees/{slugify_scope(new_scope)}")
    # remove any stale worktree at this path, then add fresh. Fail loud — a missing
    # branch here means the bundle didn't carry the worker's commits (data loss risk).
    ssh(to_host, f"cd {to_scope!r} && git worktree remove --force {new_wt!r} 2>/dev/null || true")
    ref = branch or "HEAD"
    r = ssh(to_host, f"cd {to_scope!r} && git worktree add {new_wt!r} {ref!r}", check=False)
    if r.returncode != 0 and "dubious ownership" in r.stderr:
        # target checkout belongs to the service user, we ssh as another — one-time exception
        ssh(to_host, f"git config --global --add safe.directory {to_scope!r}", check=False)
        r = ssh(to_host, f"cd {to_scope!r} && git worktree add {new_wt!r} {ref!r}", check=False)
    if r.returncode != 0:
        die(f"git worktree add failed for '{row['name']}' (ref={ref}): {r.stderr.strip()}")
    # Created over ssh as root. Left that way, Git refuses to work in it
    # ("dubious ownership") and worker_wip / kill_worker start failing — which
    # leaves force-kill as the only route and drops the unmerged-work guard.
    give_to_service_user(to_host, new_wt, to_user)
    give_to_service_user(to_host, f"{new_root}/worktrees/{slugify_scope(new_scope)}", to_user)
    log(f"worktree [{row['name']}] → {new_wt}")
    return new_wt


def build_row_upsert(row: dict, cols: list[str],
                     from_scope, to_scope, from_orch, to_orch,
                     new_wt: str | None) -> str:
    """Build INSERT OR REPLACE for one sessions row with rewritten host paths.

    worker:       cwd == worktree_path → both become new_wt.
    orchestrator: worktree_path == '', cwd == scope → rewrite cwd by scope prefix.
    """
    r = dict(row)
    r["scope"] = rewrite_path(r["scope"], from_scope, to_scope)
    if r.get("worktree_path"):
        r["worktree_path"] = new_wt or rewrite_path(r["worktree_path"], from_orch, to_orch)
        r["cwd"] = r["worktree_path"]
    else:
        r["cwd"] = rewrite_path(row["cwd"], from_scope, to_scope)
    # keep AS-IS: id, session_id, session_id_history, model, role, costs, context_pct, parent_*
    vals = ", ".join(sql_value(r.get(c)) for c in cols)
    collist = ", ".join(cols)
    # free UNIQUE(name,scope) if an archived dup exists on target (manager.py:404 pattern)
    return (
        f"DELETE FROM sessions WHERE name = {sql_value(r['name'])} "
        f"AND scope = {sql_value(r['scope'])} AND status = 'archived';\n"
        f"INSERT OR REPLACE INTO sessions ({collist}) VALUES ({vals});\n"
    )


def build_children_copy(from_host, from_db, session_row_id: str,
                        cols_map: dict) -> str:
    """Copy logs/inbox/subagents rows for one session (keyed by sessions.id)."""
    script = ""
    for table in ("logs", "inbox", "subagents"):
        rows = db_query_json(from_host, from_db,
                             f"SELECT * FROM {table} WHERE session_id = '{session_row_id}'")
        if not rows:
            continue
        cols = cols_map[table]
        insert_cols = [c for c in cols if c != "id"]  # let AUTOINCREMENT reassign
        collist = ", ".join(insert_cols)
        script += f"DELETE FROM {table} WHERE session_id = {sql_value(session_row_id)};\n"
        for row in rows:
            vals = ", ".join(sql_value(row.get(c)) for c in insert_cols)
            script += f"INSERT INTO {table} ({collist}) VALUES ({vals});\n"
        log(f"  {table}: {len(rows)} rows [{session_row_id[:8]}]")
    return script


def copy_scope_files(from_host, to_host, from_scope, to_scope, worker_names, to_user) -> None:
    """CLAUDE.md + docs/workers/<name>.md — travel with the scope repo but copy explicitly
    so migration works even if the target repo is behind."""
    ssh(to_host, f"mkdir -p {to_scope}/docs/workers")
    give_to_service_user(to_host, f"{to_scope}/docs/workers", to_user)
    for rel in ["CLAUDE.md"] + [f"docs/workers/{n}.md" for n in worker_names]:
        exists = ssh(from_host, f"test -f {from_scope}/{rel} && echo yes || echo no").stdout.strip()
        if exists == "yes":
            _relay_file(from_host, to_host, f"{from_scope}/{rel}", f"{to_scope}/{rel}")
            # relayed as root into the service user's repo — root-owned files there
            # make the tree unusable to git for the very user that must commit them
            give_to_service_user(to_host, f"{to_scope}/{rel}", to_user)
            log(f"scope file → {rel}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate an Orchestra orchestrator + its workers between servers.")
    ap.add_argument("--name", required=True, help="orchestrator name")
    ap.add_argument("--from", dest="from_host", required=True, help="source ssh host, e.g. root@laptop")
    ap.add_argument("--to", dest="to_host", required=True, help="target ssh host, e.g. root@158.220.127.161")
    ap.add_argument("--from-orchestra", required=True, help="orchestra root on source")
    ap.add_argument("--to-orchestra", required=True, help="orchestra root on target")
    ap.add_argument("--from-scope", required=True, help="project scope path on source")
    ap.add_argument("--to-scope", required=True, help="project scope path on target")
    ap.add_argument("--dry-run", action="store_true", help="print plan, don't mutate target")
    args = ap.parse_args()

    from_db = remote_db(args.from_orchestra)
    to_db = remote_db(args.to_orchestra)

    print(f"▶ Migrating '{args.name}': {args.from_host} → {args.to_host}")
    assert_sqlite3(args.from_host, args.to_host)

    # 1. collect + idle-gate
    orch, workers = collect_agents(args.from_host, from_db, args.name)
    assert_idle(orch, workers)
    all_rows = [orch, *workers]
    print(f"  agents: 1 orchestrator + {len(workers)} workers "
          f"({', '.join(w['name'] for w in workers) or 'none'})")

    if args.dry_run:
        for r in all_rows:
            new_scope = rewrite_path(r["scope"], args.from_scope, args.to_scope)
            print(f"    [{r['role']:12}] {r['name']:24} scope→{new_scope}")
        print("  (dry-run — no changes)")
        return

    cols = db_columns(args.from_host, from_db, "sessions")
    cols_map = {t: db_columns(args.from_host, from_db, t) for t in ("logs", "inbox", "subagents")}

    sql_script = "BEGIN;\n"

    to_user, to_home = target_service_user(args.to_host, args.to_orchestra)
    _, from_home = target_service_user(args.from_host, args.from_orchestra)

    # 2. per-agent: transcript + git + row + children
    print("→ transcripts")
    for r in all_rows:
        copy_transcript(args.from_host, args.to_host, r.get("session_id"),
                        r["cwd"], rewrite_cwd(r, args), to_user, to_home, from_home)

    print("→ git worktrees")
    new_wts: dict[str, str | None] = {}
    for r in workers:
        new_wts[r["id"]] = migrate_git(args.from_host, args.to_host, r,
                                       args.from_scope, args.to_scope,
                                       args.to_orchestra, to_user)

    print("→ DB rows")
    for r in all_rows:
        sql_script += build_row_upsert(r, cols, args.from_scope, args.to_scope,
                                       args.from_orchestra, args.to_orchestra,
                                       new_wts.get(r["id"]))
    print("→ children (logs/inbox/subagents)")
    for r in all_rows:
        sql_script += build_children_copy(args.from_host, from_db, r["id"], cols_map)

    print("→ scope files (CLAUDE.md + worker memory)")
    copy_scope_files(args.from_host, args.to_host, args.from_scope, args.to_scope,
                     [w["name"] for w in workers], to_user)

    sql_script += "COMMIT;\n"
    print("→ applying DB script on target")
    db_exec_script(args.to_host, to_db, sql_script)

    print(f"✓ Migration complete. On target: restart Orchestra — auto_resume_all "
          f"will replay transcripts and bring '{args.name}' + {len(workers)} workers back.")
    print(f"  ⚠ then retire source (kill_worker/archive) so one session_id isn't live on two hosts.")


def rewrite_cwd(row: dict, args) -> str:
    """Target cwd for the CLI transcript dir: worktree→worktree, orchestrator→scope."""
    if row.get("worktree_path"):
        new_scope = rewrite_path(row["scope"], args.from_scope, args.to_scope)
        return f"{args.to_orchestra.rstrip('/')}/worktrees/{slugify_scope(new_scope)}/{row['name']}"
    return rewrite_path(row["cwd"], args.from_scope, args.to_scope)


if __name__ == "__main__":
    main()
