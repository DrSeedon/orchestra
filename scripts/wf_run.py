#!/usr/bin/env python3
"""Deterministic scripted fan-out hosted by an Orchestra background run job."""

from __future__ import annotations

import argparse
import asyncio
import ast
import hashlib
import inspect
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wf_adapters import AdapterResult, persist_turn_usage, run_adapter


Adapter = Callable[..., Awaitable[AdapterResult]]
UsageWriter = Callable[..., bool]
ReadinessChecker = Callable[[str], Awaitable[dict]]
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SCHEMA_META = {"$schema", "$id", "title", "description", "default", "examples"}
DEFAULT_WORKFLOW_MODULES: tuple[str, ...] = (
    "communication-style",
    "user-values",
    "knowledge",
    "code-quality",
)


class Journal:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: dict) -> None:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_bytes().splitlines(keepends=True)
        rows: list[dict] = []
        for index, raw in enumerate(lines):
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                if index == len(lines) - 1 and not raw.endswith(b"\n"):
                    intact_bytes = sum(len(line) for line in lines[:index])
                    with self.path.open("r+b") as fh:
                        fh.truncate(intact_bytes)
                        fh.flush()
                        os.fsync(fh.fileno())
                    break
                raise ValueError(f"journal corruption at line {index + 1}: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"journal line {index + 1} is not an object")
            rows.append(row)
        return rows


@dataclass(frozen=True)
class WorkflowValue:
    data: Any
    value_id: str
    result_path: str
    workspace_path: str = ""
    free_sources: frozenset[str] = field(default_factory=frozenset)
    verified_sources: frozenset[str] = field(default_factory=frozenset)

    def to_record(self) -> dict:
        return {
            "data": self.data,
            "value_id": self.value_id,
            "result_path": self.result_path,
            "workspace_path": self.workspace_path,
            "free_sources": sorted(self.free_sources),
            "verified_sources": sorted(self.verified_sources),
        }

    @classmethod
    def from_record(cls, row: dict) -> "WorkflowValue":
        return cls(
            data=row.get("data"),
            value_id=str(row["value_id"]),
            result_path=str(row["result_path"]),
            workspace_path=str(row.get("workspace_path") or ""),
            free_sources=frozenset(str(item) for item in row.get("free_sources") or []),
            verified_sources=frozenset(
                str(item) for item in row.get("verified_sources") or []
            ),
        )


class Budget:
    def __init__(self, maximum_usd: float, maximum_calls: int):
        if maximum_usd < 0:
            raise ValueError("budget_usd must be non-negative")
        if maximum_calls < 1:
            raise ValueError("max_calls must be positive")
        self.maximum_usd = float(maximum_usd)
        self.maximum_calls = int(maximum_calls)
        self.spent_usd = 0.0
        self.dispatched_calls = 0

    def remaining_usd(self) -> float:
        return max(0.0, self.maximum_usd - self.spent_usd)

    def remaining_calls(self) -> int:
        return max(0, self.maximum_calls - self.dispatched_calls)

    def exhausted(self) -> bool:
        return self.spent_usd >= self.maximum_usd or self.dispatched_calls >= self.maximum_calls


def _jsonable(value: Any) -> Any:
    if isinstance(value, WorkflowValue):
        return value.to_record()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"workflow value is not JSON serializable: {type(value).__name__}")


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, False)


def _validate_schema(value: Any, schema: dict, path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"schema at {path} must be an object")
    supported = {
        "type", "properties", "required", "additionalProperties", "items", "enum", "const",
        "minItems", "maxItems", "minLength", "maxLength",
    } | _SCHEMA_META
    unknown = set(schema) - supported
    if unknown:
        raise ValueError(f"unsupported schema keyword at {path}: {sorted(unknown)[0]}")
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not one of the allowed values")
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(isinstance(item, str) and _type_matches(value, item) for item in expected):
            raise ValueError(f"{path} has the wrong type; expected one of {expected}")
    elif expected is not None:
        if not isinstance(expected, str) or not _type_matches(value, expected):
            raise ValueError(f"{path} has the wrong type; expected {expected}")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            raise ValueError(f"properties at {path} must be an object")
        required = schema.get("required") or []
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ValueError(f"required at {path} must be a string array")
        for name in required:
            if name not in value:
                raise ValueError(f"{path}.{name} is required")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                raise ValueError(f"{path} has unexpected property {sorted(extra)[0]}")
        for name, child in properties.items():
            if name in value:
                _validate_schema(value[name], child, f"{path}.{name}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise ValueError(f"{path} has fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ValueError(f"{path} has more than {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_schema(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise ValueError(f"{path} is shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ValueError(f"{path} is longer than {schema['maxLength']}")


def _parse_and_validate(raw: str, schema: dict) -> Any:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg} at line {error.lineno} column {error.colno}") from error
    _validate_schema(value, schema)
    return value


def _schema_retry_prompt(prompt: str, error: str, schema: dict) -> str:
    return (
        prompt
        + "\n\nValidation error: "
        + error
        + "\nReturn only JSON that satisfies this schema:\n"
        + json.dumps(schema, ensure_ascii=False, sort_keys=True)
    )


def validate_pilot_manifest(manifest: dict) -> None:
    tickets = manifest.get("tickets") if isinstance(manifest, dict) else None
    if not isinstance(tickets, list):
        raise ValueError("pilot manifest must contain tickets")
    accepted = {
        str(row.get("ticket_id"))
        for row in tickets
        if isinstance(row, dict)
        and row.get("status") == "completed"
        and row.get("schema_valid") is True
        and row.get("ticket_id") is not None
    }
    if len(accepted) < 20:
        raise ValueError(f"pilot requires 20 distinct completed schema-valid tickets; got {len(accepted)}")


async def _allow_all(_model: str) -> dict:
    return {"state": "available"}


async def _readiness(model: str) -> dict:
    base = os.environ.get("ORCHESTRA_URL", "http://127.0.0.1:8888").rstrip("/")
    url = f"{base}/api/usage/readiness?{urllib.parse.urlencode({'model': model})}"
    headers = {}
    token = os.environ.get("INTERNAL_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def request() -> dict:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=12) as response:
                row = json.loads(response.read())
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return {"state": "unknown"}
        return row if isinstance(row, dict) else {"state": "unknown"}

    return await asyncio.to_thread(request)


async def _await_despite_cancellation(task: asyncio.Task) -> tuple[Any, int]:
    cancellations = 0
    current = asyncio.current_task()
    while True:
        try:
            return await asyncio.shield(task), cancellations
        except asyncio.CancelledError:
            cancellations += 1
            if current is not None:
                current.uncancel()


def _mem_available_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _current_branch(repository: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repository, capture_output=True, text=True,
    )
    branch = result.stdout.strip()
    if result.returncode != 0 or not branch:
        detail = result.stderr.strip() or result.stdout.strip() or "detached HEAD"
        raise RuntimeError(f"cannot resolve workflow workspace base branch: {detail}")
    return branch


_WORKSPACE_PRIVATE_TOPLEVEL = frozenset({
    ".git", ".env", ".mcp.json", ".claude", ".codex", ".wf-mcp.json",
    ".pytest_cache", "__pycache__",
})


def _workspace_files(worktree: Path) -> set[str]:
    files: set[str] = set()
    for root, dirs, names in os.walk(worktree):
        relative_root = Path(root).relative_to(worktree)
        dirs[:] = [
            name for name in dirs
            if name not in _WORKSPACE_PRIVATE_TOPLEVEL
        ]
        for name in names:
            relative = relative_root / name
            if any(part in _WORKSPACE_PRIVATE_TOPLEVEL for part in relative.parts):
                continue
            files.add(str(relative))
    return files


def _snapshot_worktree(
    worktree: Path, destination: Path, initial_head: str, baseline_files: set[str],
) -> None:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "-z", initial_head, "--"],
        cwd=worktree, check=True, capture_output=True,
    ).stdout.split(b"\0")
    local = subprocess.run(
        ["git", "ls-files", "-m", "-o", "--exclude-standard", "-z"],
        cwd=worktree, check=True, capture_output=True,
    ).stdout.split(b"\0")
    after_files = _workspace_files(worktree)
    names = sorted(
        {os.fsdecode(item) for item in changed + local if item}
        | (after_files - baseline_files)
    )
    copied: list[str] = []
    deleted: list[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    root = worktree.resolve()
    for name in names:
        source = (worktree / name).resolve()
        if source != root and root not in source.parents:
            raise ValueError(f"workspace output escapes worktree: {name}")
        if not source.is_file():
            deleted.append(name)
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(name)
    manifest = destination / "workspace.json"
    manifest.write_text(json.dumps({"copied": copied, "deleted": deleted}, ensure_ascii=False))


def _reset_prepared_worktree(repository: Path, prepared: Any) -> None:
    from app.workspace import _reset_worktree_to_ref, repo_mutation_lock

    with repo_mutation_lock(repository):
        _reset_worktree_to_ref(
            prepared.path, prepared.initial_head, str(repository)
        )


def _prepare_workspace_sync(
    repository: Path, name: str, base_branch: str,
) -> tuple[Any, set[str]]:
    from app.workspace import create_worktree, discard_prepared_worktree

    prepared = create_worktree(str(repository), name, "", base_branch)
    try:
        return prepared, _workspace_files(Path(prepared.path))
    except BaseException:
        discard_prepared_worktree(str(repository), prepared)
        raise


def _cleanup_workspace_sync(
    repository: Path,
    prepared: Any,
    archive: Path,
    baseline_files: set[str],
) -> None:
    from app.workspace import discard_prepared_worktree

    snapshot_error = None
    try:
        _snapshot_worktree(
            Path(prepared.path), archive, prepared.initial_head, baseline_files
        )
    except Exception as error:
        snapshot_error = error
    _reset_prepared_worktree(repository, prepared)
    discard_prepared_worktree(str(repository), prepared)
    if snapshot_error is not None:
        raise snapshot_error


class WorkflowEngine:
    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        *,
        budget_usd: float,
        workflow_path: Path | None = None,
        resume_command_override: str = "",
        max_calls: int = 100,
        max_concurrency: int | None = None,
        adapter: Adapter | None = None,
        usage_writer: UsageWriter | None = None,
        readiness_checker: ReadinessChecker | None = None,
        scope: str | None = None,
        task_id: str | None = None,
        workspace_repo: Path | None = None,
        workspace_base_branch: str = "",
        pipeline_name: str = "default",
        default_modules: Iterable[str] = DEFAULT_WORKFLOW_MODULES,
    ):
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must contain only letters, digits, dot, underscore, or dash")
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.steps_dir = self.run_dir / "steps"
        self.steps_dir.mkdir(exist_ok=True)
        self.workflow_path = Path(workflow_path) if workflow_path is not None else None
        self.resume_command_override = resume_command_override.strip()
        self.journal = Journal(self.run_dir / "journal.jsonl")
        self.adapter = adapter or run_adapter
        self.usage_writer = usage_writer if usage_writer is not None else (
            persist_turn_usage if adapter is None else None
        )
        self.readiness_checker = readiness_checker or (_readiness if adapter is None else _allow_all)
        concurrency = max_concurrency or int(os.environ.get("WF_MAX_CONCURRENCY", "3"))
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self._codex_semaphore = asyncio.Semaphore(2)
        self._state_lock = asyncio.Lock()
        self.budget = Budget(budget_usd, max_calls)
        self.scope = scope if scope is not None else os.environ.get("ORCHESTRA_SCOPE", "")
        self.task_id = task_id if task_id is not None else os.environ.get("ORCHESTRA_TASK_ID", "")
        if workspace_repo is None and adapter is None:
            from app.workspace import repo_root

            self.workspace_repo = Path(repo_root(str(ROOT))).resolve()
        else:
            self.workspace_repo = (
                Path(workspace_repo).resolve() if workspace_repo is not None else None
            )
        self.workspace_base_branch = workspace_base_branch or (
            _current_branch(
                ROOT if workspace_repo is None and adapter is None else self.workspace_repo
            )
            if self.workspace_repo is not None
            else ""
        )
        self.pipeline_name = pipeline_name
        self.default_modules = tuple(default_modules)
        self.session_id = f"wf:{run_id}"
        self.partial_reason = ""
        self._occurrences: dict[str, int] = {}
        self._completed: dict[str, WorkflowValue | None] = {}
        self._completed_reason: dict[str, str] = {}
        self._unknown_calls: set[str] = set()
        self._retry_state: dict[str, tuple[int, str]] = {}
        self._step_records: dict[str, dict] = {}
        self.result: Any = None
        self._restore()

    def _restore(self) -> None:
        dispatched_calls: set[str] = set()
        last_state: dict[str, str] = {}
        for row in self.journal.load():
            event = row.get("event")
            if event == "dispatched":
                call_key = str(row.get("call_key") or "")
                dispatched_calls.add(call_key)
                last_state[call_key] = "dispatched"
                self.budget.dispatched_calls += 1
            elif event == "attempt_finished":
                call_key = str(row.get("call_key") or "")
                last_state[call_key] = "attempt_finished"
                self.budget.spent_usd += float(row.get("cost_usd") or 0)
            elif event == "schema_invalid":
                call_key = str(row.get("call_key") or "")
                last_state[call_key] = "schema_invalid"
                self._retry_state[call_key] = (
                    int(row.get("next_attempt") or 0),
                    str(row.get("error") or "schema validation failed"),
                )
            elif event == "completed":
                call_key = str(row.get("call_key") or "")
                last_state[call_key] = "completed"
                value = row.get("value")
                self._completed[call_key] = (
                    WorkflowValue.from_record(value) if isinstance(value, dict) else None
                )
                self._completed_reason[call_key] = str(row.get("reason") or "completed")
                self._step_records[call_key] = row
        self._unknown_calls = {
            call_key
            for call_key in dispatched_calls
            if call_key not in self._completed and last_state.get(call_key) != "schema_invalid"
        }
        if self._unknown_calls:
            self.budget.spent_usd = max(self.budget.spent_usd, self.budget.maximum_usd)

    async def _call_key(self, payload: dict) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        async with self._state_lock:
            occurrence = self._occurrences.get(digest, 0)
            self._occurrences[digest] = occurrence + 1
        return f"{digest}:{occurrence}"

    @staticmethod
    def _candidates(model: str | Iterable[str] | None, purpose: str, escalate: bool, hard: bool) -> list[str]:
        if isinstance(model, str):
            candidates = [model]
        elif model is not None:
            candidates = [str(item) for item in model]
        elif hard:
            candidates = ["opus"]
        elif purpose == "verify" or escalate:
            candidates = ["sol"]
        else:
            candidates = ["luna"]
        if not candidates or any(not item.strip() for item in candidates):
            raise ValueError("model candidates must be non-empty strings")
        from app.models import resolve_model

        return [resolve_model(item) for item in candidates]

    async def agent(
        self,
        prompt: str,
        *,
        model: str | Iterable[str] | None = None,
        schema: dict | None = None,
        timeout: float = 300,
        loss_tolerant: bool = False,
        purpose: str = "work",
        inputs: Iterable[WorkflowValue] = (),
        escalate: bool = False,
        hard: bool = False,
        label: str = "",
        tools: str = "all",
        network: bool = True,
        mcp: bool = True,
        modules: Iterable[str] | None = None,
        capability_reason: str = "",
    ) -> WorkflowValue | None:
        if purpose not in {"work", "verify", "synthesis"}:
            raise ValueError("purpose must be work, verify, or synthesis")
        if tools not in {"all", "read"}:
            raise ValueError("tools must be 'all' or 'read'")
        downgraded = tools != "all" or not network or not mcp
        if downgraded and not capability_reason.strip():
            raise ValueError("restricted capabilities require capability_reason")
        module_names = tuple(self.default_modules if modules is None else modules)
        if any(not isinstance(name, str) or not name for name in module_names):
            raise ValueError("modules must contain non-empty names")
        from app.pipeline import build_prompt_modules

        system_prompt = build_prompt_modules(self.pipeline_name, module_names)
        effective_mcp = bool(mcp and tools == "all" and network)
        input_values = list(inputs)
        if any(not isinstance(item, WorkflowValue) for item in input_values):
            raise TypeError("inputs must contain WorkflowValue objects")
        free_sources = frozenset().union(*(item.free_sources for item in input_values))
        verified_sources = frozenset().union(
            *(item.verified_sources for item in input_values)
        )
        if purpose == "synthesis" and not free_sources.issubset(verified_sources):
            missing = sorted(free_sources - verified_sources)
            raise ValueError(f"free-lane output requires a verify step before synthesis: {missing}")
        candidates = self._candidates(model, purpose, escalate, hard)
        from app.models import backend_for_model

        if any(backend_for_model(item) == "harness" for item in candidates) and not loss_tolerant:
            raise ValueError(":free harness calls require loss_tolerant=True")
        if purpose == "verify" and free_sources and any(
            backend_for_model(item) == "harness" for item in candidates
        ):
            raise ValueError("free-lane output requires a non-free verify step")
        rendered = str(prompt)
        if input_values:
            rendered += "\n\nStructured inputs:\n" + json.dumps(
                [item.data for item in input_values], ensure_ascii=False, sort_keys=True
            )
        call_key = await self._call_key({
            "prompt": rendered,
            "models": candidates,
            "schema": schema,
            "purpose": purpose,
            "loss_tolerant": loss_tolerant,
            "label": label,
            "tools": tools,
            "network": bool(network),
            "mcp": effective_mcp,
            "modules": module_names,
            "capability_reason": capability_reason.strip(),
        })
        if call_key in self._completed:
            if self._completed[call_key] is None:
                self.partial_reason = self.partial_reason or self._completed_reason[call_key]
            return self._completed[call_key]
        if call_key in self._unknown_calls:
            self.partial_reason = self.partial_reason or "outcome_unknown"
            self.journal.append({
                "event": "skipped",
                "call_key": call_key,
                "reason": "outcome_unknown",
            })
            return None

        async with self._state_lock:
            if self.budget.exhausted():
                self.partial_reason = "budget"
                self.journal.append({"event": "skipped", "call_key": call_key, "reason": "budget"})
                return None

        selected = ""
        for candidate in candidates:
            decision = await self.readiness_checker(candidate)
            if decision.get("state") != "blocked":
                selected = candidate
                break
        if not selected:
            self.partial_reason = self.partial_reason or "quota"
            self.journal.append({"event": "skipped", "call_key": call_key, "reason": "quota"})
            return None

        runtime = backend_for_model(selected)
        minimum_memory = int(os.environ.get("WF_MIN_MEM_AVAILABLE_BYTES", str(2 * 1024**3)))
        available_memory = _mem_available_bytes()
        if runtime in {"codex", "claude"} and (
            available_memory is not None and available_memory < minimum_memory
        ):
            self.partial_reason = self.partial_reason or "memory"
            self.journal.append({
                "event": "skipped",
                "call_key": call_key,
                "reason": "memory",
                "mem_available_bytes": available_memory,
            })
            return None
        scratch = self.run_dir / "calls" / call_key.replace(":", "-")
        scratch.mkdir(parents=True, exist_ok=True)
        current_prompt = rendered
        total_cost = 0.0
        final_data: Any = None
        result: AdapterResult | None = None
        workspace_path = ""
        start_attempt, schema_error = self._retry_state.get(call_key, (0, ""))
        if schema_error and schema is not None:
            current_prompt = _schema_retry_prompt(rendered, schema_error, schema)
        if schema_error and start_attempt >= 3:
            self.partial_reason = self.partial_reason or "schema"
            self._finish(call_key, None, reason="schema")
            return None
        deferred_budget = False
        for attempt in range(start_attempt, 3):
            async with self._state_lock:
                if self.budget.exhausted():
                    self.partial_reason = "budget"
                    deferred_budget = True
                    self.journal.append({
                        "event": "retry_deferred",
                        "call_key": call_key,
                        "reason": "budget",
                        "next_attempt": attempt,
                    })
                    break
                self.budget.dispatched_calls += 1
            semaphore = self._codex_semaphore if runtime == "codex" else self._semaphore
            event_id = f"wf:{self.run_id}:{call_key}:{attempt + 1}"
            async with self._semaphore:
                if semaphore is self._semaphore:
                    result, workspace_path = await self._run_attempt(
                        current_prompt,
                        model=selected,
                        runtime=runtime,
                        scratch=scratch,
                        timeout=timeout,
                        call_key=call_key,
                        attempt=attempt + 1,
                        event_id=event_id,
                        tools=tools,
                        network=bool(network),
                        mcp=effective_mcp,
                        system_prompt=system_prompt,
                        modules=module_names,
                        capability_reason=capability_reason.strip(),
                    )
                else:
                    async with semaphore:
                        result, workspace_path = await self._run_attempt(
                            current_prompt,
                            model=selected,
                            runtime=runtime,
                            scratch=scratch,
                            timeout=timeout,
                            call_key=call_key,
                            attempt=attempt + 1,
                            event_id=event_id,
                            tools=tools,
                            network=bool(network),
                            mcp=effective_mcp,
                            system_prompt=system_prompt,
                            modules=module_names,
                            capability_reason=capability_reason.strip(),
                        )
            realized = float(result.cost_usd or 0)
            total_cost += realized
            async with self._state_lock:
                self.budget.spent_usd += realized
                self.journal.append({
                    "event": "attempt_finished",
                    "call_key": call_key,
                    "attempt": attempt + 1,
                    "cost_usd": realized,
                    "ok": result.ok,
                    "stop_reason": result.stop_reason,
                })
            if not result.ok:
                break
            if schema is None:
                final_data = result.text
                schema_error = ""
                break
            try:
                final_data = _parse_and_validate(result.text, schema)
                schema_error = ""
                break
            except ValueError as error:
                schema_error = str(error)
                self.journal.append({
                    "event": "schema_invalid",
                    "call_key": call_key,
                    "attempt": attempt + 1,
                    "next_attempt": attempt + 1,
                    "error": schema_error,
                })
                if attempt < 2:
                    current_prompt = _schema_retry_prompt(rendered, schema_error, schema)

        if deferred_budget:
            return None
        if result is None or not result.ok or schema_error:
            reason = "budget" if result is None else ("schema" if schema_error else result.stop_reason)
            if reason == "budget":
                self.partial_reason = "budget"
            else:
                self.partial_reason = self.partial_reason or reason
            self._finish(
                call_key,
                None,
                reason=reason,
                cost_usd=total_cost,
                error=result.error if result is not None else "",
            )
            return None

        own_id = call_key
        output_free = free_sources | ({own_id} if runtime == "harness" else set())
        output_verified = verified_sources | (free_sources if purpose == "verify" else set())
        step_path = self.steps_dir / f"{call_key.replace(':', '-')}.json"
        value = WorkflowValue(
            data=final_data,
            value_id=own_id,
            result_path=str(step_path),
            workspace_path=workspace_path,
            free_sources=frozenset(output_free),
            verified_sources=frozenset(output_verified),
        )
        self._atomic_json(step_path, value.to_record())
        self._finish(
            call_key,
            value,
            reason="completed",
            cost_usd=total_cost,
            model=selected,
            runtime=runtime,
        )
        return value

    async def _run_attempt(
        self,
        prompt: str,
        *,
        model: str,
        runtime: str,
        scratch: Path,
        timeout: float,
        call_key: str,
        attempt: int,
        event_id: str,
        tools: str,
        network: bool,
        mcp: bool,
        system_prompt: str,
        modules: tuple[str, ...],
        capability_reason: str,
    ) -> tuple[AdapterResult, str]:
        prepared = None
        cwd = scratch
        archive = ""
        baseline_files: set[str] = set()
        if tools == "all" and self.workspace_repo is not None:
            name = f"wf-{self.run_id[:24]}-{call_key[:12]}-a{attempt}"
            prepare_task = asyncio.create_task(asyncio.to_thread(
                _prepare_workspace_sync,
                self.workspace_repo,
                name,
                self.workspace_base_branch,
            ))
            try:
                (prepared, baseline_files), cancellations = (
                    await _await_despite_cancellation(prepare_task)
                )
            except BaseException:
                async with self._state_lock:
                    self.budget.dispatched_calls -= 1
                    self.journal.append({
                        "event": "prepare_failed",
                        "call_key": call_key,
                        "attempt": attempt,
                    })
                raise
            if cancellations:
                cleanup_task = asyncio.create_task(asyncio.to_thread(
                    _cleanup_workspace_sync,
                    self.workspace_repo,
                    prepared,
                    self.run_dir / "cancelled-workspaces" / name,
                    baseline_files,
                ))
                await _await_despite_cancellation(cleanup_task)
                async with self._state_lock:
                    self.budget.dispatched_calls -= 1
                    self.journal.append({
                        "event": "prepare_cancelled",
                        "call_key": call_key,
                        "attempt": attempt,
                    })
                raise asyncio.CancelledError
            cwd = Path(prepared.path)
            archive_path = (
                self.run_dir / "workspaces" / call_key.replace(":", "-") / f"attempt-{attempt}"
            )
            archive = str(archive_path)
        async with self._state_lock:
            self.journal.append({
                "event": "dispatched",
                "call_key": call_key,
                "attempt": attempt,
                "model": model,
                "runtime": runtime,
                "tools": tools,
                "network": network,
                "mcp": mcp,
                "modules": list(modules),
                "system_prompt_bytes": len(system_prompt.encode()),
                "capability_reason": capability_reason,
            })
        try:
            result = await self.adapter(
                prompt,
                model=model,
                cwd=cwd,
                timeout=timeout,
                tools=tools,
                network=network,
                mcp=mcp,
                system_prompt=system_prompt,
                state_dir=scratch,
            )
            if self.usage_writer is not None:
                try:
                    self.usage_writer(
                        result=result,
                        event_id=event_id,
                        session_id=self.session_id,
                        scope=self.scope,
                        task_id=self.task_id,
                    )
                except Exception as error:
                    self.journal.append({
                        "event": "accounting_failed",
                        "call_key": call_key,
                        "attempt": attempt,
                        "error": f"{type(error).__name__}: {error}",
                    })
                    raise RuntimeError(f"turn_usage accounting failed: {error}") from error
            return result, archive
        finally:
            if prepared is not None:
                cleanup_task = asyncio.create_task(asyncio.to_thread(
                    _cleanup_workspace_sync,
                    self.workspace_repo,
                    prepared,
                    Path(archive),
                    baseline_files,
                ))
                _, cancellations = await _await_despite_cancellation(cleanup_task)
                if cancellations:
                    raise asyncio.CancelledError

    def _finish(
        self,
        call_key: str,
        value: WorkflowValue | None,
        *,
        reason: str,
        cost_usd: float = 0,
        model: str = "",
        runtime: str = "",
        error: str = "",
    ) -> None:
        row = {
            "event": "completed",
            "call_key": call_key,
            "reason": reason,
            "cost_usd": cost_usd,
            "model": model,
            "runtime": runtime,
            "error": error,
            "value": value.to_record() if value is not None else None,
        }
        self.journal.append(row)
        self._completed[call_key] = value
        self._completed_reason[call_key] = reason
        self._step_records[call_key] = row

    @staticmethod
    def _atomic_json(path: Path, row: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".new")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(row, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    async def parallel(self, jobs: Iterable[Any]) -> list[Any]:
        async def invoke(job: Any) -> Any:
            value = job() if callable(job) else job
            return await value if inspect.isawaitable(value) else value

        return list(await asyncio.gather(*(invoke(job) for job in jobs)))

    async def pipeline(self, items: Iterable[Any], *stages: Callable[[Any], Any]) -> list[Any]:
        current = list(items)
        for stage in stages:
            current = await self.parallel([lambda item=item: stage(item) for item in current])
        return current

    def log(self, message: str) -> None:
        self.journal.append({"event": "log", "message": str(message)})

    def phase(self, name: str) -> None:
        self.journal.append({"event": "phase", "name": str(name)})

    def resume_command(self) -> str:
        if self.resume_command_override:
            return self.resume_command_override
        if self.workflow_path is None:
            workflow = Path("workflow.wf.py")
        else:
            workflow = self.workflow_path
        return shlex.join([
            sys.executable,
            str(ROOT / "scripts" / "wf_run.py"),
            str(workflow),
            "--resume",
            self.run_id,
            "--budget-usd",
            f"{self.budget.maximum_usd:g}",
            "--max-calls",
            str(self.budget.maximum_calls),
        ])

    def write_manifest(self) -> dict:
        resume = self.resume_command()
        manifest = {
            "run_id": self.run_id,
            "complete": not bool(self.partial_reason),
            "partial_reason": self.partial_reason or None,
            "spent_usd": round(self.budget.spent_usd, 9),
            "budget_usd": self.budget.maximum_usd,
            "dispatched_calls": self.budget.dispatched_calls,
            "steps": [
                {
                    "call_key": key,
                    "reason": row.get("reason"),
                    "error": row.get("error") or None,
                    "result_path": (
                        row.get("value", {}).get("result_path")
                        if isinstance(row.get("value"), dict)
                        else None
                    ),
                    "workspace_path": (
                        row.get("value", {}).get("workspace_path")
                        if isinstance(row.get("value"), dict)
                        else None
                    ),
                }
                for key, row in self._step_records.items()
            ],
            "result": _jsonable(self.result),
            "resume_command": resume,
            "wake_message": f"wf_run {self.run_id} interrupted; resume with: {resume}",
        }
        self._atomic_json(self.run_dir / "manifest.json", manifest)
        return manifest

    async def execute(self, workflow_path: Path) -> Any:
        source = workflow_path.read_text(encoding="utf-8")
        flags = ast.PyCF_ALLOW_TOP_LEVEL_AWAIT
        code = compile(source, str(workflow_path), "exec", flags=flags, dont_inherit=True)
        namespace = {
            "__builtins__": __builtins__,
            "agent": self.agent,
            "parallel": self.parallel,
            "pipeline": self.pipeline,
            "log": self.log,
            "phase": self.phase,
            "budget": self.budget,
        }
        pending = eval(code, namespace, namespace)
        if inspect.isawaitable(pending):
            await pending
        self.result = namespace.get("result")
        return self.result


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-id")
    group.add_argument("--resume")
    parser.add_argument("--budget-usd", type=float, required=True)
    parser.add_argument("--max-calls", type=int, default=100)
    parser.add_argument("--max-concurrency", type=int, default=None)
    return parser.parse_args()


async def _main() -> int:
    args = _args()
    run_id = args.resume or args.run_id
    workflow = args.workflow.resolve()
    run_dir = ROOT / "data" / "workflow-runs" / run_id
    engine = WorkflowEngine(
        run_id,
        run_dir,
        budget_usd=args.budget_usd,
        workflow_path=workflow,
        max_calls=args.max_calls,
        max_concurrency=args.max_concurrency,
    )
    resume = engine.resume_command()
    print(f"WF_BG_MESSAGE={json.dumps(f'wf_run {run_id} interrupted; resume with: {resume}')}", flush=True)
    try:
        await engine.execute(workflow)
    except BaseException:
        engine.partial_reason = engine.partial_reason or "error"
        raise
    finally:
        manifest = engine.write_manifest()
        print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
