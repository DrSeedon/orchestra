"""Broker side of hub-backed workers (V-1008): on-demand upload, safe sync-back, cleanup.

A hub worker never gets credentials. The platform packs only what the task needs from the
worker's VPS worktree, copies it to a private directory on the hub over SSH, lets the hub
thread edit it there, then imports the result back into the worktree through a validator
(`apply_changes`) and commits it. Nothing is pre-loaded and nothing outlives `release`.

The hub side is untrusted input: whatever comes back is checked for path escape, links,
size and credential shapes before a single byte reaches the worktree.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.hub_outbox import MAX_OUTBOX_BYTES, OUTBOX_NAME
from app import publication_secrets

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_DIR = DATA_DIR / "hub-workspaces"

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_FILES = 20_000

# Copied from the VPS, never resolved through PATH (the hub's uv is a PC relay).
HUB_UV_VERSION = "0.11.28"
HUB_UV_BIN = f".local/share/orchestra/tools/uv/{HUB_UV_VERSION}/bin"
HUB_UV_INSTRUCTIONS = (
    "For a Python copy with pyproject.toml and uv.lock, the broker provisions real uv "
    f"{HUB_UV_VERSION}. In each test shell run:\n"
    f'export PATH="$HOME/{HUB_UV_BIN}:$PATH"\n'
    "uv run --frozen python -m pytest <paths> -q\n"
    "The system uv is a dispatcher to a connected PC; use the provisioned binary. "
    "uv may fetch the locked dependencies from PyPI and write its own cache under HOME; "
    "tests themselves must stay offline. Keep the environment at the default .venv. "
    "If setup or imports fail, report the exact blocker and unrun checks; never replace "
    "the lock or claim another runner is the required check.\n\n"
)

_WS_ID = re.compile(r"^hub-[0-9a-f]{16}$")
_BASE_ID = re.compile(r"^proj-[0-9a-f]{12}$")
_THREAD_ID = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
_SCRUB_SCRIPT = r"""
ws="$1"; tid="$2"
for d in "$HOME/.claude/projects" "$HOME/.cache/claude-cli-nodejs"; do
  [ -d "$d" ] && find "$d" -maxdepth 1 -mindepth 1 -type d -name "*$ws*" -exec rm -rf -- {} +
done
for d in "$HOME/.claude/sessions" "$HOME/.codex/sessions" "$HOME/.grok/sessions"; do
  [ -d "$d" ] && grep -rlF -- "$ws" "$d" 2>/dev/null | xargs -r rm -f --
done
logdir="$3"
if [ "$tid" != "-" ] && [ "$logdir" != "-" ] && [ -d "$logdir" ]; then
  find "$logdir" -maxdepth 1 -type f -name "*$(printf %s "$tid" | tr ':' '-')*" -delete
fi
exit 0
"""
_SAFE_REMOTE = re.compile(r"^/[A-Za-z0-9_./-]+$")

# Directory names that never travel in either direction.
BLOCKED_DIRS = frozenset({
    ".git", ".ssh", ".gnupg", ".aws", ".docker", ".kube", ".claude", ".codex", ".grok",
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
})
BLOCKED_NAMES = frozenset({
    ".mcp.json", ".npmrc", ".pypirc", ".netrc", ".pgpass", ".git-credentials",
    "credentials", "credentials.json", "secrets.json", "token", "id_rsa", "id_ed25519",
    "id_ecdsa", "id_dsa",
})
BLOCKED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".token", ".keystore", ".jks", ".gpg")
_ENV_OK_SUFFIXES = (".example", ".sample", ".template", ".dist")

_SECRET_SHAPES = tuple(pattern for _, pattern in publication_secrets.HUB_SECRET_SHAPES)


def base_id_for(scope: str) -> str:
    return "proj-" + hashlib.sha256(os.path.realpath(scope).encode()).hexdigest()[:12]


def _install_tag() -> str:
    """Several Orchestra installations may share one hub account; each sweeps only its own root."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", socket.gethostname())[:40] or "host"


@dataclass(frozen=True)
class ProjectOptions:
    """Per-project hub settings (data/hub-projects.json, keyed by the project's scope path)."""

    max_total_bytes: int = MAX_TOTAL_BYTES
    max_files: int = MAX_FILES
    max_file_bytes: int = MAX_FILE_BYTES
    persistent: bool = False   # keep a warm copy of the project on the hub between workers


def project_options(scope: str) -> ProjectOptions:
    """Settings for the project at `scope`; the file is read per turn, so edits need no restart."""
    path = Path(os.environ.get("MULTICODE_HUB_PROJECTS_FILE", "").strip() or DATA_DIR / "hub-projects.json")
    try:
        table = json.loads(path.read_text())
        entry = next((v for k, v in table.items()
                      if os.path.realpath(k) == os.path.realpath(scope or "")), None)
    except (OSError, ValueError, AttributeError):
        entry = None
    if not isinstance(entry, dict):
        return ProjectOptions()
    mb = 1024 * 1024

    def number(key: str, default: int, unit: int = 1) -> int:
        value = entry.get(key)
        return int(value * unit) if isinstance(value, (int, float)) and value > 0 else default

    return ProjectOptions(
        max_total_bytes=number("max_total_mb", MAX_TOTAL_BYTES, mb),
        max_files=number("max_files", MAX_FILES),
        max_file_bytes=number("max_file_mb", MAX_FILE_BYTES, mb),
        persistent=entry.get("persistent") is True,
    )


def require_scope(paths: list[str] | None, options: ProjectOptions) -> None:
    """Copy only what the worker needs: only a persistent project may go to the hub without
    an owned_dirs list. Refused before anything is uploaded."""
    if paths or options.persistent:
        return
    raise HubWorkspaceError(
        "this hub worker has no owned_dirs, and only projects marked persistent in data/hub-projects.json "
        "go to the hub whole. Nothing was uploaded. The orchestrator must set owned_dirs: call "
        "set_worker_owned_dirs for this worker with the directories (or files) the task touches; "
        "repo-level files such as CLAUDE.md and pyproject.toml always go along.")


class HubWorkspaceError(RuntimeError):
    """Safe-to-display failure of the broker."""


# ── credential exclusion ─────────────────────────────────────────────────────────────


def blocked_reason(rel: str) -> str | None:
    """Why a worktree-relative path must not cross the boundary, by name alone."""
    if rel == OUTBOX_NAME:
        return "broker outbox file"
    parts = rel.split("/")
    for part in parts[:-1]:
        if part in BLOCKED_DIRS:
            return f"directory {part}"
    name = parts[-1]
    lower = name.lower()
    if name in BLOCKED_DIRS:
        return f"directory {name}"
    if lower in BLOCKED_NAMES:
        return f"credential file name {name}"
    if lower.endswith(BLOCKED_SUFFIXES):
        return f"credential file suffix {name}"
    if lower == ".env" or (lower.startswith(".env.") and not lower.endswith(_ENV_OK_SUFFIXES)):
        return f"env file {name}"
    return None


def known_secret_values(extra: list[str] | None = None) -> list[str]:
    """Literal values of our own credentials: secret-looking environment variables and the
    files under data/secrets. A file or prompt containing one of them must not leave."""
    values = {value for _, value in publication_secrets.literal_rules(
        data_dir=DATA_DIR,
    )}
    values.update(extra or [])
    return sorted((v for v in values if len(v) >= publication_secrets._MIN_LEN), key=len, reverse=True)


def secret_in_text(text: str, known: list[str]) -> str | None:
    for value in known:
        if value in text:
            return "a literal platform credential"
    for shape in _SECRET_SHAPES:
        if shape.search(text):
            return "a credential-shaped string"
    return None


def redact_secrets(text: str, known: list[str]) -> str:
    """Mask credentials inside quoted history. A model switch must not be blocked for good by an
    old chat line, but the credential itself never goes to the hub."""
    for value in known:
        text = text.replace(value, "[redacted]")
    for shape in _SECRET_SHAPES:
        text = shape.sub("[redacted]", text)
    return text


def assert_no_secret(text: str, known: list[str], what: str) -> None:
    reason = secret_in_text(text, known)
    if reason:
        raise HubWorkspaceError(f"{what} contains {reason}; refusing to send it to the hub")


# ── upload plan ──────────────────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _uv_snapshot(scratch: Path) -> tuple[Path, str, str]:
    """Freeze the trusted VPS binary so hashing, validation and upload use the same bytes."""
    source = Path.home() / ".local/bin/uv"
    snapshot = scratch / "uv-upload"
    try:
        shutil.copyfile(source, snapshot)
        with snapshot.open("rb") as handle:
            header = handle.read(20)
        if header[:6] != b"\x7fELF\x02\x01" or header[18:20] != b"\x3e\x00":
            raise HubWorkspaceError("hub uv source ~/.local/bin/uv must be a Linux x86_64 ELF binary")
        snapshot.chmod(0o700)
        result = subprocess.run([str(snapshot), "--version"], capture_output=True, text=True,
                                check=True, timeout=20)
        version = result.stdout.strip()
        if version.split()[:2] != ["uv", HUB_UV_VERSION] or "\n" in version:
            raise HubWorkspaceError(f"hub uv source must be version {HUB_UV_VERSION}")
        return snapshot, sha256_file(snapshot), version
    except (OSError, subprocess.SubprocessError) as exc:
        raise HubWorkspaceError(
            f"cannot prepare hub uv {HUB_UV_VERSION} from ~/.local/bin/uv ({type(exc).__name__})"
        ) from None


@dataclass
class UploadPlan:
    manifest: dict[str, str] = field(default_factory=dict)   # rel path -> sha256
    skipped: list[tuple[str, str]] = field(default_factory=list)
    total_bytes: int = 0
    new_paths: list[str] = field(default_factory=list)       # owned paths that are not in HEAD at all
    materialized: list[str] = field(default_factory=list)    # owned paths pulled in from the sparse cone


def _git_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted({p for p in out.decode("utf-8", "surrogateescape").split("\0") if p})


def _git_out(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None


def _head_files(root: Path, rel: str) -> list[str]:
    """Files committed in HEAD under `rel` (a file or a directory); [] when none or no HEAD yet."""
    done = _git_out(root, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", rel)
    if done is None or done.returncode != 0:
        return []
    return [p for p in done.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def _sparse_state(root: Path) -> tuple[bool, bool]:
    """(sparse checkout enabled, cone mode)."""
    def flag(key: str) -> bool:
        done = _git_out(root, "config", "--get", key)
        return bool(done and done.returncode == 0 and done.stdout.strip().lower() == b"true")
    return flag("core.sparseCheckout"), flag("core.sparseCheckoutCone")


def prepare_scope(root: Path, prefixes: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Make every owned path usable before the upload is planned.

    Returns (in_head, new, materialized):
    * a path with files in HEAD that a sparse checkout left off disk is added to the cone, so the
      hub gets the worker's real work area instead of an empty copy (V-1008);
    * a path that is not in HEAD at all is allowed (the worker may create it) and reported as new.
    A non-git directory has no HEAD, so nothing is known and nothing is changed."""
    if _git_out(root, "rev-parse", "--git-dir") is None:
        return [], [], []
    sparse, cone = _sparse_state(root)
    in_head: list[str] = []
    new: list[str] = []
    materialized: list[str] = []
    for rel in prefixes:
        files = _head_files(root, rel)
        if not files:
            if not (root / rel).exists():
                new.append(rel)
            continue
        in_head.append(rel)
        if not sparse or all(os.path.lexists(root / f) for f in files):
            continue
        # In cone mode only directories can be added: a file asks for its parent directory.
        target = rel.rstrip("/")
        if cone and files == [target]:
            target = target.rpartition("/")[0]
        if target:
            done = _git_out(root, "sparse-checkout", "add", "--", target)
            if done is None or done.returncode != 0:
                detail = done.stderr.decode("utf-8", "replace").strip() if done else "git unavailable"
                raise HubWorkspaceError(
                    f"owned path {rel!r} is committed but outside this worktree's sparse checkout, and "
                    f"`git sparse-checkout add {target}` failed: {detail}. Nothing was uploaded.")
        materialized.append(rel)
    return in_head, new, materialized


def _walk_files(root: Path) -> list[str]:
    found: list[str] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in BLOCKED_DIRS]
        for name in files:
            found.append(os.path.relpath(os.path.join(current, name), root))
    return sorted(found)


def _owned_by(rel: str, prefixes: list[str]) -> bool:
    return any(rel == p.rstrip("/") or rel.startswith(p.rstrip("/") + "/") for p in prefixes)


def _under(rel: str, prefixes: list[str] | None) -> bool:
    if not prefixes:
        return True
    if "/" not in rel:      # repo-level files (CLAUDE.md, pyproject...) always come with a subset
        return True
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in prefixes)


def plan_upload(root: Path, paths: list[str] | None = None,
                known: list[str] | None = None,
                options: ProjectOptions | None = None) -> UploadPlan:
    """Pick the files that may go to the hub: tracked + untracked-not-ignored, restricted to
    `paths` (the worker's owned_dirs) when set, minus everything credential-like.

    Only what is checked out is considered: a sparse worktree lists skip-worktree entries in
    the index but they are absent on disk, so the cone is honoured. Paths that are not uploaded
    are not in the manifest, so a later sync never treats them as deleted."""
    root = root.resolve()
    options = options or ProjectOptions()
    prefixes = [_clean_rel(p) for p in paths] if paths else None
    known = known_secret_values() if known is None else known
    plan = UploadPlan()
    in_head: list[str] = []
    if prefixes:
        in_head, plan.new_paths, plan.materialized = prepare_scope(root, prefixes)
    candidates = _git_files(root)
    if candidates is None:
        candidates = _walk_files(root)
    over: dict[str, int] = {}          # bytes per top-level entry, filled once a limit is hit
    limit_hit = False
    for rel in candidates:
        if not _under(rel, prefixes):
            continue
        full = root / rel
        try:
            info = full.lstat()
        except OSError:
            continue          # tracked but absent (sparse checkout, deleted)
        if not stat.S_ISREG(info.st_mode):
            if stat.S_ISLNK(info.st_mode):
                plan.skipped.append((rel, "symlink"))
            continue
        reason = blocked_reason(rel)
        if reason:
            plan.skipped.append((rel, reason))
            continue
        if info.st_size > options.max_file_bytes:
            plan.skipped.append((rel, "larger than the per-file limit"))
            continue
        if not limit_hit and (plan.total_bytes + info.st_size > options.max_total_bytes
                              or len(plan.manifest) >= options.max_files):
            limit_hit = True
            for done in plan.manifest:
                top = done.split("/", 1)[0] if "/" in done else "(top-level files)"
                over[top] = over.get(top, 0) + (root / done).stat().st_size
        if limit_hit:
            top = rel.split("/", 1)[0] if "/" in rel else "(top-level files)"
            over[top] = over.get(top, 0) + info.st_size
            continue
        if _file_has_secret(full, known):
            plan.skipped.append((rel, "contains a credential"))
            continue
        plan.manifest[rel] = sha256_file(full)
        plan.total_bytes += info.st_size
    if limit_hit:
        biggest = ", ".join(f"{name} ({size // (1024 * 1024)} MiB)"
                            for name, size in sorted(over.items(), key=lambda kv: -kv[1])[:5])
        scope = "owned_dirs is already set but still too big" if prefixes else "no owned_dirs is set"
        raise HubWorkspaceError(
            f"the checked-out tree is too large for the hub (limit {options.max_total_bytes // (1024 * 1024)} MiB / "
            f"{options.max_files} files; {scope}). Narrow what the worker gets: spawn it with owned_dirs=[...] "
            f"naming only the directories the task touches (or set_worker_owned_dirs), use a sparse "
            f"checkout, or raise this project's limits in the hub projects file (max_total_mb / max_files). "
            f"Largest top-level entries: {biggest}")
    if in_head and not any(_owned_by(rel, in_head) for rel in plan.manifest):
        why = f" ({len(plan.skipped)} files were excluded: credentials, limits or symlinks)" if plan.skipped else ""
        raise HubWorkspaceError(
            f"none of the worker's owned paths that exist in HEAD produced a file to upload: "
            f"{', '.join(in_head)}{why}. Nothing was uploaded: an empty copy would look like missing "
            f"files to the hub worker. Check owned_dirs (set_worker_owned_dirs) and that these paths "
            f"are checked out and not deleted in the worktree.")
    return plan


def _clean_rel(rel: str) -> str:
    rel = rel.strip().replace("\\", "/")
    if not rel or rel.startswith("/") or ".." in rel.split("/") or "\0" in rel:
        raise HubWorkspaceError(f"path {rel!r} is not a path inside the worktree")
    return rel.removeprefix("./")


def _file_has_secret(path: Path, known: list[str]) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    if b"\0" in data[:4096]:
        return any(v.encode() in data for v in known)
    return secret_in_text(data.decode("utf-8", "ignore"), known) is not None


def write_tar(root: Path, rels: list[str], out: Path) -> None:
    with tarfile.open(out, "w") as archive:
        for rel in rels:
            full = root / rel
            info = archive.gettarinfo(str(full), arcname=rel)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with full.open("rb") as handle:
                archive.addfile(info, handle)


# ── transport (SSH) ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HubSsh:
    target: str                  # user@host
    key: str
    workspace_root: str          # absolute remote dir, e.g. /home/<u>/orchestra-ws

    @classmethod
    def from_env(cls) -> "HubSsh | None":
        target = os.environ.get("MULTICODE_HUB_SSH", "").strip()
        key = os.environ.get("MULTICODE_HUB_SSH_KEY", "").strip()
        if not target or not key:
            return None
        return cls(target, key, os.environ.get("MULTICODE_HUB_WORKSPACE_ROOT", "").strip())

    def _argv(self, remote: str) -> list[str]:
        sock = f"/tmp/orchestra-hub-{os.getuid()}-%C"
        return [
            "ssh", "-i", self.key, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=20",
            "-o", "ControlMaster=auto", "-o", f"ControlPath={sock}", "-o", "ControlPersist=120",
            self.target, remote,
        ]

    async def run(self, remote: str, *, stdin: Path | None = None, stdout: Path | None = None,
                  timeout: float = 600, max_out: int = MAX_TOTAL_BYTES * 2) -> bytes:
        with _Open(stdin, "rb") as fin, _Open(stdout, "wb") as fout:
            proc = await asyncio.create_subprocess_exec(
                *self._argv(remote),
                stdin=fin if fin else asyncio.subprocess.DEVNULL,
                stdout=fout if fout else asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise HubWorkspaceError("hub SSH command timed out") from None
        if proc.returncode != 0:
            raise HubWorkspaceError(_ssh_failure(remote, proc.returncode, out, err, stdout is not None))
        if stdout is not None and stdout.stat().st_size > max_out:
            raise HubWorkspaceError("hub workspace download exceeds the size limit")
        return out or b""

    async def home(self) -> str:
        return (await self.run('printf %s "$HOME"', timeout=60)).decode().strip()

    async def ensure_uv(self, scratch: Path) -> None:
        """Verify on every turn; upload once, or repair corruption, with an atomic rename.

        Only our home-directory tool area is touched. Parallel workers have unique temporary
        files and publish only a complete, checksum- and version-verified executable.
        """
        snapshot = scratch / "uv-upload"
        try:
            payload, digest, version = await asyncio.to_thread(_uv_snapshot, scratch)
            binary = f'"$HOME/{HUB_UV_BIN}/uv"'
            check = (
                f'test -x {binary} && '
                f'test "$(sha256sum {binary} | cut -d " " -f 1)" = {shlex.quote(digest)} && '
                f'test "$({binary} --version)" = {shlex.quote(version)}'
            )
            probe = (
                'test "$(uname -sm)" = "Linux x86_64" || '
                '{ echo "hub uv requires Linux x86_64" >&2; exit 1; }; '
                f'if {check}; then printf ready; else printf install; fi'
            )
            status = await self.run(probe, timeout=60)
            if status == b"ready":
                return
            if status != b"install":
                raise HubWorkspaceError("unexpected hub uv verification response")
            install = (
                f'set -eu; umask 077; mkdir -p -- "$HOME/{HUB_UV_BIN}"; '
                f'tmp=$(mktemp "$HOME/{HUB_UV_BIN}/.uv.XXXXXXXX"); '
                "trap 'rm -f -- \"$tmp\"' EXIT; "
                'cat > "$tmp"; '
                f'test "$(sha256sum "$tmp" | cut -d " " -f 1)" = {shlex.quote(digest)} || '
                '{ echo "hub uv upload checksum mismatch" >&2; exit 1; }; '
                'chmod 700 "$tmp"; '
                f'test "$("$tmp" --version)" = {shlex.quote(version)} || '
                '{ echo "hub uv upload version mismatch" >&2; exit 1; }; '
                f'mv -f -- "$tmp" {binary}'
            )
            await self.run(install, stdin=payload, timeout=180)
        finally:
            snapshot.unlink(missing_ok=True)

    async def root(self) -> str:
        if self.workspace_root:
            root = self.workspace_root
        else:
            root = f"{await self.home()}/orchestra-ws/{_install_tag()}"
        if not _SAFE_REMOTE.match(root) or ".." in root.split("/") or root.count("/") < 3:
            raise HubWorkspaceError("hub workspace root must be an absolute path of our own area")
        return root

    async def dir_for(self, ws_id: str) -> str:
        if not _WS_ID.match(ws_id):
            raise HubWorkspaceError("invalid workspace id")
        return f"{await self.root()}/{ws_id}"

    async def put(self, remote_dir: str, tar_path: Path) -> None:
        """Unpack a tar into the workspace, creating it when this is the first upload (or an
        earlier upload died before the directory existed)."""
        _check_remote(remote_dir)
        q = shlex.quote(remote_dir)
        await self.run(f"mkdir -p -- {q} && tar -xf - -C {q}", stdin=tar_path)

    async def delete_files(self, remote_dir: str, rels: list[str]) -> None:
        _check_remote(remote_dir)
        if not rels:
            return
        listing = Path(tempfile.mkstemp(prefix="hub-del-")[1])
        try:
            listing.write_bytes(b"".join(r.encode() + b"\0" for r in rels))
            await self.run(f"cd {shlex.quote(remote_dir)} && xargs -0 rm -f --", stdin=listing)
        finally:
            listing.unlink(missing_ok=True)

    async def get(self, remote_dir: str, out: Path) -> None:
        _check_remote(remote_dir)
        await self.run(
            f"tar -cf - -C {shlex.quote(remote_dir)} --exclude=./.git --exclude=./.venv .", stdout=out)

    async def list_workspaces(self) -> list[tuple[str, float]]:
        """(workspace id, mtime epoch) of every broker directory under our root."""
        root = await self.root()
        out = await self.run(
            f"test -d {shlex.quote(root)} && find {shlex.quote(root)} -maxdepth 1 -mindepth 1 "
            f"-type d -name 'hub-*' -printf '%f %T@\\n'; true", timeout=120)
        found = []
        for line in out.decode().splitlines():
            name, _, mtime = line.partition(" ")
            if _WS_ID.match(name):
                found.append((name, float(mtime or 0)))
        return found

    async def scrub_traces(self, ws_id: str, thread_id: str) -> None:
        """Delete what the hub's providers wrote about this workspace outside the T3 store:
        Claude/Codex/Grok session transcripts and the per-thread provider log. Every match is
        keyed by the unique workspace id (or our thread id), so nothing else can be hit. The
        per-thread provider log directory is deployment-specific: MULTICODE_HUB_PROVIDER_LOG_DIR."""
        if not _WS_ID.match(ws_id) or (thread_id and not _THREAD_ID.match(thread_id)):
            raise HubWorkspaceError("invalid workspace or thread id")
        script = Path(tempfile.mkstemp(prefix="hub-scrub-")[1])
        try:
            script.write_text(_SCRUB_SCRIPT)
            logdir = os.environ.get("MULTICODE_HUB_PROVIDER_LOG_DIR", "").strip() or "-"
            if logdir != "-" and not _SAFE_REMOTE.match(logdir):
                raise HubWorkspaceError("MULTICODE_HUB_PROVIDER_LOG_DIR must be an absolute path")
            await self.run(f"bash -s -- {shlex.quote(ws_id)} {shlex.quote(thread_id or '-')} "
                           f"{shlex.quote(logdir)}", stdin=script, timeout=300)
        finally:
            script.unlink(missing_ok=True)

    async def base_dir_for(self, scope: str) -> str:
        return f"{await self.root()}/{base_id_for(scope)}"

    async def copy_dir(self, source: str, dest: str) -> None:
        """Copy a persistent base into a fresh worker workspace, entirely on the hub."""
        _check_remote(source)
        _check_remote(dest, base_ok=False)
        await self.run(f"mkdir -p -- {shlex.quote(dest)} && "
                       f"cp -a --reflink=auto -- {shlex.quote(source)}/. {shlex.quote(dest)}/", timeout=1800)

    async def remove(self, remote_dir: str) -> None:
        _check_remote(remote_dir, base_ok=False)
        root = await self.root()
        if os.path.dirname(remote_dir) != root:
            raise HubWorkspaceError("refusing to remove a path outside the workspace root")
        await self.run(f"rm -rf -- {shlex.quote(remote_dir)}", timeout=300)


def _ssh_failure(remote: str, rc: int, out: bytes | None, err: bytes | None, streamed: bool) -> str:
    """An SSH failure message that always says what was run and what came back."""
    said = (err or b"").decode("utf-8", "replace").strip()
    if not said and not streamed:
        said = (out or b"").decode("utf-8", "replace").strip()
    said = said[-300:] or "no output (the remote command failed silently)"
    words = remote.split()
    kind = " ".join(words[:2]) if words else "?"
    return f"hub SSH command failed rc={rc}: {said} [remote command: {kind[:60]}]"


def _check_remote(remote_dir: str, *, base_ok: bool = True) -> None:
    if not _SAFE_REMOTE.match(remote_dir) or ".." in remote_dir.split("/"):
        raise HubWorkspaceError("unsafe remote path")
    name = os.path.basename(remote_dir)
    if not (_WS_ID.match(name) or (base_ok and _BASE_ID.match(name))):
        raise HubWorkspaceError("remote path is not a broker workspace")


class _Open:
    """`open` that tolerates a None path (no redirect)."""

    def __init__(self, path: Path | None, mode: str):
        self._path, self._mode, self._fh = path, mode, None

    def __enter__(self):
        if self._path is not None:
            self._fh = self._path.open(self._mode)
        return self._fh

    def __exit__(self, *_):
        if self._fh:
            self._fh.close()


# ── sync back ────────────────────────────────────────────────────────────────────────


@dataclass
class SyncResult:
    changed: list[str] = field(default_factory=list)      # added or modified
    deleted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)    # both sides changed: hub copy NOT applied
    rejected: list[tuple[str, str]] = field(default_factory=list)
    manifest: dict[str, str] = field(default_factory=dict)  # updated manifest after the sync
    outbox: bytes = b""     # the worker's outbox file (never imported as a file; the broker executes it)


def _member_path(name: str) -> str | None:
    rel = name[2:] if name.startswith("./") else name
    if not rel or rel == "." or rel.startswith("/") or "\0" in rel:
        return None
    if ".." in rel.split("/"):
        return None
    return rel


def apply_changes(tar_path: Path, root: Path, manifest: dict[str, str],
                  known: list[str] | None = None) -> SyncResult:
    """Import a hub workspace snapshot into the worktree, touching only regular files that
    changed relative to `manifest`, never leaving `root`, never importing credentials."""
    root = root.resolve()
    known = known_secret_values() if known is None else known
    result = SyncResult(manifest=dict(manifest))
    seen: set[str] = set()
    total = 0
    pending: list[tuple[str, bytes, int]] = []
    with tarfile.open(tar_path, "r:") as archive:
        # Inspect names first: pyvenv.cfg can follow its siblings in a tar snapshot.
        # Match directory boundaries, independent of the environment's chosen name.
        venvs = {str(Path(rel).parent) for member in archive.getmembers()
                 if (rel := _member_path(member.name)) is not None
                 and Path(rel).name == "pyvenv.cfg"}

        def in_virtualenv(rel: str) -> bool:
            path = Path(rel)
            return str(path) in venvs or any(str(parent) in venvs for parent in path.parents)

        for directory in sorted(venvs):
            result.rejected.append((directory, "Python virtualenv (contains pyvenv.cfg)"))
        seen.update(rel for rel in manifest if in_virtualenv(rel))
        for member in archive:
            if member.isdir():
                continue
            rel = _member_path(member.name)
            if rel is None:
                result.rejected.append((member.name, "path escapes the workspace"))
                continue
            if in_virtualenv(rel):
                seen.add(rel)  # preserve previously synced files; exclusion is not a deletion
                continue
            if not member.isreg():
                result.rejected.append((rel, "not a regular file (link or special)"))
                continue
            if rel == OUTBOX_NAME:
                handle = archive.extractfile(member)
                result.outbox = handle.read(MAX_OUTBOX_BYTES + 1) if handle else b""
                continue
            reason = blocked_reason(rel)
            if reason:
                if not reason.startswith("directory"):   # caches the hub run left behind are noise
                    result.rejected.append((rel, reason))
                continue
            seen.add(rel)
            if member.size > MAX_FILE_BYTES or total + member.size > MAX_TOTAL_BYTES:
                result.rejected.append((rel, "exceeds the size limit"))
                continue
            handle = archive.extractfile(member)
            data = handle.read() if handle else b""
            digest = hashlib.sha256(data).hexdigest()
            if manifest.get(rel) == digest:
                continue
            total += member.size
            if b"\0" not in data[:4096] and secret_in_text(data.decode("utf-8", "ignore"), known):
                result.rejected.append((rel, "contains a credential"))
                continue
            pending.append((rel, data, member.mode))
    for rel, data, mode in pending:
        target = root / rel
        if not _contained(root, target):
            result.rejected.append((rel, "resolves outside the worktree"))
            continue
        local = sha256_file(target) if target.is_file() and not target.is_symlink() else None
        new = hashlib.sha256(data).hexdigest()
        if target.is_symlink() or (target.exists() and not target.is_file()):
            result.rejected.append((rel, "worktree path is not a regular file"))
            continue
        if local is not None and local != new and local != manifest.get(rel):
            result.conflicts.append(rel)
            continue
        if local == new:
            result.manifest[rel] = new
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if not _contained(root, target):
            result.rejected.append((rel, "resolves outside the worktree"))
            continue
        tmp = target.with_name(f".{target.name}.hub-{uuid.uuid4().hex[:8]}")
        tmp.write_bytes(data)
        os.chmod(tmp, 0o755 if mode & 0o111 else 0o644)
        os.replace(tmp, target)
        result.changed.append(rel)
        result.manifest[rel] = new
    gone = [rel for rel in manifest if rel not in seen]
    if gone and len(gone) > 20 and len(gone) * 2 > len(manifest):
        result.rejected.append(("*", f"{len(gone)} deletions look like a truncated snapshot; ignored"))
        gone = []
    for rel in gone:
        target = root / rel
        if not _contained(root, target) or target.is_symlink():
            continue
        if not target.exists():
            result.manifest.pop(rel, None)
            continue
        if target.is_file() and sha256_file(target) == manifest[rel]:
            target.unlink()
            result.deleted.append(rel)
            result.manifest.pop(rel, None)
            _prune_empty(root, target.parent)
        else:
            result.conflicts.append(rel)
    return result


def _contained(root: Path, target: Path) -> bool:
    try:
        real = Path(os.path.realpath(target.parent)) / target.name
        real.relative_to(root)
    except (ValueError, OSError):
        return False
    return True


def _prune_empty(root: Path, directory: Path) -> None:
    while directory != root and root in directory.parents:
        try:
            directory.rmdir()
        except OSError:
            return
        directory = directory.parent


def local_delta(root: Path, plan: UploadPlan, manifest: dict[str, str], keep: frozenset[str] | set[str] = frozenset()
                ) -> tuple[list[str], list[str]]:
    """Files to (re)send and to delete on the hub so it matches the worktree again.

    `keep` are files the hub itself created and the broker imported (a task report under
    .orchestra/tasks/, say): they sit outside the upload scope, but they are not stale, so they stay
    on the hub and in the manifest. Dropping them forgot their baseline, and the next turn's
    rewrite of the same file looked like a change on both sides."""
    send = [rel for rel, digest in plan.manifest.items() if manifest.get(rel) != digest]
    drop = [rel for rel in manifest if rel not in plan.manifest and rel not in keep]
    return sorted(send), sorted(drop)


# ── persistent record (resume after restart, release by worktree) ────────────────────


@dataclass
class WorkspaceState:
    ws_id: str
    worktree: str
    remote_dir: str
    manifest: dict[str, str] = field(default_factory=dict)
    paths: list[str] = field(default_factory=list)
    project_id: str = ""
    thread_id: str = ""
    turns: int = 0
    hub_made: list[str] = field(default_factory=list)  # files the hub created or changed and the broker imported
    uploaded: bool = False  # the first upload reached the hub; until then the workspace is not established
    activity_pos: int = 0   # live-feed cursor: timeline position already shown
    created_at: float = field(default_factory=time.time)

    @staticmethod
    def new_id() -> str:
        return f"hub-{uuid.uuid4().hex[:16]}"

    def path(self) -> Path:
        return STATE_DIR / f"{self.ws_id}.json"

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, sort_keys=True))
        os.replace(tmp, self.path())

    @classmethod
    def load(cls, ws_id: str) -> "WorkspaceState | None":
        if not _WS_ID.match(ws_id or ""):
            return None
        try:
            data = json.loads((STATE_DIR / f"{ws_id}.json").read_text())
            return cls(**data)
        except (OSError, ValueError, TypeError):
            return None


@dataclass
class BaseState:
    """The warm, persistent copy of one project on the hub (never touched by release or the sweep)."""

    base_id: str
    scope: str
    manifest: dict[str, str] = field(default_factory=dict)

    def path(self) -> Path:
        return STATE_DIR / f"base-{self.base_id}.json"

    def save(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, sort_keys=True))
        os.replace(tmp, self.path())

    @classmethod
    def load(cls, scope: str) -> "BaseState":
        base_id = base_id_for(scope)
        try:
            return cls(**json.loads((STATE_DIR / f"base-{base_id}.json").read_text()))
        except (OSError, ValueError, TypeError):
            return cls(base_id=base_id, scope=os.path.realpath(scope))


_BASE_LOCKS: dict[str, asyncio.Lock] = {}


async def provision_from_base(ssh: HubSsh, root: Path, scope: str, plan: UploadPlan,
                              dest_dir: str) -> tuple[int, int]:
    """Make the project's warm copy on the hub match `plan` by sending only what changed, then
    copy it into the worker's own directory on the hub. Returns (files sent, files dropped).

    The base is updated and copied under one lock, so two workers of a project never see it half
    changed; each worker then edits its own copy and the base itself is never edited."""
    lock = _BASE_LOCKS.setdefault(base_id_for(scope), asyncio.Lock())
    async with lock:
        base = BaseState.load(scope)
        base_dir = await ssh.base_dir_for(scope)
        send, drop = local_delta(root, plan, base.manifest)
        scratch = local_scratch()
        try:
            if send:
                tar_path = scratch / "base.tar"
                await asyncio.to_thread(write_tar, root, send, tar_path)
                await ssh.put(base_dir, tar_path)
            else:
                await ssh.run(f"mkdir -p -- {shlex.quote(base_dir)}")
            await ssh.delete_files(base_dir, drop)
            base.manifest = dict(plan.manifest)
            base.save()
            await ssh.copy_dir(base_dir, dest_dir)
        finally:
            rmtree_quiet(scratch)
    return len(send), len(drop)


async def drop_base(scope: str, ssh: HubSsh | None = None) -> None:
    """Turn the persistent copy of a project off for good: delete it on the hub and locally."""
    ssh = ssh or HubSsh.from_env()
    base_dir = await ssh.base_dir_for(scope)
    await ssh.run(f"rm -rf -- {shlex.quote(base_dir)}", timeout=600)
    BaseState.load(scope).path().unlink(missing_ok=True)


def states_for_worktree(worktree: str) -> list[WorkspaceState]:
    found: list[WorkspaceState] = []
    if not STATE_DIR.is_dir():
        return found
    real = os.path.realpath(worktree)
    for path in STATE_DIR.glob("hub-*.json"):
        state = WorkspaceState.load(path.stem)
        if state and os.path.realpath(state.worktree) == real:
            found.append(state)
    return found


# ── git commit of imported work ──────────────────────────────────────────────────────


def commit_sync(root: Path, changed: list[str], deleted: list[str], message: str
                ) -> tuple[str, list[tuple[str, str]]]:
    """Commit the imported paths on the worker's own branch; returns (short SHA or '', paths that
    could not be staged with the reason). One unstageable path never costs the rest of the turn.

    `--sparse` lets git stage files the hub created outside the worker's sparse-checkout cone
    (a plain `git add` refuses them and used to abort the whole commit). The author comes from
    git config — never overridden."""
    paths = sorted(set(changed) | set(deleted))
    if not paths:
        return "", []
    base = ["git", "-C", str(root)]

    def add(batch: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(base + ["add", "-A", "--sparse", "--", *batch],
                              capture_output=True, text=True, timeout=120)

    staged, failed = paths, []
    if add(paths).returncode != 0:
        staged = []
        for path in paths:
            done = add([path])
            if done.returncode == 0:
                staged.append(path)
            else:
                failed.append((path, (done.stderr or done.stdout).strip().splitlines()[-1][:200]
                               if (done.stderr or done.stdout).strip() else "git add refused it"))
    if not staged:
        return "", failed
    done = subprocess.run(base + ["commit", "-m", message, "--only", "--", *staged],
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise HubWorkspaceError(f"git commit failed: {(done.stderr or done.stdout).strip()[-300:]}")
    sha = subprocess.run(base + ["rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, timeout=30).stdout.strip()
    return sha, failed


# ── lifecycle ────────────────────────────────────────────────────────────────────────


def _gone(exc: Exception) -> bool:
    return "not_found" in str(exc) or "not found" in str(exc).lower()


async def _project_listed(mcp, project_id: str) -> bool:
    cursor = None
    while True:
        args = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        page = await mcp.tool_call("t3_project_list", args)
        if any(p.get("id") == project_id for p in page.get("projects", [])):
            return True
        cursor = page.get("nextCursor")
        if cursor is None:
            return False


async def verify_released(state: WorkspaceState, mcp, ssh: HubSsh | None, *, wait: float = 20) -> list[str]:
    """Problems left on the hub for this workspace: [] means nothing is visible any more."""
    problems: list[str] = []
    deadline = time.monotonic() + wait
    while True:
        problems = []
        if state.project_id and await _project_listed(mcp, state.project_id):
            problems.append("project still listed")
        if state.thread_id:
            try:
                await mcp.tool_call("t3_thread_read", {"threadId": state.thread_id, "view": "messages", "limit": 1})
                problems.append("thread still readable")
            except Exception as exc:   # noqa: BLE001 - only "not found" counts as gone
                if not _gone(exc):
                    problems.append(f"thread check failed: {exc}")
        if not problems or time.monotonic() > deadline:
            break
        await asyncio.sleep(2)
    if ssh is not None:
        names = {name for name, _ in await ssh.list_workspaces()}
        if state.ws_id in names:
            problems.append("workspace directory still present")
    return problems


async def release_workspace(state: WorkspaceState, ssh: HubSsh | None = None, mcp=None) -> None:
    """Remove everything the task left on the hub, then prove it is gone.

    T3 `project.delete(force)` deletes every live and archived thread of the project; the hub then
    purges their messages, turn items and attachments (only an id/title tombstone stays in its
    own event store). What T3 does not own — the workspace directory and the providers' own
    transcripts — is removed here. The local record is deleted only after the check passes."""
    ssh = ssh or HubSsh.from_env()
    errors: list[str] = []
    if mcp is not None:
        if state.thread_id:
            try:
                await mcp.tool_call("t3_thread_interrupt", {"threadId": state.thread_id})
            except Exception:   # noqa: BLE001 - an idle or already gone thread is fine
                pass
        if state.project_id:
            try:
                await mcp.tool_call("t3_project_delete", {"projectId": state.project_id, "force": True})
            except Exception as exc:   # noqa: BLE001
                if not _gone(exc):
                    errors.append(f"project: {exc}")
    else:
        errors.append("MultiCode client unavailable: project and threads not deleted")
    if ssh is not None:
        for what, action in (("directory", lambda: ssh.remove(state.remote_dir)),
                             ("traces", lambda: ssh.scrub_traces(state.ws_id, state.thread_id))):
            try:
                await action()
            except HubWorkspaceError as exc:
                errors.append(f"{what}: {exc}")
    if not errors and mcp is not None:
        errors += [f"verify: {p}" for p in await verify_released(state, mcp, ssh)]
    if errors:
        raise HubWorkspaceError("hub cleanup incomplete: " + "; ".join(errors))
    state.path().unlink(missing_ok=True)


def local_scratch() -> Path:
    return Path(tempfile.mkdtemp(prefix="hub-sync-"))


def rmtree_quiet(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
