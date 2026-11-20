"""Scoped registry and immutable, mode-private run artifacts."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import uuid4

from .abi import canonical, check_manifest, object_schema, Rejected


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class SkillSource:
    path: Path
    scripts: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Catalog:
    types: dict
    operations: dict
    skills: dict
    schemas: dict
    policy_version: str = "1"

    def dependencies(self, manifest, scope):
        source = self.skills[scope, manifest["skill"]]
        paths = (source.path, *source.scripts)
        schemas = self.schemas.get((scope, manifest["skill"]), {})
        if isinstance(schemas, tuple):
            schemas = {str(path): json.loads(path.read_bytes()) for path in schemas}
        ops = {}
        for step in manifest["steps"] + manifest["verification"]:
            if step["kind"] != "program":
                continue
            name = step["op"]
            op = self.operations[name]
            ops[name] = {
                "version": op.version,
                "in": object_schema({port: self.types[t] for port, t in op.inputs.items()}),
                "out": object_schema({port: self.types[t] for port, t in op.outputs.items()}),
            }
        return {
            "skill": sha256(paths[0].read_bytes()).hexdigest(),
            "scripts": {str(path): sha256(path.read_bytes()).hexdigest() for path in paths[1:]},
            "schemas": digest(schemas), "operations": digest(ops),
            "types": digest({b["type"]: self.types[b["type"]] for b in manifest["bindings"].values()}),
            "runtime": digest({
                file: sha256(Path(__file__).with_name(file).read_bytes()).hexdigest()
                for file in ("runner.py", "abi.py", "registry.py", "qualifier.py",
                             "replay.py", "fixtures.py", "pilots.py", "sources.py")
            }),
            "policy": self.policy_version,
        }


class Registry:
    def __init__(self, connect, catalog):
        self.connect = connect
        self.catalog = catalog

    @contextmanager
    def write(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def stage(self, scope, manifest):
        check_manifest(manifest, self.catalog)
        deps = self.catalog.dependencies(manifest, scope)
        version = digest([manifest, deps])
        with self.write() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sc_capsule VALUES (?, ?, ?, ?, ?, ?, 'candidate', ?)""",
                (scope, version, manifest["skill"], manifest["intent"],
                 canonical(manifest), canonical(deps), int(time.time())),
            )
        return version

    def current(self, conn, row):
        state = row["status"]
        if state != "active":
            return state
        try:
            manifest = json.loads(row["manifest_json"])
            current = self.catalog.dependencies(manifest, row["scope"])
            matches = current == json.loads(row["deps_json"])
        except (KeyError, OSError, ValueError):
            matches = False
        if matches:
            return "active"
        conn.execute("UPDATE sc_capsule SET status='stale' WHERE scope=? AND digest=?",
                     (row["scope"], row["digest"]))
        return "stale"

    def lookup(self, scope, skill, intent):
        with self.write() as conn:
            row = conn.execute(
                "SELECT * FROM sc_capsule WHERE scope=? AND skill=? AND intent=? AND status='active'",
                (scope, skill, intent),
            ).fetchone()
            if row is not None and self.current(conn, row) == "active":
                return dict(row)


class PrivateStore:
    """Opaque references are accepted only from the database, never from the caller."""

    _ref = re.compile(r"[0-9]+-[0-9a-f]{32}")

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        status = self.root.lstat()
        if not self.root.is_dir() or self.root.is_symlink() or status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise PermissionError("unsafe private artifact directory")

    def put(self, value, expires_at):
        encoded = canonical(value).encode()
        if len(encoded) > 2 * 1024 * 1024:
            raise Rejected("private run state exceeds limit")
        ref = f"{expires_at}-{uuid4().hex}"
        fd = os.open(self.root / ref, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return ref

    def get(self, ref):
        if not self._ref.fullmatch(ref) or int(ref.split("-")[0]) <= time.time():
            raise Rejected("expired artifact")
        return json.loads((self.root / ref).read_bytes())

    def purge_expired(self, now):
        for path in self.root.iterdir():
            if self._ref.fullmatch(path.name) and int(path.name.split("-")[0]) <= now:
                path.unlink(missing_ok=True)

