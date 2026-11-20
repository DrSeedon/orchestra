"""Read-only execution and revisioned request receipts."""

from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from uuid import uuid4

from .abi import AccessRevoked, Rejected, RetryableRead, canonical, check_value, fields

LEASE_SECONDS = 180
TTL_SECONDS = 1800


@dataclass(frozen=True)
class Access:
    scope: str
    principal: str
    invocation_id: str
    skills: frozenset[str]
    workspace: dict
    sources: object
    origin: str = "orchestra"
    grant_revision: str = ""


def _schemas(manifest, step, catalog, port_group):
    return {port: catalog.types[manifest["bindings"][binding]["type"]]
            for port, binding in step[port_group].items()}


def _bind_inputs(manifest, catalog, state, names, values):
    fields(values, names)
    for name, value in values.items():
        check_value(catalog.types[manifest["bindings"][name]["type"]], value)
    state["values"].update(values)


def _bind_outputs(manifest, catalog, state, step, outputs):
    fields(outputs, step["out"])
    schemas = _schemas(manifest, step, catalog, "out")
    for port, value in outputs.items():
        check_value(schemas[port], value)
    for port, binding in step["out"].items():
        state["values"][binding] = outputs[port]


def _inputs(step, values):
    return {port: values[binding] for port, binding in step["in"].items()}


def _execute(op, inputs, sources):
    try:
        return op.execute(inputs, sources)
    except RetryableRead:
        return op.execute(inputs, sources)


def advance(manifest, catalog, state, sources, supplied):
    """Advance through deterministic work until interaction or verification."""
    steps = manifest["steps"]
    pending = state["pending"]
    if pending:
        status, keys = pending
        if status == "needs_bindings":
            _bind_inputs(manifest, catalog, state, keys, supplied)
        else:
            fields(supplied, keys)
            for sid in keys:
                step = steps[state["position"]]
                _bind_outputs(manifest, catalog, state, step, supplied[sid])
                state["position"] += 1
        state["pending"] = None
    else:
        fields(supplied, ())
    missing = [key for key, spec in manifest["bindings"].items()
               if spec["from"] == "request" and key not in state["values"]]
    if missing:
        state["pending"] = ["needs_bindings", missing]
        return {"status": "needs_bindings", "bindings": {
            key: catalog.types[manifest["bindings"][key]["type"]] for key in missing
        }}

    values = state["values"]
    while state["position"] < len(steps):
        index = state["position"]
        step = steps[index]
        if step["kind"] == "llm_step":
            group = []
            produced = set()
            for item in steps[index:]:
                if item["kind"] != "llm_step":
                    break
                group.append({
                    "id": item["id"], "instruction": item["instruction"],
                    "in": {port: {"binding": binding} if binding in produced
                           else {"value": values[binding]} for port, binding in item["in"].items()},
                    "out": _schemas(manifest, item, catalog, "out"),
                    "bindings": item["out"],
                })
                produced.update(item["out"].values())
            state["pending"] = ["your_steps", [item["id"] for item in group]]
            return {"status": "your_steps", "steps": group}

        op = catalog.operations[step["op"]]
        try:
            outputs = _execute(op, _inputs(step, values), sources)
            _bind_outputs(manifest, catalog, state, step, outputs)
        except AccessRevoked:
            return {"status": "revoked"}
        except Exception:
            if not step["out"]:
                return {"status": "program_failed", "terminal": True, "step": step["id"]}
            state["pending"] = ["program_failed", [step["id"]]]
            return {
                "status": "program_failed", "step": step["id"], "operation": step["op"],
                "diagnostic": "Read operation failed. Recover this step in the original skill.",
                "out": _schemas(manifest, step, catalog, "out"),
            }
        state["position"] += 1

    for step in manifest["verification"]:
        op = catalog.operations[step["op"]]
        try:
            fields(_execute(op, _inputs(step, values), sources), ())
        except AccessRevoked:
            return {"status": "revoked"}
        except Exception:
            return {"status": "verification_failed", "step": step["id"]}
    return {"status": "complete", "result": {name: values[name] for name in manifest["return"]}}


def initial_state(manifest, catalog, bindings, workspace):
    state = {"position": 0, "pending": None, "values": {}}
    requested = {name for name, spec in manifest["bindings"].items() if spec["from"] == "request"}
    if not isinstance(bindings, dict) or not set(bindings) <= requested:
        raise Rejected("caller can only set request bindings")
    _bind_inputs(manifest, catalog, state, bindings.keys(), bindings)
    required = {name for name, spec in manifest["bindings"].items()
                if spec["from"] == "authorized_workspace"}
    if not required <= workspace.keys():
        raise AccessRevoked
    _bind_inputs(manifest, catalog, state, required, {key: workspace[key] for key in required})
    return state


class Runner:
    def __init__(self, registry, private, key, authorize):
        if len(key) < 32:
            raise ValueError("receipt key must be at least 32 bytes")
        self.registry = registry
        self.private = private
        self.key = key
        self.authorize = authorize

    def handle(self, request):
        try:
            return self._handle(request)
        except AccessRevoked:
            return {"status": "revoked"}
        except (Rejected, ValueError, TypeError, RecursionError):
            return {"status": "invalid_request"}

    def _handle(self, request):
        if not isinstance(request, dict):
            raise Rejected("expected an object")
        action = request.get("action")
        if action == "run":
            fields(request, ("action", "skill", "intent", "request_id", "bindings"))
            if not all(isinstance(request[k], str) and 0 < len(request[k]) <= 64
                       for k in ("skill", "intent")):
                raise Rejected("invalid skill or intent")
        elif action == "continue":
            fields(request, ("action", "run_id", "request_id", "revision", "bindings"))
            if (type(request["revision"]) is not int or request["revision"] < 0
                    or not isinstance(request["run_id"], str) or len(request["run_id"]) != 32):
                raise Rejected("invalid run id or revision")
        else:
            raise Rejected("unknown action")
        request_id = request["request_id"]
        if not isinstance(request_id, str) or not 0 < len(request_id) <= 128:
            raise Rejected("invalid request id")
        data = canonical(request).encode()
        if len(data) > 524288:
            raise Rejected("request exceeds size limit")
        access = self.authorize()
        if not access:
            raise AccessRevoked
        mac = hmac.new(self.key, b"input:" + data, hashlib.sha256).hexdigest()
        request_id = hmac.new(self.key, b"id:" + request_id.encode(), hashlib.sha256).hexdigest()
        now = int(time.time())
        lease = uuid4().hex

        with self.registry.write() as conn:
            if action == "run":
                run = conn.execute(
                    "SELECT * FROM sc_run WHERE scope=? AND principal=? AND request_key=?",
                    (access.scope, access.principal, request_id),
                ).fetchone()
                if run is None:
                    run = self._new_run(conn, access, request, request_id, mac, now)
                    if run is None:
                        return {"status": "unavailable"}
            else:
                run = conn.execute("SELECT * FROM sc_run WHERE id=?", (request["run_id"],)).fetchone()
            if (run is None or run["scope"] != access.scope or run["principal"] != access.principal
                    or run["invocation_id"] != access.invocation_id):
                raise AccessRevoked
            capsule = conn.execute("SELECT * FROM sc_capsule WHERE scope=? AND digest=?",
                                   (run["scope"], run["digest"])).fetchone()
            status = self._admission(conn, capsule, run, access, now)
            if status:
                return {"status": status}
            artifact = self.private.get(run["private_state_ref"])
            if artifact["grant_revision"] != access.grant_revision or artifact["workspace"] != access.workspace:
                return {"status": "revoked"}
            receipt = conn.execute("SELECT * FROM sc_receipt WHERE run_id=? AND request_id=?",
                                   (run["id"], request_id)).fetchone()
            if receipt:
                if not hmac.compare_digest(receipt["input_mac"], mac):
                    return {"status": "conflict"}
                return self.private.get(receipt["report_ref"])
            if action == "run":
                if not hmac.compare_digest(artifact["initial_mac"], mac):
                    return {"status": "conflict"}
            elif run["revision"] != request["revision"] or run["state"] not in {
                "needs_bindings", "your_steps", "program_failed",
            }:
                return {"status": "conflict"}
            if run["lease_until"] and run["lease_until"] > now:
                return {"status": "busy", "run_id": run["id"], "revision": run["revision"]}
            conn.execute("UPDATE sc_run SET lease_token=?, lease_until=? WHERE id=?",
                         (lease, now + LEASE_SECONDS, run["id"]))

        try:
            manifest = json.loads(capsule["manifest_json"])
            state = artifact["state"]
            if hasattr(access.sources, "records"):
                access.sources.records.update(tuple(record) for record in artifact.get("evidence", []))
            report = advance(manifest, self.registry.catalog, state, access.sources,
                             request["bindings"] if action == "continue" else {})
            return self._finish(run, capsule, access, lease, state, report, request_id, mac)
        finally:
            with self.registry.write() as conn:
                conn.execute(
                    "UPDATE sc_run SET lease_token=NULL, lease_until=NULL WHERE id=? AND lease_token=?",
                    (run["id"], lease),
                )

    def _admission(self, conn, capsule, run, access, now):
        if run["expires_at"] <= now:
            return "expired"
        if capsule["skill"] not in access.skills:
            return "revoked"
        status = self.registry.current(conn, capsule)
        return status if status != "active" else None

    def _new_run(self, conn, access, request, request_key, mac, now):
        skill = request["skill"]
        if skill not in access.skills:
            raise AccessRevoked
        capsule = conn.execute(
            "SELECT * FROM sc_capsule WHERE scope=? AND skill=? AND intent=? AND status='active'",
            (access.scope, skill, request["intent"]),
        ).fetchone()
        if capsule is None or self.registry.current(conn, capsule) != "active":
            return None
        manifest = json.loads(capsule["manifest_json"])
        state = initial_state(manifest, self.registry.catalog, request["bindings"],
                              access.workspace.get(skill, {}))
        expiry = now + TTL_SECONDS
        self.private.purge_expired(now)
        ref = self.private.put({"state": state, "initial_mac": mac, "workspace": access.workspace,
                                "grant_revision": access.grant_revision}, expiry)
        conn.execute(
            """INSERT OR IGNORE INTO sc_invocation(id,scope,origin,session_ref,skill)
               VALUES (?,?,?,?,?)""",
            (access.invocation_id, access.scope, access.origin, access.principal, skill),
        )
        invocation = conn.execute("SELECT * FROM sc_invocation WHERE id=?", (access.invocation_id,)).fetchone()
        if (invocation["scope"], invocation["origin"], invocation["session_ref"]) != (
            access.scope, access.origin, access.principal,
        ):
            raise AccessRevoked
        run_id = uuid4().hex
        conn.execute(
            """INSERT INTO sc_run(id,scope,digest,principal,invocation_id,request_key,state,
                                  private_state_ref,expires_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (run_id, access.scope, capsule["digest"], access.principal, access.invocation_id,
             request_key, "starting", ref, expiry),
        )
        return conn.execute("SELECT * FROM sc_run WHERE id=?", (run_id,)).fetchone()

    def _finish(self, run, capsule, access, lease, state, report, request_id, mac):
        now = int(time.time())
        revision = run["revision"] + 1
        report.update(run_id=run["id"], revision=revision)
        with self.registry.write() as conn:
            fresh_access = self.authorize()
            if (not fresh_access or fresh_access.invocation_id != access.invocation_id
                    or fresh_access.principal != access.principal or fresh_access.scope != access.scope
                    or fresh_access.workspace != access.workspace
                    or fresh_access.grant_revision != access.grant_revision):
                return {"status": "revoked"}
            current = conn.execute("SELECT * FROM sc_capsule WHERE scope=? AND digest=?",
                                   (capsule["scope"], capsule["digest"])).fetchone()
            status = self._admission(conn, current, run, fresh_access, now)
            if status:
                return {"status": status}
            owned = conn.execute(
                "SELECT 1 FROM sc_run WHERE id=? AND revision=? AND lease_token=? AND lease_until>?",
                (run["id"], run["revision"], lease, now),
            ).fetchone()
            if not owned:
                return {"status": "conflict"}
            report_ref = self.private.put(report, run["expires_at"])
            state_ref = self.private.put(
                {"state": state, "initial_mac": mac, "workspace": access.workspace,
                 "grant_revision": access.grant_revision,
                 "evidence": sorted(getattr(access.sources, "records", ()))},
                run["expires_at"],
            )
            conn.execute(
                """UPDATE sc_run SET revision=?, position=?, state=?, private_state_ref=?,
                   lease_token=NULL, lease_until=NULL WHERE id=?""",
                (revision, state["position"], "failed" if report.get("terminal") else report["status"],
                 state_ref, run["id"]),
            )
            conn.execute("INSERT INTO sc_receipt VALUES (?,?,?,?,?)",
                         (run["id"], request_id, mac, report_ref, revision))
        return report

