"""The manifest language has no expressions, commands, paths, or literal inputs."""

from dataclasses import dataclass
import json
import re
from typing import Callable

from jsonschema import Draft202012Validator, ValidationError

from app.secret_mask import mask_secrets


NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
OP_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}@[1-9][0-9]*")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
# Fixed pilot instructions may describe work. Their values must come from ports.
UNSAFE_PROSE = re.compile(r'://|[/\\`@"\x00-\x1f]|\d|[<>]')


class Rejected(ValueError):
    pass


class AccessRevoked(Exception):
    pass


class RetryableRead(Exception):
    pass


@dataclass(frozen=True)
class Operation:
    inputs: dict[str, str]
    outputs: dict[str, str]
    execute: Callable
    verify: bool = False
    version: str = "1"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def object_schema(properties):
    return {
        "type": "object", "properties": properties, "required": sorted(properties),
        "additionalProperties": False,
    }


def fields(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise Rejected("unexpected or missing fields")


def check_value(schema, value):
    try:
        if len(canonical(value).encode()) > 524288:
            raise Rejected("value exceeds size limit")
        Draft202012Validator(schema).validate(value)
    except (ValidationError, TypeError, ValueError, RecursionError) as exc:
        raise Rejected("value does not match port schema") from exc


def check_manifest(manifest, catalog):
    encoded = canonical(manifest)
    if len(encoded.encode()) > 65536 or mask_secrets(encoded) != encoded or EMAIL.search(encoded):
        raise Rejected("manifest failed publication scan")
    fields(manifest, ("version", "skill", "intent", "description", "effect",
                      "bindings", "steps", "verification", "return"))
    if type(manifest["version"]) is not int or manifest["version"] != 1 or manifest["effect"] != "read":
        raise Rejected("unsupported capsule ABI or effect")
    for value in (manifest["skill"], manifest["intent"]):
        if not isinstance(value, str) or not NAME.fullmatch(value):
            raise Rejected("invalid skill or intent")
    _prose(manifest["description"])
    bindings = manifest["bindings"]
    if not isinstance(bindings, dict) or not 1 <= len(bindings) <= 64:
        raise Rejected("invalid bindings")
    available = set()
    for name, spec in bindings.items():
        fields(spec, ("type", "from"))
        if not NAME.fullmatch(name) or not isinstance(spec["type"], str) or spec["type"] not in catalog.types:
            raise Rejected("unknown binding type")
        if not isinstance(spec["from"], str) or not NAME.fullmatch(spec["from"]):
            raise Rejected("invalid binding source")
        if spec["from"] in ("request", "authorized_workspace"):
            available.add(name)
    ids = set()
    steps = manifest["steps"]
    verification = manifest["verification"]
    if not all(isinstance(group, list) and 1 <= len(group) <= 32 for group in (steps, verification)):
        raise Rejected("steps and verification are required")
    for group, verifying in ((steps, False), (verification, True)):
        for step in group:
            if not isinstance(step, dict):
                raise Rejected("invalid step")
            kind = step.get("kind")
            mode = "op" if kind == "program" else "instruction"
            fields(step, ("id", "kind", mode, "in", "out"))
            sid = step["id"]
            if (not isinstance(sid, str) or not NAME.fullmatch(sid) or sid in ids
                    or sid in ("request", "authorized_workspace")):
                raise Rejected("invalid or duplicate step id")
            ids.add(sid)
            for ports in (step["in"], step["out"]):
                if not isinstance(ports, dict) or any(
                    not NAME.fullmatch(port) or not isinstance(binding, str) or binding not in bindings
                    for port, binding in ports.items()
                ):
                    raise Rejected("ports must reference declared bindings")
            if kind == "program":
                op_name = step["op"]
                op = catalog.operations.get(op_name) if isinstance(op_name, str) else None
                if not op or op.verify != verifying or not OP_NAME.fullmatch(op_name):
                    raise Rejected("unknown or misplaced program operation")
                for key, spec in (("in", op.inputs), ("out", op.outputs)):
                    if {port: bindings[b]["type"] for port, b in step[key].items()} != spec:
                        raise Rejected("program ports do not match ABI")
            elif kind == "llm_step" and not verifying and step["out"]:
                _prose(step["instruction"])
            else:
                raise Rejected("invalid step kind")
            if not set(step["in"].values()) <= available:
                raise Rejected("step reads an unavailable binding")
            for binding in step["out"].values():
                if verifying or binding in available or bindings[binding]["from"] != sid:
                    raise Rejected("invalid binding producer")
                available.add(binding)
    returns = manifest["return"]
    if (available != set(bindings) or not isinstance(returns, list) or not returns
            or any(not isinstance(name, str) or name not in available for name in returns)
            or len(set(returns)) != len(returns)):
        raise Rejected("invalid return bindings")


def _prose(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 400 or UNSAFE_PROSE.search(value):
        raise Rejected("invalid instruction or description")

