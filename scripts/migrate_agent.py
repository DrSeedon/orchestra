#!/usr/bin/env python3
"""Migrate an Orchestra orchestrator (with all its workers) between two servers.

Copies the FULL durable state of an agent so it resumes with intact context on the
target host: SQLite rows (sessions + logs + inbox + subagents), the CLI transcript
(~/.claude/projects/<enc-cwd>/<session_id>.jsonl [+ v2.1 <id>/ subdir]), the git
worktrees, .orchestra/workers/<name>.md and the project CLAUDE.md.

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
  - CLI transcript dir : app.manager.enc_cli_dir (leading '-' kept, '.' → '-')
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
from pathlib import Path, PurePosixPath

# ── path encodings ──
# Owner: app.manager.enc_cli_dir. Import, do not copy — the previous inline
# body drifted from change-scope (#200) and from the live CLI (#195).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.manager import enc_cli_dir  # noqa: E402


def slugify_repo(repo_root: str) -> str:
    """worktrees/<this>/<name> — mirrors app/workspace.py::_slugify.

    Feed it the REPOSITORY ROOT, never the session scope. The platform builds the directory
    from `_slugify(str(repo))` on purpose (`create_worktree`): one scope can hold several
    independent repositories — seedon keeps `site/` and `infra/` inside the project directory,
    each with its own origin. Slugging the scope puts the migrated copy in a directory the
    platform will never look in (#67, #69).
    """
    slug = re.sub(r"[^a-zA-Z0-9]", "-", repo_root).strip("-")
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


def git_at(host: str, repo: str, args: str, *, check: bool = True) -> subprocess.CompletedProcess:
    """Run git over ssh inside a repo owned by somebody else.

    We log in as root while the repo belongs to the service user, so git refuses with
    "dubious ownership". The exception is passed per command and never written into the
    login user's global config: that would be a permanent change on a machine we are
    only visiting, and it would grant root access it does not need after we leave.
    """
    return ssh(host, f"git -c safe.directory={repo!r} -C {repo!r} {args}", check=check)


def worker_repo(host: str, row: dict, fallback_scope: str) -> str:
    """Repository that OWNS this worker's worktree, asked of git — not guessed from scope.

    `scope` is the project directory; the repository is whatever `--git-common-dir` says.
    They differ whenever a project keeps independent repositories inside itself (seedon has
    `site/` and `infra/`, each with its own origin). Bundling from the scope in that case
    fetches a repository that does not contain the worker's branch at all (#67, #69).

    `safe.directory` is passed per command and never written into the login user's config:
    we visit as root while the checkout belongs to the service user.
    """
    wt = row.get("worktree_path") or ""
    if wt:
        r = ssh(
            host,
            f"cd {wt!r} && cd \"$(git -c safe.directory='*' rev-parse --git-common-dir)/..\" && pwd",
            check=False,
        )
        root = r.stdout.strip()
        if r.returncode == 0 and root:
            return root
        detail = r.stderr.strip() or f"exit {r.returncode}"
        log(f"⚠ cannot read the repository of '{row['name']}' from {wt} on {host}: {detail} — "
            f"falling back to the scope {fallback_scope}. If this project keeps nested "
            f"repositories, that fallback is wrong: verify before trusting the migration.")
    return fallback_scope.rstrip("/")


def unit_service_user(host: str, unit: str) -> str:
    """``User=`` of a LOADED systemd unit; '' when the unit isn't there.

    ``LoadState`` has to be read alongside: ``systemctl show <missing-unit> -p User``
    prints an empty ``User=`` and exits 0 — indistinguishable from a live unit running
    as root. Same trap as ``OOMScoreAdjust`` (see CLAUDE.md: a check that prints the same
    on success and on failure is not a check). Empty ``User=`` on a loaded unit is
    systemd's default, i.e. root.
    """
    r = ssh(host, f"systemctl show {unit!r} -p LoadState -p User", check=False)
    if r.returncode != 0:
        return ""
    fields = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    if fields.get("LoadState") != "loaded":
        return ""
    return fields.get("User", "").strip() or "root"


def target_service_user(host: str, orch_root: str, unit: str) -> tuple[str, str]:
    """Who Orchestra actually runs as on `host`, plus that user's home.

    Ground truth is the systemd unit, NOT the ssh login and NOT the owner of the
    installation directory: we log in as root, and a checkout can sit under a foreign
    owner while the service runs as someone else — that is exactly the state this VPS
    was in on 2026-08-03 (3021 root-owned files under `User=kesha`). Handing files to
    the directory's owner in that moment would recreate the bug being fixed, and report
    success. Anything left behind as the wrong user is unusable to the service: git
    refuses with "dubious ownership", and '~' resolves to /root.
    """
    user = unit_service_user(host, unit)
    if user:
        log(f"service user on {host}: {user} (from systemd unit '{unit}')")
    else:
        user = ssh(host, f"stat -c %U {orch_root!r}").stdout.strip()
        if not user:
            die(f"cannot determine the owner of {orch_root} on {host}")
        log(f"⚠ systemd unit '{unit}' is not loaded on {host} — falling back to the owner "
            f"of {orch_root}: {user}. This is a guess, not the service identity: verify it "
            f"before trusting the migration (pass --to-unit/--from-unit if the unit is named "
            f"differently).")
    home = ssh(host, f"getent passwd {user!r} | cut -d: -f6").stdout.strip()
    if not home:
        die(f"cannot determine the home directory of user '{user}' on {host}")
    log(f"  home {home}")
    return user, home


def _foreign_entries(host: str, path: str, user: str) -> list[str]:
    """Entries under `path` not owned by `user`.

    Fails loud when the path cannot be inspected. The previous form
    (`find … 2>/dev/null | wc -c`) printed 0 both when everything was already owned and
    when the path did not exist at all — certifying a chown that never happened.
    """
    r = ssh(
        host,
        f"test -e {path!r} || exit 66; find {path!r} ! -user {user!r} -printf '%p\\n'",
        check=False,
    )
    if r.returncode == 66:
        die(f"{path} does not exist on {host} — nothing to hand over to '{user}'")
    if r.returncode != 0:
        detail = r.stderr.strip() or f"exit {r.returncode}"
        die(f"cannot inspect ownership of {path} on {host}: {detail}")
    return [line for line in r.stdout.splitlines() if line]


def _mode_snapshot(host: str, path: str) -> list[str]:
    """`<mode> <path>` for every entry — to prove chown changed owners and nothing else."""
    r = ssh(host, f"find {path!r} -printf '%m %p\\n'", check=False)
    if r.returncode != 0:
        detail = r.stderr.strip() or f"exit {r.returncode}"
        die(f"cannot read permissions of {path} on {host}: {detail}")
    return sorted(line for line in r.stdout.splitlines() if line)


def give_to_service_user(to_host: str, path: str, user: str) -> None:
    """Hand a freshly created path to the service user, and prove it took effect."""
    before = _foreign_entries(to_host, path, user)
    modes_before = _mode_snapshot(to_host, path)
    ssh(to_host, f"chown -R {user}:{user} {path!r}")
    after = _foreign_entries(to_host, path, user)
    if after:
        die(f"chown -R {user} did not take on {path}: {len(after)} entries still foreign, "
            f"e.g. {', '.join(after[:3])}")
    modes_after = _mode_snapshot(to_host, path)
    if modes_after != modes_before:
        changed = [m for m in modes_after if m not in set(modes_before)][:3]
        die(f"chown changed permissions under {path} — we change the owner, never the mode: "
            f"{', '.join(changed) or 'entry set differs'}")
    log(f"owner {path} → {user} (было чужих: {len(before)}, режимы не тронуты)")


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


def target_worktree(from_host: str, row: dict, from_scope: str, to_scope: str,
                    to_orch: str) -> tuple[str, str, str]:
    """``(src_repo, dst_repo, new_worktree_path)`` — единый расчёт для транскрипта, git и БД.

    Считается ОДИН раз на воркера: расходящиеся копии этой формулы уже стоили нам того, что
    перенесённая копия оказывалась в каталоге, куда платформа не смотрит.
    """
    src_repo = worker_repo(from_host, row, from_scope)
    dst_repo = rewrite_path(src_repo, from_scope, to_scope)
    new_wt = f"{to_orch.rstrip('/')}/worktrees/{slugify_repo(dst_repo)}/{row['name']}"
    return src_repo, dst_repo, new_wt


def migrate_git(from_host, to_host, row, src_repo, dst_repo, new_wt, to_user) -> str | None:
    """Push worker branch (if any), recreate worktree on target. Returns new worktree_path or None."""
    wt = row.get("worktree_path") or ""
    branch = row.get("branch") or ""
    if not wt:
        return None  # orchestrator: works directly in scope, no worktree

    wt_parent = str(PurePosixPath(new_wt).parent)
    exists = ssh(to_host, f"test -d {dst_repo!r}/.git && echo yes || echo no").stdout.strip()
    if exists != "yes":
        die(f"target repository {dst_repo} does not exist on {to_host} (worker "
            f"'{row['name']}' lives in {src_repo}, which is not the scope root). Clone or "
            f"copy it there first — migrating the worker into the wrong repository would "
            f"silently give it someone else's history")

    # Ensure the branch exists on the target repo. Simplest robust path:
    # bundle the worker branch from source and fetch it on target.
    if branch:
        bundle_remote = f"/tmp/orch_{row['name']}.bundle"
        # bundle from the repository that OWNS the worktree (it shares .git objects) — not
        # from the scope. Errors are NOT swallowed: a lost bundle means lost worker commits,
        # and `git worktree add` below would then fail with "invalid reference" — the
        # symptom, never the cause.
        b = git_at(from_host, src_repo, f"bundle create {bundle_remote} {branch}", check=False)
        if b.returncode != 0:
            die(f"git bundle create failed for branch '{branch}' on {from_host}: "
                f"{b.stderr.strip() or f'exit {b.returncode}'}")
        _relay_file(from_host, to_host, bundle_remote, bundle_remote)
        f = git_at(to_host, dst_repo, f"fetch {bundle_remote} {branch}:{branch}", check=False)
        if f.returncode != 0:
            die(f"git fetch of the worker bundle failed on {to_host} (branch '{branch}'): "
                f"{f.stderr.strip() or f'exit {f.returncode}'}")
        ssh(from_host, f"rm -f {bundle_remote}")
        ssh(to_host, f"rm -f {bundle_remote}")

    ssh(to_host, f"mkdir -p {wt_parent!r}")
    # remove any stale worktree at this path, then add fresh. Fail loud — a missing
    # branch here means the bundle didn't carry the worker's commits (data loss risk).
    git_at(to_host, dst_repo, f"worktree remove --force {new_wt!r}", check=False)
    ref = branch or "HEAD"
    r = git_at(to_host, dst_repo, f"worktree add {new_wt!r} {ref!r}", check=False)
    if r.returncode != 0:
        die(f"git worktree add failed for '{row['name']}' (ref={ref}): {r.stderr.strip()}")
    # Everything above ran over ssh as the login user. Left that way, Git refuses to work
    # for the service user and worker_wip / kill_worker start failing — which leaves
    # force-kill as the only route and drops the unmerged-work guard.
    # The worktree alone is NOT enough: for a linked worktree Git also checks the gitdir
    # (.git/worktrees/<name>), and a commit additionally locks .git/refs/heads/<branch>.
    # Miss the target repo's .git and the migrated worker can read but never commit —
    # which is worse than a loud failure, because it looks healthy.
    give_to_service_user(to_host, new_wt, to_user)
    give_to_service_user(to_host, wt_parent, to_user)
    give_to_service_user(to_host, f"{dst_repo.rstrip('/')}/.git", to_user)
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
    """CLAUDE.md + .orchestra/workers/<name>.md — travel with the scope repo but copy explicitly
    so migration works even if the target repo is behind."""
    ssh(to_host, f"mkdir -p {to_scope}/.orchestra/workers")
    give_to_service_user(to_host, f"{to_scope}/.orchestra/workers", to_user)
    # Copy the import target before its adapter when the destination repo is behind.
    for rel in ["AGENTS.md", "CLAUDE.md"] + [f".orchestra/workers/{n}.md" for n in worker_names]:
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
    ap.add_argument("--to-unit", default="orchestra",
                    help="systemd unit of the target Orchestra — its User= is who owns the "
                         "migrated files (default: orchestra)")
    ap.add_argument("--from-unit", default="orchestra",
                    help="systemd unit of the source Orchestra (default: orchestra)")
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

    to_user, to_home = target_service_user(args.to_host, args.to_orchestra, args.to_unit)
    _, from_home = target_service_user(args.from_host, args.from_orchestra, args.from_unit)

    # 2. per-agent: transcript + git + row + children.
    # Целевой путь считается ОДИН раз на воркера и переиспользуется — транскрипт, worktree и
    # строка БД обязаны говорить об одном и том же каталоге.
    targets: dict[str, tuple[str, str, str]] = {
        r["id"]: target_worktree(args.from_host, r, args.from_scope, args.to_scope,
                                 args.to_orchestra)
        for r in all_rows if r.get("worktree_path")
    }
    for r in all_rows:
        t = targets.get(r["id"])
        if t and t[0].rstrip("/") != args.from_scope.rstrip("/"):
            log(f"[{r['name']}] репозиторий {t[0]} → {t[1]} (вложен в scope, не равен ему)")

    print("→ transcripts")
    for r in all_rows:
        copy_transcript(args.from_host, args.to_host, r.get("session_id"),
                        r["cwd"], rewrite_cwd(r, args, targets), to_user, to_home, from_home)

    print("→ git worktrees")
    new_wts: dict[str, str | None] = {}
    for r in workers:
        src_repo, dst_repo, new_wt = targets[r["id"]]
        new_wts[r["id"]] = migrate_git(args.from_host, args.to_host, r,
                                       src_repo, dst_repo, new_wt, to_user)

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


def rewrite_cwd(row: dict, args, targets: dict[str, tuple[str, str, str]]) -> str:
    """Target cwd for the CLI transcript dir: worktree→worktree, orchestrator→scope.

    Путь воркера берётся из общего расчёта (`target_worktree`), а не пересчитывается здесь:
    транскрипт обязан лечь в тот же каталог, в котором окажется рабочая копия.
    """
    if row.get("worktree_path"):
        return targets[row["id"]][2]
    return rewrite_path(row["cwd"], args.from_scope, args.to_scope)


if __name__ == "__main__":
    main()
