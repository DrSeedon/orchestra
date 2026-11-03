"""Validate a frozen comparison pack without importing hidden validators or history."""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import PurePosixPath
import re


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def seed_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (candidate.is_absolute() or ".." in candidate.parts or "\\" in path
            or candidate.parts[:1] != ("src",) or len(candidate.parts) < 2
            or any(part.startswith(".") for part in candidate.parts)):
        raise ValueError("evaluation seed path must stay under src/")
    return candidate


def plan(manifest: dict, inputs: dict[str, str], run_order_csv: str) -> list[dict]:
    from app.eval_admission import MAX_CALLS, GENERATED_BUDGET, WALL_SECONDS, validate_conditions
    version = 2 if manifest.get("stage") == "coding" else 1
    if type(manifest.get("version")) is not int or manifest.get("version") != version:
        raise ValueError("unsupported frozen fixture manifest version")
    policy = manifest.get("grant", {})
    expected = {"task_id": manifest.get("task_id"), "billing": "subscription",
        "api_credit_fallback": False, "max_task_invocations": MAX_CALLS,
        "max_generated_output_plus_reasoning_tokens": GENERATED_BUDGET,
        "max_wall_seconds": WALL_SECONDS, "retry_policy": "none", "max_concurrency": 1}
    if any(type(policy.get(key)) is not type(value) or policy.get(key) != value
           for key, value in expected.items()):
        raise ValueError("frozen pack policy differs from approved evaluation limits")
    configs = policy.get("allowed_models_efforts", [])
    repeats = validate_conditions(configs, stage=manifest.get("stage", "legacy"),
        runtime_supported_efforts=manifest.get("runtime_supported_efforts"))
    if (any(not isinstance(row.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", row["id"]) for row in configs)
            or len({row["id"] for row in configs}) != len(configs)):
        raise ValueError("frozen pack model/effort cohort mismatch")
    conditions = {row["id"]: row for row in configs}
    if digest(run_order_csv) != manifest.get("run_order_sha256"):
        raise ValueError("frozen run order hash mismatch")
    fixtures = manifest.get("tasks", [])
    if len(fixtures) != 4 or len({row.get("id") for row in fixtures}) != 4:
        raise ValueError("frozen pack requires four fixtures")
    visible = {}
    required_paths = set()
    for fixture in fixtures:
        fixture_id = fixture["id"]
        if not isinstance(fixture_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", fixture_id):
            raise ValueError("invalid frozen fixture identity")
        hashes = fixture.get("model_input_files", {})
        prompt_path = f"fixtures/{fixture_id}/prompt.md"
        if prompt_path not in hashes:
            raise ValueError("frozen fixture prompt missing")
        seeds = {}
        for path, expected_hash in hashes.items():
            content = inputs.get(path)
            if not isinstance(content, str) or digest(content) != expected_hash:
                raise ValueError(f"frozen model input hash mismatch: {path}")
            required_paths.add(path)
            if path != prompt_path:
                prefix = f"fixtures/{fixture_id}/seed/"
                if not path.startswith(prefix):
                    raise ValueError("only prompt and seed source may be model-visible")
                relative = str(seed_path(path[len(prefix):]))
                seeds[relative] = content
        if not seeds:
            raise ValueError("frozen fixture has no seed source")
        visible[fixture_id] = {"prompt": inputs[prompt_path], "seed_files": seeds}
    if set(inputs) != required_paths:
        raise ValueError("unmanifested/hidden files must not be model-visible")
    controls = manifest.get("fixture_controls", [])
    expected_controls = {(name, label) for name in visible for label in ("base-red", "reference-green")}
    if len(controls) != 8 or {(row.get("fixture"), row.get("control")) for row in controls} != expected_controls:
        raise ValueError("frozen fixture controls missing")
    for control in controls:
        red = control["control"] == "base-red"
        color, returncode = ("RED", 1) if red else ("GREEN", 0)
        if any(control.get(key) != value for key, value in
               {"actual": color, "expected": color, "returncode": returncode, "outcome": "PASS"}.items()):
            raise ValueError("frozen fixture control failed or skipped")
    rows = list(csv.DictReader(io.StringIO(run_order_csv)))
    expected_units = {(fixture, str(repeat), condition) for fixture in visible
                      for repeat in range(1, repeats + 1) for condition in conditions}
    if len(rows) != len(expected_units) or not 0 < len(rows) <= MAX_CALLS:
        raise ValueError("frozen order differs from the bounded task matrix")
    seen, tasks = set(), []
    for index, row in enumerate(rows):
        unit = (row.get("fixture_id"), row.get("repeat"), row.get("condition_id"))
        if unit not in expected_units or unit in seen:
            raise ValueError("duplicate or unexpected frozen task invocation")
        seen.add(unit)
        condition = conditions[row["condition_id"]]
        if (row.get("sequence") != str(index + 1) or row.get("attempt") != "1"
                or row.get("billing") != "subscription"
                or (row.get("model"), row.get("effort")) != (condition["model"], condition["effort"])):
            raise ValueError("frozen task order/condition/billing mismatch")
        tasks.append({**visible[row["fixture_id"]], "model": condition["model"],
            "effort": condition["effort"], "billing": "subscription",
            "task_id": f"{row['fixture_id']}-r{row['repeat']}-{row['condition_id']}",
            "fixture_id": row["fixture_id"], "repeat": int(row["repeat"]),
            "condition_id": row["condition_id"], "label": f"Task {index + 1}"})
    return tasks
