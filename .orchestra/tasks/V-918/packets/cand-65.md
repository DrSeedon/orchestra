# Candidate cand-65

## ORIGIN commit 038f06b7b2 (2026-10-05): V-720: #V-720: add one-call dynamic workflows
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index d4ebe9e1b..f76d0991e 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -2,16 +2,17 @@
 
 Runs as a separate process, communicates with Orchestra via HTTP API.
 Avoids the in-process SDK control_request deadlock (issue #425/#701).
 
 Usage: python -m app.mcp_stdio
 """
 
 import asyncio
+import base64
 import hashlib
 import json
 import logging
 import math
 import os
 import shutil
 import re
 import shlex
@@ -3143,16 +3144,107 @@ async def task_get(par: str, project: str = "") -> str:
     """Get task details. project overrides scope and should come from task_list output."""
     params = {"project": project} if project else ({"scope": SCOPE} if SCOPE else None)
     result = await _api("GET", f"/api/tm/tasks/{par}", params=params)
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     return json.dumps(result, ensure_ascii=False)
 
 
+@mcp.tool()
+async def dynamic_workflow(
+    tasks: list[dict[str, Any]],
+    mode: str,
+    budget_usd: float,
+    max_calls: int,
+    max_concurrency: int,
+    task_id: str,
+    repo: str,
+) -> str:
+    """Run a bounded set of model tasks without a workflow file. Each task has prompt, optional model (defaults to luna), and optional JSON schema. mode is parallel or chain; chain passes each completed result as structured input to the next task. Completion wakes the caller with short answers and result paths."""
+    if mode not in {"parallel", "chain"}:
+        return "Error: mode must be 'parallel' or 'chain'"
+    if not tasks or len(tasks) > 100:
+        return "Error: tasks must contain between 1 and 100 items"
+    if (not isinstance(budget_usd, (int, float)) or isinstance(budget_usd, bool)
+            or not math.isfinite(budget_usd) or budget_usd <= 0):
+        return "Error: budget_usd must be positive"
+    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
+        return "Error: max_calls must be a positive integer"
+    if not isinstance(max_concurrency, int) or isinstance(max_concurrency, bool) or not 1 <= max_concurrency <= 100:
+        return "Error: max_concurrency must be between 1 and 100"
+    if not task_id or not task_id.strip():
+        return "Error: task_id is required"
+    if re.fullmatch(r"[A-Za-z0-9._-]+", task_id) is None:
+        return "Error: task_id may contain only letters, digits, dot, underscore, and dash"
+    repo_path = Path(repo).expanduser().resolve()
+    if not repo_path.is_dir():
+        return f"Error: repository directory not found: {repo_path}"
+
+    from app.models import get_model_flags, resolve_model
+
+    normalized = []
+    for index, task in enumerate(tasks):
+        if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
+            return f"Error: tasks[{index}].prompt must be a non-empty string"
+        row = {"prompt": task["prompt"]}
+        model = task.get("model", "luna")
+        if not isinstance(model, str) or not model.strip():
+            return f"Error: tasks[{index}].model must be a non-empty string"
+        try:
+            model_id = resolve_model(model)
+        except (ValueError, TypeError) as error:
+            return f"Error: tasks[{index}].model: {error}"
+        if model_id in {"gpt-6-astra", "gpt-6-sol", "gpt-5.6-sol"}:
+            return f"Error: model '{model}' is not allowed for dynamic workflows"
+        if not get_model_flags(model_id)["agents"]:
+            return f"Error: model '{model}' is not enabled for agents"
+        row["model"] = model_id
+        schema = task.get("schema")
+        if schema is not None:
+            if not isinstance(schema, dict):
+                return f"Error: tasks[{index}].schema must be a JSON object"
+            row["schema"] = schema
+        normalized.append(row)
+
+    runner_root = Path(__file__).resolve().parents[1]
+    run_id = f"{task_id}-{uuid.uuid4().hex[:12]}"
+    spec = json.dumps({"tasks": normalized, "mode": mode}, ensure_ascii=False, separators=(",", ":"))
+    tasks_b64 = base64.urlsafe_b64encode(spec.encode()).decode()
+    if len(tasks_b64) > 64 * 1024:
+        return "Error: encoded tasks exceed the 64 KiB command limit"
+    command_parts = [
+        "env", f"ORCHESTRA_TASK_ID={task_id}", f"ORCHESTRA_SCOPE={SCOPE}",
+        sys.executable, str(runner_root / "scripts" / "wf_run.py"),
+        "--tasks-b64", tasks_b64, "--run-id", run_id,
+        "--budget-usd", f"{budget_usd:g}", "--max-calls", str(max_calls),
+        "--max-concurrency", str(max_concurrency), "--repo", str(repo_path),
+    ]
+    command = shlex.join(command_parts)
+    manifest_path = runner_root / "data" / "workflow-runs" / run_id / "manifest.json"
+    result = await _api("POST", "/api/bg/jobs", json={
+        "type": "run",
+        "config": {
+            "command": command,
+            "cwd": str(repo_path),
+            "success_file": str(manifest_path),
+            "success_pattern": r'"complete"\s*:\s*true',
+        },
+        "message": f"Dynamic workflow {run_id} ({len(tasks)} tasks, {mode})",
+        "target_name": WORKER_NAME,
+        "target_scope": SCOPE,
+        "timeout_seconds": 3600,
+        "created_by": WORKER_NAME,
+    })
+    if isinstance(result, dict) and result.get("error"):
+        return f"Error: {result['error']}"
+    return (f"Dynamic workflow queued: run_id={run_id}, job_id={result.get('id', '?')}, "
+            f"tasks={len(tasks)}, mode={mode}. The completion message will include answers and result paths.")
+
+
 @mcp.tool()
 async def bg_create(type: str, message: str = "", target: str = "",
                     delay_seconds: int = 0, path: str = "", pattern: str = "",
                     command: str = "", host: str = "", cron_expr: str = "",
                     interval_seconds: int = 60,
                     timeout_seconds: int = 3600) -> str:
     """Create a durable job and wake its target on trigger; survives hibernate. Returns a job receipt, not command completion. Types: run executes command (optional host); timer uses delay_seconds; file watches path for regex pattern; command checks command output for pattern every interval_seconds; ssh streams host command for pattern; cron uses 5-field UTC cron_expr; cron_command runs on cron_expr and wakes for matching completed output; each run is killed after 600 s without a wake (timeout shows only in bg_list last_output). cron types recur, skip missed downtime fires without backfill. target defaults to caller. timeout_seconds defaults to 3600, max 86400; 0 means no expiry only for file/command/ssh/cron/cron_command."""
     config = {}
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index e106a76a9..0c9ea4a6b 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -1,16 +1,17 @@
 #!/usr/bin/env python3
 """Deterministic scripted fan-out hosted by an Orchestra background run job."""
 
 from __future__ import annotations
 
 import argparse
 import asyncio
 import ast
+import base64
 import hashlib
 import inspect
 import json
 import os
 import re
 import shlex
 import shutil
 import subprocess
@@ -207,16 +208,20 @@ def _validate_schema(value: Any, schema: dict, path: str = "$") -> None:
         if "maxLength" in schema and len(value) > int(schema["maxLength"]):
             raise ValueError(f"{path} is longer than {schema['maxLength']}")
 
 
 def _parse_and_validate(raw: str, schema: dict) -> Any:
     try:
         value = json.loads(raw)
     except json.JSONDecodeError as error:
+        if schema.get("type") == "string":
+            value = raw
+            _validate_schema(value, schema)
+            return value
         raise ValueError(f"invalid JSON: {error.msg} at line {error.lineno} column {error.colno}") from error
     _validate_schema(value, schema)
     return value
 
 
 def _schema_retry_prompt(prompt: str, error: str, schema: dict) -> str:
     return (
         prompt
@@ -1032,51 +1037,136 @@ class WorkflowEngine:
             "budget": self.budget,
         }
         pending = eval(code, namespace, namespace)
         if inspect.isawaitable(pending):
             await pending
         self.result = namespace.get("result")
         return self.result
 
+    async def execute_tasks(self, spec: dict[str, Any]) -> Any:
+        tasks = spec["tasks"]
+        mode = spec["mode"]
+
+        async def run_task(task: dict[str, Any], prior: WorkflowValue | None = None):
+            inputs = [prior] if prior is not None else []
+            return await self.agent(
+                task["prompt"], model=task.get("model", "luna"),
+                schema=task.get("schema"), inputs=inputs,
+            )
+
+        if mode == "parallel":
+            self.result = await self.parallel([
+                lambda task=task: run_task(task) for task in tasks
+            ])
+        elif mode == "chain":
+            results = []
+            prior = None
+            for task in tasks:
+                prior = await run_task(task, prior)
+                results.append(prior)
+                if prior is None:
+                    break
+            self.result = results
+        else:
+            raise ValueError("mode must be 'parallel' or 'chain'")
+        return self.result
+
 
 def _args() -> argparse.Namespace:
     parser = argparse.ArgumentParser(description=__doc__)
-    parser.add_argument("workflow", type=Path)
+    parser.add_argument("workflow", type=Path, nargs="?")
     group = parser.add_mutually_exclusive_group(required=True)
     group.add_argument("--run-id")
     group.add_argument("--resume")
     parser.add_argument("--budget-usd", type=float, required=True)
     parser.add_argument("--max-calls", type=int, default=100)
     parser.add_argument("--max-concurrency", type=int, default=None)
     parser.add_argument("--repo", type=Path, help="Target repository for isolated writable calls")
+    parser.add_argument("--tasks-b64", help="Base64-encoded declarative tasks; avoids a workflow file")
     return parser.parse_args()
 
 
 async def _main() -> int:
     args = _args()
     run_id = args.resume or args.run_id
-    workflow = args.workflow.resolve()
+    if bool(args.workflow) == bool(args.tasks_b64):
+        raise ValueError("provide exactly one of workflow or --tasks-b64")
+    workflow = args.workflow.resolve() if args.workflow else None
+    spec = None
+    if args.tasks_b64:
+        spec = json.loads(base64.urlsafe_b64decode(args.tasks_b64.encode()).decode())
     run_dir = ROOT / "data" / "workflow-runs" / run_id
+    encoded_spec = args.tasks_b64 or ""
+    command_parts = [
+        "env", f"ORCHESTRA_TASK_ID={os.environ.get('ORCHESTRA_TASK_ID', '')}",
+        f"ORCHESTRA_SCOPE={os.environ.get('ORCHESTRA_SCOPE', '')}",
+        sys.executable, str(ROOT / "scripts" / "wf_run.py"),
+        "--tasks-b64", encoded_spec,
+        "--budget-usd", f"{args.budget_usd:g}",
+        "--max-calls", str(args.max_calls),
+        "--max-concurrency", str(args.max_concurrency or 3),
+    ] if spec is not None else []
+    if args.repo:
+        command_parts.extend(["--repo", str(args.repo.resolve())])
+    if spec is not None:
+        command_parts.extend(["--resume", run_id])
+    command = shlex.join(command_parts) if command_parts else ""
     engine = WorkflowEngine(
         run_id,
         run_dir,
         budget_usd=args.budget_usd,
         workflow_path=workflow,
         max_calls=args.max_calls,
         max_concurrency=args.max_concurrency,
         workspace_repo=args.repo,
+        resume_command_override=command,
     )
     resume = engine.resume_command()
     print(f"WF_BG_MESSAGE={json.dumps(f'wf_run {run_id} interrupted; resume with: {resume}')}", flush=True)
     try:
-        await engine.execute(workflow)
+        if spec is None:
+            await engine.execute(workflow)
+        else:
+            await engine.execute_tasks(spec)
     except BaseException:
         engine.partial_reason = engine.partial_reason or "error"
         raise
     finally:
         manifest = engine.write_manifest()
         print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), flush=True)
+        if spec is not None:
+            print(_notification_summary(manifest), flush=True)
     return 0
 
 
+def _notification_summary(manifest: dict) -> str:
+    steps = manifest.get("steps", [])
+    results = manifest.get("result") or []
+    successful = sum(step.get("reason") == "completed" for step in steps)
+    total = max(len(steps), len(results))
+    lines = [
+        f"WORKFLOW_SUMMARY run={manifest.get('run_id')} "
+        f"successful={successful}/{total} "
+        f"complete={str(bool(manifest.get('complete'))).lower()} "
+        f"manifest={ROOT / 'data' / 'workflow-runs' / str(manifest.get('run_id')) / 'manifest.json'}"
+    ]
+    omitted = 0
+    for index, value in enumerate(results):
+        data = value.get("data") if isinstance(value, dict) else None
+        path = value.get("result_path") if isinstance(value, dict) else None
+        label = f"{index + 1}. {path or 'no result path'}"
+        if isinstance(data, str) and data:
+            answer = " ".join(data.split())
+            label = f"{index + 1}. {answer[:120]}"
+        if sum(map(len, lines)) + len(label) + len(lines) * 1 > 2400:
+            omitted = len(results) - index
+            break
+        lines.append(label)
+    if manifest.get("partial_reason"):
+        lines.append(f"partial_reason={manifest['partial_reason']}")
+    if omitted:
+        lines.append(f"{omitted} more results in manifest")
+    return "\n".join(lines)
+
+
 if __name__ == "__main__":
     raise SystemExit(asyncio.run(_main()))
diff --git a/tests/test_dynamic_workflows.py b/tests/test_dynamic_workflows.py
index 9702e12d1..5660c12a8 100644
--- a/tests/test_dynamic_workflows.py
+++ b/tests/test_dynamic_workflows.py
@@ -1,10 +1,11 @@
 """Prevent lost workflow routing, wrong-project edits and obsolete MCP dispatch."""
 import asyncio
+import base64
 import json
 import shlex
 import sys
 from pathlib import Path
 
 import pytest
 
 from app import mcp_stdio, pipeline
@@ -67,8 +68,129 @@ async def test_cli_parallel_uses_target_repository_and_resume_preserves_it(tmp_p
     assert await wf_run._main() == 0
     manifest = json.loads((runner / 'data/workflow-runs/target-check/manifest.json').read_text())
     assert manifest['complete'] and len(manifest['steps']) == 2
     assert len(set(arrived)) == 2
     assert all(Path(step['workspace_path'], 'output.txt').is_file() for step in manifest['steps'])
     assert not (repo / 'output.txt').exists()
     resume = shlex.split(manifest['resume_command'])
     assert resume[resume.index('--repo') + 1] == str(repo)
+
+
+@pytest.mark.asyncio
+async def test_dynamic_workflow_tool_builds_durable_run_and_manifest_delivery(tmp_path, monkeypatch):
+    captured = {}
+
+    async def fake_api(method, path, **kwargs):
+        captured.update(method=method, path=path, body=kwargs['json'])
+        return {'id': 'bg-test', 'status': 'active'}
+
+    monkeypatch.setattr(mcp_stdio, '_api', fake_api)
+    monkeypatch.setattr(mcp_stdio, 'SCOPE', 'test-scope')
+    monkeypatch.setattr(mcp_stdio, 'WORKER_NAME', 'test-orchestrator')
+    response = await mcp_stdio.dynamic_workflow(
+        tasks=[{'prompt': 'first', 'schema': {'type': 'object'}}, {'prompt': 'second'}],
+        mode='parallel', budget_usd=1, max_calls=2, max_concurrency=2,
+        task_id='V-720', repo=str(tmp_path),
+    )
+    assert 'queued' in response
+    body = captured['body']
+    assert captured['method'] == 'POST' and captured['path'] == '/api/bg/jobs'
+    assert body['type'] == 'run'
+    assert body['target_name'] == 'test-orchestrator'
+    assert body['target_scope'] == 'test-scope'
+    assert body['config']['cwd'] == str(tmp_path.resolve())
+    assert body['config']['success_file'].endswith('/manifest.json')
+    assert body['config']['success_pattern'] == r'"complete"\s*:\s*true'
+    args = shlex.split(body['config']['command'])
+    assert args[:3] == ['env', 'ORCHESTRA_TASK_ID=V-720', 'ORCHESTRA_SCOPE=test-scope']
+    assert '--tasks-b64' in args and '--run-id' in args and '--repo' in args
+    spec = json.loads(base64.urlsafe_b64decode(args[args.index('--tasks-b64') + 1]))
+    assert spec == {
+        'tasks': [
+            {'prompt': 'first', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}},
+            {'prompt': 'second', 'model': 'gpt-6-luna'},
+        ],
+        'mode': 'parallel',
+    }
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize('model', ['astra', 'sol', 'gpt-5.6-sol'])
+async def test_dynamic_workflow_rejects_platform_blocked_models(model, monkeypatch):
+    async def unexpected_api(*_args, **_kwargs):
+        pytest.fail('blocked models must not create a background job')
+
+    monkeypatch.setattr(mcp_stdio, '_api', unexpected_api)
+    response = await mcp_stdio.dynamic_workflow(
+        tasks=[{'prompt': 'work', 'model': model}], mode='parallel',
+        budget_usd=1, max_calls=1, max_concurrency=1,
+        task_id='V-720', repo=str(Path.cwd()),
+    )
+    assert 'not allowed' in response
+
+
+@pytest.mark.asyncio
+async def test_inline_workflow_run_writes_manifest_and_completion_summary(tmp_path, monkeypatch, capsys):
+    from scripts.wf_adapters import AdapterResult, Usage
+
+    repo = _git_repo(tmp_path / 'target')
+    runner = tmp_path / 'runner'
+    runner.mkdir()
+    monkeypatch.setattr(wf_run, 'ROOT', runner)
+    monkeypatch.setattr(sys, 'argv', [
+        'wf_run.py', '--tasks-b64', base64.urlsafe_b64encode(json.dumps({
+            'tasks': [{'prompt': 'one'}, {'prompt': 'two'}], 'mode': 'parallel',
+        }).encode()).decode(), '--repo', str(repo), '--run-id', 'inline-test',
+        '--budget-usd', '1', '--max-calls', '2', '--max-concurrency', '2',
+    ])
+    arrived = []
+    both = asyncio.Event()
+
+    async def adapter(prompt, **_kwargs):
+        arrived.append(prompt)
+        if len(arrived) == 2:
+            both.set()
+        await asyncio.wait_for(both.wait(), 5)
+        return AdapterResult(
+            text=f'answer {prompt}', runtime='codex', model='gpt-6-luna', ok=True,
+            stop_reason='end_turn', cost_usd=0.01, usage=Usage(input_tokens=1, output_tokens=1),
+        )
+
+    async def readiness(_model):
+        return {'state': 'available'}
+
+    monkeypatch.setattr(wf_run, 'run_adapter', adapter)
+    monkeypatch.setattr(wf_run, '_readiness', readiness)
+    monkeypatch.setattr(wf_run, 'persist_turn_usage', lambda **_kwargs: True)
+    assert await wf_run._main() == 0
+    output = capsys.readouterr().out
+    manifest = json.loads((runner / 'data/workflow-runs/inline-test/manifest.json').read_text())
+    assert manifest['complete'] and len(manifest['steps']) == 2
+    assert 'WORKFLOW_SUMMARY run=inline-test successful=2/2 complete=true' in output
+    assert 'answer one' in output and 'answer two' in output
+    resume = shlex.split(manifest['resume_command'])
+    assert '--tasks-b64' in resume and '--resume' in resume
+
+
+@pytest.mark.asyncio
+async def test_inline_chain_passes_each_result_as_structured_input(tmp_path):
+    prompts = []
+
+    async def adapter(prompt, **_kwargs):
+        prompts.append(prompt)
+        return _result(f"result-{len(prompts)}")
+
+    async def readiness(_model):
+        return {'state': 'available'}
+
+    engine = wf_run.WorkflowEngine(
+        'chain-check', tmp_path, budget_usd=1, max_calls=2,
+        adapter=adapter, usage_writer=None, readiness_checker=readiness,
+        default_modules=(),
+    )
+    result = await engine.execute_tasks({
+        'mode': 'chain',
+        'tasks': [{'prompt': 'first'}, {'prompt': 'second'}],
+    })
+    assert [item.data for item in result] == ['result-1', 'result-2']
+    assert prompts[0] == 'first'
+    assert prompts[1].startswith('second\n\nStructured inputs:\n["result-1"]')
diff --git a/tests/test_wf_run.py b/tests/test_wf_run.py
index 3aa2dcce6..9839ca6fc 100644
--- a/tests/test_wf_run.py
+++ b/tests/test_wf_run.py
@@ -7,22 +7,28 @@ import pytest
 
 from scripts.wf_adapters import (
     AdapterResult,
     Usage,
     parse_claude_output,
     parse_codex_output,
     persist_turn_usage,
 )
-from scripts.wf_run import WorkflowEngine, validate_pilot_manifest
+from scripts.wf_run import WorkflowEngine, _parse_and_validate, validate_pilot_manifest
 
 
 FIXTURES = Path(__file__).parent / "fixtures" / "wf"
 
 
+def test_string_schema_accepts_plain_text_and_json_string():
+    schema = {"type": "string"}
+    assert _parse_and_validate("answer without quotes\n", schema) == "answer without quotes\n"
+    assert _parse_and_validate('"quoted JSON string"', schema) == "quoted JSON string"
+
+
 def _git_repo(path: Path) -> Path:
     path.mkdir()
     subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
     subprocess.run(["git", "config", "user.email", "wf@example.invalid"], cwd=path, check=True)
     subprocess.run(["git", "config", "user.name", "WF Test"], cwd=path, check=True)
     (path / "seed.txt").write_text("seed\n")
     subprocess.run(["git", "add", "seed.txt"], cwd=path, check=True)
     subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)


## LATER FIX 532c73f620 (11.9 days later): V-916: #V-916: fix workflow schema, identity, and resume races
lines of origin it changed/deleted: 11
(code only, capped 400 lines)

V-916: #V-916: fix workflow schema, identity, and resume races

Orchestra-Operation: f8bf4dd7-0b63-4535-ba68-7174a99677cb


diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 1e98ff5cd..341948147 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -3257,47 +3257,60 @@ async def dynamic_workflow(
             default_billing = stage.get("billing", "subscription")
             if "tasks" in stage:
                 if "prompt" in stage or "items" in stage:
                     return f"Error: stages[{stage_index}] must use either tasks or prompt and items"
                 stage_tasks = stage["tasks"]
                 if not isinstance(stage_tasks, list) or not stage_tasks:
                     return f"Error: stages[{stage_index}].tasks must be a non-empty array"
                 task_count = len(stage_tasks)
+                stage_tasks = [(task, None, None) for task in stage_tasks]
             elif "prompt" in stage and "items" in stage:
                 template = stage["prompt"]
                 items = stage["items"]
                 if not isinstance(template, str) or "{item}" not in template:
                     return f"Error: stages[{stage_index}].prompt must contain '{{item}}'"
                 if not isinstance(items, list) or not items:
                     return f"Error: stages[{stage_index}].items must be a non-empty array"
                 task_count = len(items)
                 stage_tasks = (
-                    {"prompt": template.replace(
-                        "{item}", item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
-                    )}
-                    for item in items
+                    (
+                        {"prompt": template.replace(
+                            "{item}", item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
+                        )},
+                        item,
+                        task_index,
+                    )
+                    for task_index, item in enumerate(items)
                 )
             else:
                 return f"Error: stages[{stage_index}] needs tasks or prompt and items"
             if total_tasks + task_count > 1000:
                 return "Error: expanded workflow exceeds 1,000 tasks"
             normalized_stage = []
-            for task_index, task in enumerate(stage_tasks):
+            for task_index, (task, item, item_index) in enumerate(stage_tasks):
                 if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
                     return f"Error: stages[{stage_index}].tasks[{task_index}].prompt must be a non-empty string"
                 normalized, error = _normalize_dynamic_task(
                     task, default_model=default_model,
                     default_schema=default_schema,
                     default_billing=default_billing,
                     label=f"stages[{stage_index}].tasks[{task_index}]",
                 )
                 if error:
                     return f"Error: {error}"
                 normalized["label"] = f"Stage {stage_index + 1} · Task {task_index + 1}"
+                normalized["task_id"] = str(
+                    task.get("task_id") or task.get("id")
+                    or f"stage-{stage_index + 1}-task-{task_index + 1}"
+                )
+                if item_index is not None:
+                    normalized["task_id"] = f"stage-{stage_index + 1}-item-{item_index + 1}"
+                    normalized["item"] = item
+                    normalized["item_index"] = item_index
                 normalized_stage.append(normalized)
                 spec_payload_size += len(
                     json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                 )
                 if spec_payload_size > 1024 * 1024:
                     return "Error: workflow specification exceeds 1 MiB"
             expanded_stages.append({"tasks": normalized_stage})
             total_tasks += task_count
@@ -3310,16 +3323,19 @@ async def dynamic_workflow(
         normalized = []
         for index, task in enumerate(tasks):
             if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
                 return f"Error: tasks[{index}].prompt must be a non-empty string"
             row, error = _normalize_dynamic_task(task, label=f"tasks[{index}]")
             if error:
                 return f"Error: {error}"
             row["label"] = f"Task {index + 1}"
+            row["task_id"] = str(
+                task.get("task_id") or task.get("id") or f"task-{index + 1}"
+            )
             normalized.append(row)
         spec_payload = {"tasks": normalized, "mode": mode}
     if (not isinstance(budget_usd, (int, float)) or isinstance(budget_usd, bool)
             or not math.isfinite(budget_usd) or budget_usd <= 0):
         return "Error: budget_usd must be positive"
     if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
         return "Error: max_calls must be a positive integer"
     if not isinstance(max_concurrency, int) or isinstance(max_concurrency, bool) or not 1 <= max_concurrency <= 100:
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index 352da7f85..4c4e8ec0f 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -2,16 +2,17 @@
 """Deterministic scripted fan-out hosted by an Orchestra background run job."""
 
 from __future__ import annotations
 
 import argparse
 import asyncio
 import ast
 import base64
+import fcntl
 import hashlib
 import inspect
 import json
 import os
 import re
 import shlex
 import shutil
 import subprocess
@@ -113,16 +114,74 @@ class WorkflowValue:
             ),
         )
 
 
 class WorkspacePreparationError(RuntimeError):
     pass
 
 
+class WorkflowRunAlreadyActive(RuntimeError):
+    pass
+
+
+class WorkflowRunLock:
+    def __init__(self, path: Path):
+        self.path = path
+        self.fd: int | None = None
+
+    def __enter__(self) -> "WorkflowRunLock":
+        self.path.parent.mkdir(parents=True, exist_ok=True)
+        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
+        try:
+            try:
+                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
+            except BlockingIOError:
+                os.lseek(fd, 0, os.SEEK_SET)
+                owner = os.read(fd, 64).decode("ascii", errors="ignore").strip()
+                if owner.isdigit():
+                    raise WorkflowRunAlreadyActive(
+                        f"workflow run already active (pid {owner})"
+                    )
+                # The owner may have acquired the lock but not yet published its PID.
+                fcntl.flock(fd, fcntl.LOCK_EX)
+            os.ftruncate(fd, 0)
+            os.write(fd, str(os.getpid()).encode("ascii"))
+            os.fsync(fd)
+            self.fd = fd
+            return self
+        except BaseException:
+            os.close(fd)
+            raise
+
+    def __exit__(self, exc_type, exc, traceback) -> None:
+        if self.fd is not None:
+            fcntl.flock(self.fd, fcntl.LOCK_UN)
+            os.close(self.fd)
+            self.fd = None
+
+
+def _task_result_record(
+    task: dict[str, Any], result: WorkflowValue | None, *, task_id: str,
+    task_index: int, stage_index: int | None = None,
+) -> dict[str, Any]:
+    record: dict[str, Any] = {
+        "task_id": str(task.get("task_id") or task.get("id") or task_id),
+        "task_index": task_index,
+        "result": result,
+    }
+    if stage_index is not None:
+        record["stage_index"] = stage_index
+    if "item" in task:
+        record["item"] = task["item"]
+    if "item_index" in task:
+        record["item_index"] = task["item_index"]
+    return record
+
+
 class Budget:
     def __init__(self, maximum_usd: float, maximum_calls: int):
         if maximum_usd < 0:
             raise ValueError("budget_usd must be non-negative")
         if maximum_calls < 1:
             raise ValueError("max_calls must be positive")
         self.maximum_usd = float(maximum_usd)
         self.maximum_calls = int(maximum_calls)
@@ -219,25 +278,70 @@ def _validate_schema(value: Any, schema: dict, path: str = "$") -> None:
         if "maxLength" in schema and len(value) > int(schema["maxLength"]):
             raise ValueError(f"{path} is longer than {schema['maxLength']}")
 
 
 def _parse_and_validate(raw: str, schema: dict) -> Any:
     try:
         value = json.loads(raw)
     except json.JSONDecodeError as error:
-        if schema.get("type") == "string":
+        wrapped = _extract_wrapped_json(raw)
+        if wrapped is not None:
+            try:
+                value = json.loads(wrapped)
+            except json.JSONDecodeError as wrapped_error:
+                if schema.get("type") != "string":
+                    raise ValueError(
+                        f"invalid JSON: {wrapped_error.msg} at line "
+                        f"{wrapped_error.lineno} column {wrapped_error.colno}"
+                    ) from wrapped_error
+                value = raw
+        elif schema.get("type") == "string":
             value = raw
-            _validate_schema(value, schema)
-            return value
-        raise ValueError(f"invalid JSON: {error.msg} at line {error.lineno} column {error.colno}") from error
+        else:
+            raise ValueError(
+                f"invalid JSON: {error.msg} at line {error.lineno} column {error.colno}"
+            ) from error
     _validate_schema(value, schema)
     return value
 
 
+def _extract_wrapped_json(raw: str) -> str | None:
+    for match in re.finditer(r"```(?:json)?\s*\r?\n?(.*?)```", raw, re.IGNORECASE | re.DOTALL):
+        return match.group(1).strip()
+
+    stack: list[str] = []
+    start = -1
+    in_string = False
+    escaped = False
+    pairs = {"}": "{", "]": "["}
+    for index, char in enumerate(raw):
+        if in_string:
+            if escaped:
+                escaped = False
+            elif char == "\\":
+                escaped = True
+            elif char == '"':
+                in_string = False
+            continue
+        if char == '"':
+            in_string = True
+        elif char in "{[":
+            if not stack:
+                start = index
+            stack.append(char)
+        elif char in "}]" and stack:
+            if stack[-1] != pairs[char]:
+                return None
+            stack.pop()
+            if not stack:
+                return raw[start:index + 1]
+    return None
+
+
 def _schema_retry_prompt(prompt: str, error: str, schema: dict) -> str:
     return (
         prompt
         + "\n\nValidation error: "
         + error
         + "\nReturn only JSON that satisfies this schema:\n"
         + json.dumps(schema, ensure_ascii=False, sort_keys=True)
     )
@@ -555,16 +659,17 @@ class WorkflowEngine:
                 self.budget.spent_usd += float(row.get("cost_usd") or 0)
             elif event == "schema_invalid":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "schema_invalid"
                 self._retry_state[call_key] = (
                     int(row.get("next_attempt") or 0),
                     str(row.get("error") or "schema validation failed"),
                 )
+                self._step_records[call_key] = {**row, "reason": "schema", "value": None}
             elif event == "prepare_failed":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "prepare_failed"
                 self.budget.dispatched_calls = max(0, self.budget.dispatched_calls - 1)
                 self._step_records[call_key] = {
                     **row, "reason": "prepare_failed", "value": None,
                 }
             elif event == "completed":
@@ -936,40 +1041,48 @@ class WorkflowEngine:
             except ValueError as error:
                 schema_error = str(error)
                 response_path = _save_schema_invalid_response(
                     scratch, attempt + 1, result.text,
                 )
                 self.journal.append({
                     "event": "schema_invalid",
                     "call_key": call_key,
+                    "label": label,
                     "attempt": attempt + 1,
                     "next_attempt": attempt + 1,
                     "error": schema_error,
                     "response_path": response_path.relative_to(self.run_dir).as_posix(),
                     "response_bytes": response_path.stat().st_size,
                     "response_truncated": len(
                         result.text.encode("utf-8", errors="replace")
                     ) > _SCHEMA_RESPONSE_MAX_BYTES,
                 })
+                self._step_records[call_key] = {
+                    "call_key": call_key,
+                    "label": label,
+                    "reason": "schema",
+                    "error": schema_error,
+                    "value": None,
+                }
                 if attempt < 2:
                     current_prompt = _schema_retry_prompt(rendered, schema_error, schema)
 
         if deferred_reason:
             return None
         if result is None or not result.ok or schema_error:
             reason = "error" if result is None else ("schema" if schema_error else result.stop_reason)
             self.partial_reason = self.partial_reason or reason
             self._finish(
                 call_key,
                 None,
                 reason=reason,
                 label=label,
                 cost_usd=total_cost,
-                error=result.error if result is not None else "",
+                error=(schema_error or result.error) if result is not None else "",
             )
             return None
 
         own_id = call_key
         output_free = free_sources | ({own_id} if runtime == "harness" else set())
         output_verified = verified_sources | (free_sources if purpose == "verify" else set())
         step_path = self.steps_dir / f"{call_key.replace(':', '-')}.json"
         value = WorkflowValue(
@@ -1271,50 +1384,69 @@ class WorkflowEngine:
             return await self.agent(
                 task["prompt"], model=task.get("model", "luna"),
                 schema=task.get("schema"), inputs=inputs,
                 label=task.get("label", ""),
                 billing=task.get("billing", "subscription"),
             )
 
         if mode == "parallel":
-            self.result = await self.parallel([
+            values = await self.parallel([
                 lambda task=task: run_task(task) for task in tasks
             ])
+            self.result = [
+                _task_result_record(
+                    task, value,
+                    task_id=f"task-{index + 1}", task_index=index,
+                )
+                for index, (task, value) in enumerate(zip(tasks, values))
+            ]
         elif mode == "chain":
             results = []
             prior = None
-            for task in tasks:
+            for index, task in enumerate(tasks):
                 prior = await run_task(task, prior)
-                results.append(prior)
+                results.append(_task_result_record(
+                    task, prior,
+                    task_id=f"task-{index + 1}", task_index=index,
+                ))
                 if prior is None:
                     break
             self.result = results
         else:
             raise ValueError("mode must be 'parallel' or 'chain'")
         return self.result
 
     async def execute_stages(self, stages: list[dict[str, Any]]) -> Any:
         results_by_stage = []
         previous: list[WorkflowValue] = []
-        for stage in stages:
+        for stage_index, stage in enumerate(stages):
             stage_tasks = stage["tasks"]
-            results = await self.parallel([
+            values = await self.parallel([
                 lambda task=task, prior=tuple(previous): self.agent(
                     task["prompt"], model=task.get("model", "luna"),
                     schema=task.get("schema"), inputs=prior,
                     label=task.get("label", ""),
                     billing=task.get("billing", "subscription"),
                 )
                 for task in stage_tasks
             ])
+            results = [
+                _task_result_record(
+                    task, value,
+                    task_id=f"stage-{stage_index + 1}-task-{task_index + 1}",
+                    task_index=task_index,
+                    stage_index=stage_index,
+                )
+                for task_index, (task, value) in enumerate(zip(stage_tasks, values))
+            ]
             results_by_stage.append(results)
-            if any(value is None for value in results):