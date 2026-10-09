"""Background Jobs API routes."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.deps import manager

router = APIRouter(prefix="/api/bg", tags=["bg-jobs"])
_WORKFLOW_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_WORKFLOW_HEADERS = {"Cache-Control": "no-store, private, max-age=0"}
WORKFLOW_RUNS_DIR = Path(__file__).resolve().parents[2] / "data" / "workflow-runs"


def _workflow_run_dir(run_id: str) -> Path | None:
    if not _WORKFLOW_RUN_ID.fullmatch(run_id):
        return None
    root = WORKFLOW_RUNS_DIR.resolve()
    run_dir = (root / run_id).resolve()
    try:
        run_dir.relative_to(root)
    except ValueError:
        return None
    return run_dir


def _read_workflow_json(path: Path, *, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _workflow_journal(path: Path) -> list[dict]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []
    rows = []
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            if index == len(lines) - 1 and not line.endswith(b"\n"):
                break
            raise
        if isinstance(event, dict):
            rows.append(event)
    return rows


def _workflow_tasks(request: dict) -> list[list[dict]]:
    if request.get("mode") == "stages":
        return [stage.get("tasks", []) for stage in request.get("stages", [])]
    return [request.get("tasks", [])]


def _workflow_answer_preview(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(str(text).split())
    return text[:280] + ("…" if len(text) > 280 else "")


def _workflow_finished(run_dir: Path) -> bool:
    manifest = run_dir / "manifest.json"
    journal = run_dir / "journal.jsonl"
    try:
        data = _read_workflow_json(manifest, default={})
        if isinstance(data, dict) and isinstance(data.get("finished"), bool):
            return data["finished"]
        return manifest.is_file() and (
            not journal.exists() or manifest.stat().st_mtime_ns >= journal.stat().st_mtime_ns
        )
    except OSError:
        return manifest.is_file()


def _workflow_detail(run_id: str, run_dir: Path) -> dict:
    request = _read_workflow_json(run_dir / "request.json", default={}) or {}
    manifest = _read_workflow_json(run_dir / "manifest.json", default={}) or {}
    events = _workflow_journal(run_dir / "journal.jsonl")
    finished = _workflow_finished(run_dir)
    latest_by_key = {}
    for event in events:
        key = event.get("call_key")
        if key:
            previous = latest_by_key.get(str(key), {})
            latest_by_key[str(key)] = {**previous, **event, "label": event.get("label") or previous.get("label", "")}

    result = manifest.get("result")
    flat_results = []
    def flatten(value):
        if isinstance(value, list):
            for item in value:
                flatten(item)
        else:
            flat_results.append(value)
    flatten(result or [])

    stages = []
    tasks_flat = [task for group in _workflow_tasks(request) for task in group]
    task_states = {}
    for label, event in latest_by_key.items():
        if event.get("label"):
            task_states[str(event["label"])] = event
    for step in manifest.get("steps", []):
        if isinstance(step, dict) and step.get("label"):
            task_states[str(step["label"])] = step
    all_steps = [step for step in manifest.get("steps", []) if isinstance(step, dict)]
    if len(all_steps) == len(tasks_flat):
        for index, step in enumerate(all_steps):
            label = str(tasks_flat[index].get("label") or f"Task {index + 1}")
            task_states.setdefault(label, step)

    global_index = 0
    for stage_no, group in enumerate(_workflow_tasks(request)):
        items = []
        for task_no, task in enumerate(group):
            label = str(task.get("label") or f"Task {task_no + 1}")
            event = task_states.get(label, {})
            status = "pending"
            reason = event.get("reason") or event.get("event")
            if reason == "completed":
                status = "completed" if event.get("value") is not None else "failed"
            elif reason == "slot_waiting":
                status = "waiting"
            elif reason in {"prepare_failed", "schema_invalid", "skipped", "accounting_failed"}:
                status = "failed"
            elif reason in {"task_started", "dispatched", "attempt_finished", "slot_acquired"}:
                status = "running"
            value = flat_results[global_index] if global_index < len(flat_results) else None
            if value is not None:
                status = "completed"
            elif manifest and (manifest.get("complete") or manifest.get("partial_reason")) and status == "pending":
                status = "failed"
            call_key = str(value.get("value_id")) if isinstance(value, dict) else str(event.get("call_key") or "")
            result_url = f"/api/bg/workflows/{run_id}/results/{global_index}"
            items.append({
                "index": task_no,
                "global_index": global_index,
                "label": label,
                "model": str(task.get("model") or "gpt-6-luna"),
                "status": status,
                "reason": str(event.get("reason") or (event.get("event") if status == "failed" else "") or ""),
                "position": event.get("position"),
                "error": str(event.get("error") or ""),
                "answer_preview": _workflow_answer_preview(value.get("data")) if finished and isinstance(value, dict) else None,
                "result_url": result_url if finished and value is not None else "",
                "call_key": call_key,
            })
            global_index += 1
        stages.append({"index": stage_no, "tasks": items})

    tasks = [task for stage in stages for task in stage["tasks"]]
    counts = {state: sum(task["status"] == state for task in tasks)
              for state in ("running", "waiting", "completed", "failed", "pending")}
    created_at = request.get("dashboard", {}).get("created_at")
    if not created_at:
        try:
            created_at = datetime.fromtimestamp((run_dir / "request.json").stat().st_mtime, timezone.utc).isoformat()
        except FileNotFoundError:
            created_at = ""
    ended_at = ""
    if manifest:
        try:
            ended_at = datetime.fromtimestamp((run_dir / "manifest.json").stat().st_mtime, timezone.utc).isoformat()
        except FileNotFoundError:
            pass
    try:
        started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00")) if ended_at else datetime.now(timezone.utc)
        elapsed_seconds = max(0, int((ended - started).total_seconds()))
    except (AttributeError, TypeError, ValueError):
        elapsed_seconds = None
    return {
        "run_id": run_id,
        "mode": request.get("mode", "parallel"),
        "task_id": request.get("dashboard", {}).get("task_id", ""),
        "repo": request.get("dashboard", {}).get("repo", ""),
        "budget_usd": request.get("dashboard", {}).get("budget_usd", manifest.get("budget_usd")),
        "max_calls": request.get("dashboard", {}).get("max_calls"),
        "max_concurrency": request.get("dashboard", {}).get("max_concurrency"),
        "scheduler": manifest.get("scheduler") or {},
        "spent_usd": manifest.get("spent_usd", 0),
        "complete": bool(manifest.get("complete", False)),
        "finished": finished,
        "partial_reason": manifest.get("partial_reason"),
        "elapsed_seconds": elapsed_seconds,
        "counts": counts,
        "stages": stages,
        "available": bool(tasks_flat),
    }


class WorkflowSlotRequest(BaseModel):
    request_id: str
    run_id: str
    label: str = ""


class WorkflowSlotRelease(BaseModel):
    request_id: str


@router.post("/workflow-scheduler/acquire")
async def bg_workflow_slot_acquire(req: WorkflowSlotRequest, request: Request):
    if not req.request_id or len(req.request_id) > 512 or not req.run_id or len(req.run_id) > 128:
        return JSONResponse({"error": "invalid workflow slot identity"}, status_code=400)
    if not getattr(request.app.state, "agent_cgroup", ""):
        required = bool(getattr(request.app.state, "agent_cgroup_required", False))
        return JSONResponse({
            "error": "agent cgroup unavailable",
            "detail": getattr(request.app.state, "agent_cgroup_error", ""),
            "scheduler_missing": not required,
        }, status_code=503 if required else 404)
    try:
        from app.workflow_scheduler import get_scheduler
        return get_scheduler().acquire(req.request_id, req.run_id, req.label)
    except (OSError, RuntimeError, ValueError) as error:
        return JSONResponse({"error": f"workflow scheduler unavailable: {error}"}, status_code=503)


@router.post("/workflow-scheduler/release")
async def bg_workflow_slot_release(req: WorkflowSlotRelease):
    from app.workflow_scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler.release(req.request_id)
    return {"released": True, **scheduler.snapshot()}


@router.get("/workflow-scheduler")
async def bg_workflow_scheduler_status(request: Request):
    if not getattr(request.app.state, "agent_cgroup", ""):
        required = bool(getattr(request.app.state, "agent_cgroup_required", False))
        return JSONResponse({
            "error": "agent cgroup unavailable",
            "scheduler_missing": not required,
        }, status_code=503 if required else 404)
    from app.workflow_scheduler import get_scheduler
    return get_scheduler().snapshot()


@router.get("/workflows/{run_id}")
async def bg_workflow_detail(run_id: str, request: Request):
    run_dir = _workflow_run_dir(run_id)
    if run_dir is None:
        return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
    if not run_dir.is_dir():
        return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
    try:
        detail = _workflow_detail(run_id, run_dir)
        if getattr(request.app.state, "agent_cgroup", ""):
            try:
                from app.workflow_scheduler import get_scheduler
                detail["scheduler"] = get_scheduler().snapshot()
            except (OSError, RuntimeError, ValueError):
                pass
        return JSONResponse(detail, headers=_WORKFLOW_HEADERS)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse(
            {"error": "workflow data unavailable"},
            status_code=500,
            headers=_WORKFLOW_HEADERS,
        )


@router.get("/workflows/{run_id}/results/{index}")
async def bg_workflow_result(run_id: str, index: int):
    run_dir = _workflow_run_dir(run_id)
    if run_dir is None or not run_dir.is_dir() or index < 0:
        return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
    try:
        detail = _workflow_detail(run_id, run_dir)
        task = next((item for stage in detail["stages"] for item in stage["tasks"]
                     if item["global_index"] == index), None)
        call_key = (task or {}).get("call_key", "")
        if not re.fullmatch(r"[0-9a-f]{64}:[0-9]+", call_key):
            return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
        path = (run_dir / "steps" / f"{call_key.replace(':', '-')}.json").resolve()
        path.relative_to(run_dir.resolve())
        value = _read_workflow_json(path)
        if value is None:
            return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)
        return JSONResponse(value, headers=_WORKFLOW_HEADERS)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "not found"}, status_code=404, headers=_WORKFLOW_HEADERS)


class BgJobCreateRequest(BaseModel):
    type: str
    config: dict = {}
    message: str = ""
    target_name: str = ""
    target_scope: str = ""
    timeout_seconds: int = 3600
    created_by: str = ""
    receipt_id: str = ""


@router.post("/jobs")
async def bg_job_create(req: BgJobCreateRequest, request: Request = None):
    from app.bg_jobs import bg_manager
    scope = req.target_scope.rstrip("/")
    name = req.target_name
    if not scope or not name:
        return JSONResponse({"error": "target_name and target_scope required"}, status_code=400)
    session = manager.get_by_name(name, scope)
    if not session:
        return JSONResponse({"error": f"session '{name}' not found in scope"}, status_code=404)
    session_id = session.id
    if not str(session_id or "").strip():
        # Раньше пустой id уезжал в джоб и всплывал как 500 где-то ниже (#54).
        # Отказ на границе: 400 с причиной, которую видно вызывающему агенту.
        return JSONResponse(
            {"error": f"session '{name}' has no id — it cannot be a background job target; "
                      f"respawn the worker"},
            status_code=400,
        )
    from app.db import get_session, review_receipt_get, review_receipt_finish, bg_get_jobs
    from app.work_review import assignment, _task_reviews, MAX_REVIEW_REQUESTS
    from app.db import _conn
    import json
    target = get_session(session_id) or {}
    run = assignment(scope, session_id, str(target.get("task_id") or ""))
    config = dict(req.config)
    if req.type == "run" and not config.get("host"):
        caller_session_id = request.headers.get("x-orchestra-session-id", "") if request else ""
        caller = get_session(caller_session_id) if caller_session_id else None
        caller = caller or target
        candidates = (caller.get("worktree_path"), caller.get("cwd"), caller.get("scope"))
        cwd = next((Path(path) for path in candidates if path and Path(path).is_dir()), None)
        if cwd is None:
            return JSONResponse(
                {"error": "no existing caller worktree, cwd, or scope directory for local run"},
                status_code=400,
            )
        config["cwd"] = str(cwd)
    config.pop("review_receipt_id", None)
    receipt = review_receipt_get(req.receipt_id) if req.receipt_id else None
    review_job = req.type == "run" and bool(req.receipt_id)
    if review_job:
        from app.mcp_proof import check_mcp_proof, PROOF_HEADER
        caller = request.headers.get("x-orchestra-session-id", "") if request else ""
        proof = request.headers.get(PROOF_HEADER, "") if request else ""
        if caller != session_id or not check_mcp_proof(caller, proof) or target.get("role") not in {"worker", "full-cycle"} or target.get("is_orchestrator"):
            return JSONResponse({"error": "review_requester_forbidden"}, status_code=403)
        if not receipt or receipt["session_id"] != session_id or receipt["scope"] != scope:
            return JSONResponse({"error": "review_protocol_upgrade_required: reconnect MCP before requesting review"}, status_code=409)
        if config.get("success_file") != receipt["artifact_path"]:
            return JSONResponse({"error": "review_artifact_mismatch"}, status_code=409)
        # Run jobs do not await between lookup, save and start. Replay returns the saved job,
        # including the crash gap before the MCP process linked its receipt to the job.
        for job in bg_get_jobs(session_id=session_id):
            previous = json.loads(job["config"])
            if previous.get("review_receipt_id") == req.receipt_id:
                if previous.get("command") != config.get("command"):
                    return JSONResponse({"error": "review_job_payload_changed"}, status_code=409)
                return {"id": job["id"], "type": "run", "status": job["status"]}
        if run is None or run["status"] != "requested" or receipt["task_id"] != str(target.get("task_id") or ""):
            return JSONResponse({"error": "review_task_not_active"}, status_code=409)
        with _conn() as connection:
            rows = _task_reviews(connection, run)
        if receipt["status"] != "requested" or len(rows) > MAX_REVIEW_REQUESTS or any(r["status"] == "requested" and r["receipt_id"] != req.receipt_id for r in rows):
            return JSONResponse({"error": "review_budget_or_active_request_conflict"}, status_code=409)
        config.update(review_receipt_id=req.receipt_id)
    result = await bg_manager.create(
        job_type=req.type, config=config, message=req.message,
        target_session_id=session_id, target_name=name, target_scope=scope,
        created_by=str(target.get("name") or name) if review_job else req.created_by, timeout_seconds=req.timeout_seconds,
    )
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    if review_job and result.get("id"):
        review_receipt_finish(req.receipt_id, {"job_id": result["id"]})
    return result


@router.get("/jobs")
async def bg_job_list(scope: str = "", session_id: str = ""):
    from app.db import bg_get_jobs
    return bg_get_jobs(scope=scope or None, session_id=session_id or None)


@router.delete("/jobs/{job_id}")
async def bg_job_cancel(job_id: str):
    from app.bg_jobs import bg_manager
    result = await bg_manager.cancel(job_id)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result
