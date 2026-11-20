"""Opt-in host provisioning and the single execution service."""

import hashlib
import hmac
import json
import os
from pathlib import Path

from app import db
from .pilots import MANIFESTS, catalog
from .registry import PrivateStore, Registry, SkillSource, digest
from .runner import Access, Runner
from .sources import LiveSources


def settings():
    filename = os.environ.get("ORCHESTRA_SKILLCACHE_CONFIG")
    if not filename:
        return None
    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        from stat import S_ISREG

        status = os.fstat(stream.fileno())
        if not S_ISREG(status.st_mode) or status.st_uid != os.getuid() or status.st_mode & 0o077:
            raise PermissionError("SkillCache config must be an owner-only file")
        return json.loads(stream.read(262144))


def registry(config):
    skills = {}
    schemas = {}
    for scope, definitions in config["scopes"].items():
        for skill, definition in definitions.items():
            skills[scope, skill] = SkillSource(
                Path(definition["skill_path"]), tuple(Path(p) for p in definition.get("scripts", []))
            )
            paths = definition.get("mcp_schema_paths", [])
            if paths:
                schemas[scope, skill] = tuple(Path(path) for path in paths)
    return Registry(db._conn, catalog(skills, schemas))


def access(config, *, principal, invocation, origin, scope=None):
    if not config or not invocation:
        return None
    grant = config["grants"].get(principal)
    if not grant or (scope is not None and scope != grant["scope"]):
        return None
    scope = grant["scope"]
    allowed = frozenset(config["scopes"].get(scope, {})) & set(grant["skills"]) & MANIFESTS.keys()
    if not allowed:
        return None
    return Access(scope, principal, invocation, allowed, grant.get("bindings", {}),
                  LiveSources(grant.get("sources", {}), os.environ), origin, digest(grant))


def execute(request, authorize):
    config = settings()
    secret = os.environ.get("ORCHESTRA_SKILLCACHE_RECEIPT_KEY", "")
    if not config or len(secret) < 32:
        return {"status": "unavailable"}
    key = hmac.digest(secret.encode(), b"skillcache-receipts", hashlib.sha256)
    private = PrivateStore(config["private_dir"])
    return Runner(registry(config), private, key, authorize).handle(request)

