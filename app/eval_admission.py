"""Single-use subscription evaluation grants; no change to ordinary worker admission.

The server owns issuance, immutable manifests and a SQLite before-dispatch ledger.
An unresolved reservation is never dispatched again, including after process death.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from uuid import uuid4

from app import db

CONDITIONS = frozenset(
    [("gpt-6.1-terra", effort) for effort in ("low", "medium", "high", "xhigh", "max")]
    + [("gpt-6.1-sol", "high"), ("gpt-6-luna", "high")]
)
CODING_MODELS = frozenset({"gpt-6.1-terra", "gpt-6.1-sol"})
MAX_CALLS = 56  # Task invocations, not internal provider requests.
GENERATED_BUDGET = 500000
WALL_SECONDS = 5400
LEASE_CHECK_SECONDS = 0.25
TOKEN_POLICY = "soft_stop_unbounded_single_invocation_overshoot"
TOKEN_RISK = (
    "No verified per-generation token cap. output_tokens includes reasoning; "
    "reasoning_tokens is a subset and is not added. Serial soft stop at 500000 "
    "aggregate output tokens; unknown usage or unresolved invocation stops remaining "
    "tasks. One task may contain multiple provider requests: token overshoot has no "
    "verified finite bound. Deadline interrupt/disconnect does not prove remote cancellation."
)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def manifest_hash(manifest: dict) -> str:
    content = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return hashlib.sha256(canonical(content).encode()).hexdigest()


def validate_conditions(conditions: list[dict], *, stage: str = "legacy",
                        runtime_supported_efforts: dict | None = None) -> int:
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("manifest requires model/effort conditions")
    pairs = []
    for row in conditions:
        if (not isinstance(row, dict) or not isinstance(row.get("model"), str)
                or not isinstance(row.get("effort"), str)):
            raise ValueError("invalid condition")
        pairs.append((row["model"], row["effort"]))
    if len(set(pairs)) != len(pairs):
        raise ValueError("duplicate model/effort condition")
    if stage == "legacy":
        if set(pairs) != CONDITIONS:
            raise ValueError("model/effort cohort differs from the authorized comparison")
        return 2
    if stage != "coding" or not isinstance(runtime_supported_efforts, dict) or set(runtime_supported_efforts) != CODING_MODELS:
        raise ValueError("coding stage requires both models' frozen runtime-supported efforts")
    expected = set()
    for model, efforts in runtime_supported_efforts.items():
        if (not isinstance(efforts, list) or not efforts
                or any(not isinstance(item, str) or not item.strip() for item in efforts)
                or len(set(efforts)) != len(efforts)):
            raise ValueError("unsupported or duplicate frozen coding effort")
        expected.update((model, effort) for effort in efforts)
    if set(pairs) != expected:
        raise ValueError("coding matrix must contain all frozen runtime-supported efforts")
    if 4 * len(expected) > MAX_CALLS:
        raise ValueError("coding matrix exceeds the approved task-invocation cap")
    return 1


def validate_manifest(manifest: dict) -> list[dict]:
    fields = {"fixtures", "conditions", "repeats"}
    if isinstance(manifest, dict) and manifest.get("stage") == "coding":
        fields |= {"stage", "runtime_supported_efforts"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise ValueError("manifest needs exactly fixtures, conditions, repeats")
    fixtures, conditions = manifest["fixtures"], manifest["conditions"]
    repeats = validate_conditions(conditions, stage=manifest.get("stage", "legacy"),
        runtime_supported_efforts=manifest.get("runtime_supported_efforts"))
    if type(manifest["repeats"]) is not int or manifest["repeats"] != repeats:
        raise ValueError("manifest repeat count differs from the approved stage")
    if not isinstance(fixtures, list) or len(fixtures) != 4:
        raise ValueError("manifest requires four public synthetic fixtures")
    ids = set()
    for fixture in fixtures:
        if (not isinstance(fixture, dict) or set(fixture) != {"id", "prompt"}
                or not isinstance(fixture["id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", fixture["id"])
                or fixture["id"] in ids or not isinstance(fixture["prompt"], str)
                or not fixture["prompt"].strip()):
            raise ValueError("invalid or duplicate fixture")
        ids.add(fixture["id"])
    for row in conditions:
        if set(row) != {"model", "effort"}:
            raise ValueError("invalid condition")
    if len(canonical(manifest).encode()) > 1024 * 1024:
        raise ValueError("manifest exceeds 1 MiB")
    return [
        {"prompt": fixture["prompt"], **condition, "billing": "subscription",
         "task_id": f"{fixture['id']}-r{repeat + 1}-c{index + 1}",
         "label": f"Task {number + 1}"}
        for number, (fixture, repeat, index, condition) in enumerate(
            (fixture, repeat, index, condition)
            for fixture in fixtures for repeat in range(repeats)
            for index, condition in enumerate(conditions)
        )
    ]


def _schema(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS eval_grants (
        id TEXT PRIMARY KEY, issuer TEXT NOT NULL, scope TEXT NOT NULL,
        task_id TEXT NOT NULL, task_identity TEXT NOT NULL, approval_ref TEXT NOT NULL UNIQUE,
        manifest_hash TEXT NOT NULL, manifest TEXT NOT NULL, plan TEXT NOT NULL,
        issued_at REAL NOT NULL, expires_at REAL NOT NULL,
        run_id TEXT UNIQUE, deadline REAL, token_policy TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS eval_invocations (
        grant_id TEXT NOT NULL REFERENCES eval_grants(id), invocation INTEGER NOT NULL,
        run_id TEXT NOT NULL, task_id TEXT NOT NULL, origin TEXT NOT NULL,
        actor_id TEXT NOT NULL UNIQUE, reserved_at REAL NOT NULL,
        result TEXT, generated_tokens INTEGER,
        PRIMARY KEY(grant_id, invocation))""")


def _root(actor):
    # Same authenticated root/project identity as existing global-rule authorization.
    from app.temp_rules import _is_orchestra_orchestrator, _require_orchestrator
    _require_orchestrator(actor)
    if not _is_orchestra_orchestrator(actor):
        raise PermissionError("evaluation grants require the root Orchestra orchestrator")


def issue(actor: dict | None, *, task_id: str, manifest: dict, expected_hash: str,
          approval_ref: str, expires_at: float, token_policy: str,
          fixture_inputs: dict[str, str] | None = None, run_order_csv: str = "") -> dict:
    _root(actor)
    from app.task_refs import parse_task_ref
    from app.tm import resolve_scoped_task_identity
    task_id = parse_task_ref(task_id).key
    if "manifest_sha256" in manifest:
        from app.eval_fixtures import plan
        tasks = plan(manifest, fixture_inputs or {}, run_order_csv)
        if task_id != manifest.get("task_id"):
            raise ValueError("frozen pack task identity mismatch")
    else:
        if fixture_inputs or run_order_csv:
            raise ValueError("file inputs require a frozen pack manifest")
        tasks = validate_manifest(manifest)
    digest = manifest_hash(manifest)
    if digest != expected_hash or manifest.get("manifest_sha256", digest) != digest:
        raise ValueError("frozen manifest hash mismatch")
    if len(canonical(tasks).encode()) > 1024 * 1024:
        raise ValueError("evaluation execution plan exceeds 1 MiB")
    if not isinstance(approval_ref, str) or not approval_ref.strip():
        raise ValueError("owner permission record reference is required")
    if token_policy != TOKEN_POLICY:
        raise ValueError(f"explicit experiment soft-stop acknowledgement required: {TOKEN_RISK}")
    now = time.time()
    if (isinstance(expires_at, bool) or not isinstance(expires_at, (int, float))
            or not math.isfinite(expires_at) or not now < expires_at <= now + WALL_SECONDS):
        raise ValueError("grant expiry must be within 90 minutes")
    identity = resolve_scoped_task_identity(actor["scope"], task_id)
    grant_id = uuid4().hex
    with db._conn() as connection:
        _schema(connection)
        connection.execute("""INSERT INTO eval_grants
            (id,issuer,scope,task_id,task_identity,approval_ref,manifest_hash,manifest,plan,
             issued_at,expires_at,token_policy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (grant_id, actor["id"], actor["scope"], task_id, canonical(identity),
             approval_ref.strip(), digest, canonical(manifest), canonical(tasks), now, expires_at, token_policy))
    return {"grant_id": grant_id, "task_id": task_id, "manifest_hash": digest,
            "max_calls": MAX_CALLS, "planned_generated_tokens": GENERATED_BUDGET,
            "planned_task_invocations": len(tasks),
            "token_policy": TOKEN_POLICY, "token_risk": TOKEN_RISK, "expires_at": expires_at}


def _grant(connection, grant_id):
    _schema(connection)
    row = connection.execute("SELECT * FROM eval_grants WHERE id=?", (grant_id,)).fetchone()
    if row is None:
        raise ValueError("unknown evaluation grant")
    return dict(row)


def _match(row, task_id, digest):
    if row["task_id"] != task_id or row["manifest_hash"] != digest:
        raise ValueError("grant task/manifest mismatch")


def bind(actor, *, grant_id: str, task_id: str, manifest_hash: str, run_id: str) -> dict:
    _root(actor)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("invalid evaluation run id")
    with db._conn() as connection:
        _schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        row = _grant(connection, grant_id)
        _match(row, task_id, manifest_hash)
        if actor["id"] != row["issuer"] or actor["scope"] != row["scope"]:
            raise PermissionError("only the issuing root may bind this grant")
        if row["run_id"] is not None:
            raise ValueError("evaluation grant is single-use and already bound")
        now = time.time()
        if now >= row["expires_at"]:
            raise ValueError("evaluation grant expired")
        deadline = min(now + WALL_SECONDS, row["expires_at"])
        connection.execute("UPDATE eval_grants SET run_id=?,deadline=? WHERE id=?",
                           (run_id, deadline, grant_id))
    return {"grant_id": grant_id, "task_id": task_id, "manifest_hash": manifest_hash,
            "deadline": deadline, "tasks": json.loads(row["plan"]),
            "token_policy": row["token_policy"], "token_risk": TOKEN_RISK}


def reserve(*, grant_id: str, run_id: str, task_id: str, manifest_hash: str,
            invocation: int) -> tuple[dict, dict | None]:
    if type(invocation) is not int or not 0 <= invocation < MAX_CALLS:
        raise ValueError("invocation outside the 56 task slots")
    with db._conn() as connection:
        _schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        row = _grant(connection, grant_id)
        _match(row, task_id, manifest_hash)
        if row["run_id"] != run_id:
            raise ValueError("grant run mismatch or unbound grant")
        if invocation >= len(json.loads(row["plan"])):
            raise ValueError("invocation outside the frozen task plan")
        previous = connection.execute(
            "SELECT result FROM eval_invocations WHERE grant_id=? AND invocation=?",
            (grant_id, invocation)).fetchone()
        if previous:
            if previous["result"] is None:
                raise ValueError("outcome_unknown: reserved invocation must never be redispatched")
            return row, json.loads(previous["result"])
        if time.time() >= min(row["expires_at"], row["deadline"]):
            raise ValueError("evaluation deadline expired")
        counts = connection.execute("""SELECT count(*) AS calls,
            sum(generated_tokens) AS tokens,
            sum(CASE WHEN generated_tokens IS NULL THEN 1 ELSE 0 END) AS unknown
            FROM eval_invocations WHERE grant_id=?""", (grant_id,)).fetchone()
        if counts["unknown"]:
            raise ValueError("unknown usage or unresolved invocation: stop remaining tasks")
        if counts["calls"] >= MAX_CALLS or (counts["tokens"] or 0) >= GENERATED_BUDGET:
            raise ValueError("evaluation planned budget exhausted")
        # Serial, fixed order also makes replay and missing-task recovery deterministic.
        if invocation != counts["calls"]:
            raise ValueError("evaluation invocation order mismatch")
        connection.execute("""INSERT INTO eval_invocations
            (grant_id,invocation,run_id,task_id,origin,actor_id,reserved_at)
            VALUES (?,?,?,?,?,?,?)""", (grant_id, invocation, run_id, task_id,
            "workflow_eval_worker", f"eval-{grant_id}-{invocation}", time.time()))
    # Commit happens BEFORE quota/catalog/provider admission, never after dispatch.
    return row, None


def finish(grant_id: str, invocation: int, result: dict) -> None:
    from scripts.wf_adapters import AdapterResult, Usage
    # Validate the result before persisting a replayable terminal receipt.
    adapter_result = AdapterResult(**{**result, "usage": Usage(**result["usage"])})
    generated = adapter_result.usage.output_tokens if adapter_result.usage_known else None
    for name, count in asdict(adapter_result.usage).items():
        if type(count) is not int or count < 0:
            raise ValueError(f"invalid evaluation usage: {name}")
    reasoning = adapter_result.reasoning_tokens
    if reasoning is not None and (type(reasoning) is not int or reasoning < 0
                                  or reasoning > adapter_result.usage.output_tokens):
        raise ValueError("invalid evaluation reasoning subset")
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM eval_invocations WHERE grant_id=? AND invocation=?",
                                 (grant_id, invocation)).fetchone()
        if row is None or row["result"] is not None:
            raise ValueError("missing reservation or terminal result already recorded")
        grant = _grant(connection, grant_id)
        # Non-session actor: never attribute evaluation usage to the root orchestrator.
    # Idempotent accounting precedes the receipt. A crash between the transactions
    # leaves the reservation unresolved and stops the grant, never reruns a provider.
    db.turn_usage_add(
        event_id=f"eval:{grant_id}:{invocation}", session_id=row["actor_id"],
        scope=grant["scope"], task_id=row["task_id"], runtime="codex",
        model=adapter_result.model, billing_mode="subscription", ok=adapter_result.ok,
        stop_reason=adapter_result.stop_reason, cost_usd=adapter_result.cost_usd,
        cost_unaccounted=adapter_result.cost_unaccounted,
        **asdict(adapter_result.usage), reasoning_tokens=adapter_result.reasoning_tokens,
    )
    with db._conn() as connection:
        connection.execute("""UPDATE eval_invocations SET result=?,generated_tokens=?
            WHERE grant_id=? AND invocation=?""", (canonical(result), generated, grant_id, invocation))


def check_catalog(model: str, effort: str, *, coding_efforts: dict | None = None) -> None:
    from app.models import MANUAL_ONLY_MODEL_IDS, get_model_spec, ensure_dashboard_visible, _load_model_flags
    spec = get_model_spec(model)
    permitted = (model, effort) in CONDITIONS if coding_efforts is None else (
        model in CODING_MODELS and effort in coding_efforts.get(model, []))
    if not permitted or spec.runtime != "codex" or not spec.available:
        raise ValueError("evaluation model/runtime/effort unavailable")
    ensure_dashboard_visible(model)
    # Manual-only serialization clamps agents=False even for set_model_flags(True).
    # It is ordinary-worker policy, not an independently expressible eval revocation.
    # A proved, task-bound grant supplies this purpose-specific exception; dashboard
    # visibility/availability stay authoritative. Luna's worker disable is unchanged.
    if model not in MANUAL_ONLY_MODEL_IDS and _load_model_flags().get(model, {}).get("agents") is False:
        raise ValueError("evaluation model explicitly disabled in catalog")


def check_slot(slot_id: str, run_id: str) -> None:
    from app.workflow_scheduler import get_scheduler
    scheduler = get_scheduler()
    with scheduler._connect() as connection:
        row = connection.execute("""SELECT 1 FROM requests WHERE request_id=? AND run_id=?
            AND lease_until>? AND last_seen>?""",
            (slot_id, run_id, time.time(), time.time() - scheduler.lease_seconds)).fetchone()
    if row is None:
        raise ValueError("evaluation requires a live scheduler slot for this run")


def check_task_identity(row: dict) -> None:
    from app.tm import resolve_scoped_task_identity
    from app.task_refs import task_ref
    identity = resolve_scoped_task_identity(row["scope"], row["task_id"])
    expected = json.loads(row["task_identity"])
    for key in ("stable_id", "project_id", "ref_prefix", "par_number"):
        if identity.get(key) != expected.get(key):
            raise ValueError("grant task identity or project scope changed")
    if "par_number" in identity and task_ref(identity) != row["task_id"]:
        raise ValueError("grant task reference changed")


def prepare_synthetic_workspace(task: dict) -> Path:
    """Fresh Git boundary outside every checkout; keep outputs for parent validation."""
    from app.eval_fixtures import seed_path
    parent = Path(tempfile.gettempdir()).resolve()
    for ancestor in (parent, *parent.parents):
        if (ancestor / ".git").exists() or (ancestor / ".git").is_symlink():
            raise ValueError("evaluation temporary workspace is inside a real checkout")
    cwd = Path(tempfile.mkdtemp(prefix="orchestra-eval-", dir=parent)).resolve()
    # Ignore inherited GIT_DIR/WORK_TREE/OBJECT_DIRECTORY and config redirections.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    initialized = subprocess.run(["git", "-c", "init.templateDir=", "init", "-q", str(cwd)],
                                 env=env, capture_output=True, text=True, timeout=10, check=False)
    if initialized.returncode:
        raise ValueError(f"cannot initialize synthetic Git workspace: {initialized.stderr.strip()}")
    for relative, content in task.get("seed_files", {}).items():
        path = cwd / seed_path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (cwd / "prompt.md").write_text(task["prompt"], encoding="utf-8")
    return cwd


async def managed_call(row: dict, invocation: int, task: dict) -> dict:
    """Use the existing managed app-server/auth/home path; never one-shot CLI auth."""
    from app.backend_codex import CodexBackend
    from scripts.wf_adapters import AdapterResult, Usage
    actor_id = f"eval-{row['id']}-{invocation}"
    cwd = prepare_synthetic_workspace(task)
    backend = CodexBackend(model=task["model"], cwd=str(cwd), reasoning_effort=task["effort"],
                           evaluation_actor_id=actor_id,
                           is_orchestrator=False)
    text, errors, terminal = [], [], None
    async def run():
        nonlocal terminal
        await backend.connect()
        mcp = await backend._request("mcpServerStatus/list", {"threadId": backend.session_id, "limit": 100})
        if mcp.get("data") != [] or mcp.get("nextCursor"):
            raise ValueError("evaluation requires a confirmed empty MCP server registry")
        # Public app-server read contracts; no login, refresh or auth-file inspection.
        # Reject unsupported/ambiguous responses for this experiment only.
        account = await backend._request("account/read", {"refreshToken": False})
        if (account.get("account") or {}).get("type") != "chatgpt" or account.get("requiresOpenaiAuth") is not True:
            raise ValueError("evaluation requires confirmed ChatGPT subscription auth")
        cursor = None
        for _ in range(20):
            params = {"limit": 100, "includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            listing = await backend._request("model/list", params)
            available = next((item for item in listing.get("data", [])
                              if item.get("model") == task["model"]), None)
            if available:
                efforts = {item.get("reasoningEffort") for item in available.get("supportedReasoningEfforts", [])}
                frozen = json.loads(row["manifest"])
                if frozen.get("stage") == "coding" and efforts != set(frozen["runtime_supported_efforts"][task["model"]]):
                    raise ValueError("runtime effort catalog differs from the frozen coding matrix")
                if available.get("hidden") or task["effort"] not in efforts:
                    raise ValueError("evaluation model/effort unavailable in current runtime catalog")
                break
            cursor = listing.get("nextCursor")
            if not cursor:
                raise ValueError("evaluation model absent from current runtime catalog")
        else:
            raise ValueError("evaluation runtime catalog pagination limit exceeded")
        # Connection and runtime reads can take time. Recheck ordinary admission
        # and the actual lease immediately before the first generation request.
        from app.quota_gate import get_worker_admission, require_worker_admission
        require_worker_admission(await asyncio.wait_for(
            get_worker_admission(task["model"]), max(0.001, row["deadline"] - time.time())))
        check_catalog(task["model"], task["effort"],
            coding_efforts=frozen.get("runtime_supported_efforts") if frozen.get("stage") == "coding" else None)
        check_slot(row["dispatch_slot_id"], row["run_id"])
        check_task_identity(row)
        if time.time() >= row["deadline"]:
            raise TimeoutError("evaluation deadline expired during connection")
        await backend.send(task["prompt"])
        async for event in backend.events():
            if event.type == "text":
                text.append(event.content)
            elif event.type == "error":
                errors.append(event.content)
            elif event.type == "turn_end":
                terminal = event
                break
    async def watch_lease():
        while True:
            await asyncio.sleep(LEASE_CHECK_SECONDS)
            check_slot(row["dispatch_slot_id"], row["run_id"])

    provider_task = asyncio.create_task(run())
    lease_task = asyncio.create_task(watch_lease())
    try:
        done, _ = await asyncio.wait({provider_task, lease_task},
            timeout=max(0.001, row["deadline"] - time.time()), return_when=asyncio.FIRST_COMPLETED)
        if lease_task in done:
            await lease_task
        if provider_task not in done:
            raise TimeoutError("evaluation controller deadline expired")
        await provider_task
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    finally:
        provider_task.cancel()
        lease_task.cancel()
        # Cancellation prevents our coroutine from starting another RPC. Stop the
        # app-server locally even if the HTTP caller is gone; remote outcome remains
        # unknown without an authoritative terminal usage receipt.
        try:
            await backend.interrupt()
        except Exception as error:
            errors.append(f"interrupt {type(error).__name__}: {error}")
        try:
            await backend.disconnect()
        except Exception as error:
            errors.append(f"disconnect {type(error).__name__}: {error}")
        await asyncio.gather(provider_task, lease_task, return_exceptions=True)
    metadata = terminal.metadata if terminal else {}
    if metadata.get("model_error"):
        errors.append(str(metadata["model_error"]))
    known = (terminal is not None and terminal.usage is not None
             and terminal.usage.aggregate.input_tokens + terminal.usage.aggregate.output_tokens > 0)
    usage = terminal.usage.aggregate if known else None
    return asdict(AdapterResult(
        text="".join(text), runtime="codex", model=task["model"],
        ok=bool(metadata.get("ok")) and not errors,
        stop_reason=str(metadata.get("stop_reason") or "outcome_unknown"),
        cost_usd=metadata.get("cost_usd"),
        cost_unaccounted=not known or bool(metadata.get("cost_unaccounted")),
        usage=Usage(usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                    usage.cache_create_tokens) if known else Usage(),
        usage_known=known, reasoning_tokens=metadata.get("reasoning_tokens"),
        error="\n".join(errors),
        workspace_path=str(cwd),
        model_calls=usage.model_calls if known else None,
    ))


async def dispatch(*, grant_id: str, run_id: str, task_id: str, manifest_hash: str,
                   invocation: int, slot_id: str, prompt: str, model: str, effort: str,
                   scheduler_available: bool = True) -> dict:
    from scripts.wf_adapters import _failed
    row, previous = reserve(grant_id=grant_id, run_id=run_id, task_id=task_id,
                            manifest_hash=manifest_hash, invocation=invocation)
    if previous is not None:
        return previous
    task = json.loads(row["plan"])[invocation]
    frozen = json.loads(row["manifest"])
    coding_efforts = frozen.get("runtime_supported_efforts") if frozen.get("stage") == "coding" else None
    try:
        if (prompt, model, effort) != (task["prompt"], task["model"], task["effort"]):
            raise ValueError("invocation differs from immutable fixture/condition")
        if not scheduler_available:
            raise ValueError("evaluation scheduler missing: agent cgroup unavailable")
        check_catalog(model, effort, coding_efforts=coding_efforts)
        check_slot(slot_id, run_id)
        check_task_identity(row)
        from app.quota_gate import get_worker_admission, require_worker_admission
        require_worker_admission(await asyncio.wait_for(
            get_worker_admission(model), max(0.001, row["deadline"] - time.time())))
        # Recheck the deadline after async admission, before entering the provider.
        if time.time() >= row["deadline"]:
            raise ValueError("evaluation deadline expired")
        check_catalog(model, effort, coding_efforts=coding_efforts)
        check_slot(slot_id, run_id)
        result = await managed_call({**row, "dispatch_slot_id": slot_id}, invocation, task)
    except Exception as error:
        result = asdict(_failed("codex", task["model"], f"{type(error).__name__}: {error}",
                                stop_reason="eval_refused"))
    finish(grant_id, invocation, result)
    return result


def snapshot(grant_id: str) -> dict:
    """Durable recovery receipt, including consumed slots whose outcomes are unknown."""
    with db._conn() as connection:
        row = _grant(connection, grant_id)
        invocations = [dict(record) for record in connection.execute(
            "SELECT * FROM eval_invocations WHERE grant_id=? ORDER BY invocation", (grant_id,))]
    for item in invocations:
        item["result"] = json.loads(item["result"]) if item["result"] else None
        item["usage_known"] = item["generated_tokens"] is not None
        item["state"] = "finished" if item["result"] is not None else "outcome_unknown"
    return {"grant_id": grant_id, "task_id": row["task_id"], "run_id": row["run_id"],
            "manifest_hash": row["manifest_hash"], "deadline": row["deadline"],
            "consumed_task_invocations": len(invocations), "max_task_invocations": MAX_CALLS,
            "planned_task_invocations": len(json.loads(row["plan"])),
            "known_generated_tokens": sum(item["generated_tokens"] or 0 for item in invocations),
            "unknown_usage_invocations": sum(not item["usage_known"] for item in invocations),
            "planned_generated_tokens": GENERATED_BUDGET, "token_policy": row["token_policy"],
            "token_risk": TOKEN_RISK, "invocations": invocations}
