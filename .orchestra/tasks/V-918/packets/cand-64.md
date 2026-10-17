# Candidate cand-64

## ORIGIN commit 382660ab41 (2026-10-06): V-738: #V-738: add staged dynamic workflow execution
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index 2d8ae32cc..a4119eb7d 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -2,17 +2,16 @@
 
 Runs as a separate process, communicates with Orchestra via HTTP API.
 Avoids the in-process SDK control_request deadlock (issue #425/#701).
 
 Usage: python -m app.mcp_stdio
 """
 
 import asyncio
-import base64
 import hashlib
 import json
 import logging
 import math
 import os
 import shutil
 import re
 import shlex
@@ -3150,103 +3149,197 @@ async def task_get(par: str, project: str = "") -> str:
     result = await _api("GET", f"/api/tm/tasks/{par}", params=params)
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     return json.dumps(result, ensure_ascii=False)
 
 
 @mcp.tool()
 async def dynamic_workflow(
-    tasks: list[dict[str, Any]],
-    mode: str,
     budget_usd: float,
     max_calls: int,
     max_concurrency: int,
     task_id: str,
     repo: str,
+    tasks: list[dict[str, Any]] | None = None,
+    mode: str = "parallel",
+    stages: list[dict[str, Any]] | None = None,
 ) -> str:
-    """Run a bounded set of model tasks without a workflow file. Each task has prompt, optional model (defaults to luna), and optional JSON schema. mode is parallel or chain; chain passes each completed result as structured input to the next task. Completion wakes the caller with short answers and result paths."""
-    if mode not in {"parallel", "chain"}:
-        return "Error: mode must be 'parallel' or 'chain'"
-    if not tasks or len(tasks) > 100:
-        return "Error: tasks must contain between 1 and 100 items"
+    """Run model tasks in parallel, as a result-fed chain, or in parallel stages. Stages accept task lists or one prompt plus items using {item}; every task in a stage receives all prior-stage results as structured input. Each task has an optional model (defaults to luna) and JSON schema. Completion wakes the caller with answers and result paths. Limits: 20 stages, 1,000 expanded tasks, and a 1 MiB specification.
+
+    MiroFish example: 50 personas read a page, then each writes a reaction for
+    three rounds using all results from the previous round, then one analyst
+    produces a report. This is one tool call:
+
+        personas = [{"id": i, "profile": f"persona {i}"} for i in range(50)]
+        stages = [{"prompt": "Read PAGE_URL as persona {item}; write your initial view.",
+                   "items": personas}]
+        stages += [{"prompt": f"Round {round_no}: as persona {{item}}, read every prior post in your structured inputs and write one reaction.",
+                    "items": personas} for round_no in range(1, 4)]
+        stages.append({"tasks": [{"prompt": "Analyze the page and all three rounds in your structured inputs; write the audience report."}]})
+        dynamic_workflow(budget_usd=5, max_calls=300, max_concurrency=20,
+                         task_id="TASK-ID", repo="/absolute/repository",
+                         mode="stages", stages=stages)
+    """
+    if stages is not None:
+        if mode != "stages" or tasks is not None:
+            return "Error: pass stages with mode='stages' and omit tasks"
+        if not stages or len(stages) > 20:
+            return "Error: stages must contain between 1 and 20 stages"
+        expanded_stages = []
+        total_tasks = 0
+        spec_payload_size = 0
+        for stage_index, stage in enumerate(stages):
+            if not isinstance(stage, dict):
+                return f"Error: stages[{stage_index}] must be an object"
+            allowed_fields = {"tasks", "prompt", "items", "model", "schema"}
+            unknown_fields = set(stage) - allowed_fields
+            if unknown_fields:
+                return f"Error: stages[{stage_index}] has unknown field {sorted(unknown_fields)[0]}"
+            default_model = stage.get("model", "luna")
+            default_schema = stage.get("schema")
+            if "tasks" in stage:
+                if "prompt" in stage or "items" in stage:
+                    return f"Error: stages[{stage_index}] must use either tasks or prompt and items"
+                stage_tasks = stage["tasks"]
+                if not isinstance(stage_tasks, list) or not stage_tasks:
+                    return f"Error: stages[{stage_index}].tasks must be a non-empty array"
+                task_count = len(stage_tasks)
+            elif "prompt" in stage and "items" in stage:
+                template = stage["prompt"]
+                items = stage["items"]
+                if not isinstance(template, str) or "{item}" not in template:
+                    return f"Error: stages[{stage_index}].prompt must contain '{{item}}'"
+                if not isinstance(items, list) or not items:
+                    return f"Error: stages[{stage_index}].items must be a non-empty array"
+                task_count = len(items)
+                stage_tasks = (
+                    {"prompt": template.replace(
+                        "{item}", item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
+                    )}
+                    for item in items
+                )
+            else:
+                return f"Error: stages[{stage_index}] needs tasks or prompt and items"
+            if total_tasks + task_count > 1000:
+                return "Error: expanded workflow exceeds 1,000 tasks"
+            normalized_stage = []
+            for task_index, task in enumerate(stage_tasks):
+                if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
+                    return f"Error: stages[{stage_index}].tasks[{task_index}].prompt must be a non-empty string"
+                normalized, error = _normalize_dynamic_task(
+                    task, default_model=default_model,
+                    default_schema=default_schema,
+                    label=f"stages[{stage_index}].tasks[{task_index}]",
+                )
+                if error:
+                    return f"Error: {error}"
+                normalized_stage.append(normalized)
+                spec_payload_size += len(
+                    json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
+                )
+                if spec_payload_size > 1024 * 1024:
+                    return "Error: workflow specification exceeds 1 MiB"
+            expanded_stages.append({"tasks": normalized_stage})
+            total_tasks += task_count
+        spec_payload = {"mode": "stages", "stages": expanded_stages}
+    else:
+        if mode not in {"parallel", "chain"}:
+            return "Error: mode must be 'parallel' or 'chain' unless stages are supplied"
+        if not isinstance(tasks, list) or not tasks or len(tasks) > 1000:
+            return "Error: tasks must contain between 1 and 1,000 items"
+        normalized = []
+        for index, task in enumerate(tasks):
+            if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
+                return f"Error: tasks[{index}].prompt must be a non-empty string"
+            row, error = _normalize_dynamic_task(task, label=f"tasks[{index}]")
+            if error:
+                return f"Error: {error}"
+            normalized.append(row)
+        spec_payload = {"tasks": normalized, "mode": mode}
     if (not isinstance(budget_usd, (int, float)) or isinstance(budget_usd, bool)
             or not math.isfinite(budget_usd) or budget_usd <= 0):
         return "Error: budget_usd must be positive"
     if not isinstance(max_calls, int) or isinstance(max_calls, bool) or max_calls < 1:
         return "Error: max_calls must be a positive integer"
     if not isinstance(max_concurrency, int) or isinstance(max_concurrency, bool) or not 1 <= max_concurrency <= 100:
         return "Error: max_concurrency must be between 1 and 100"
     if not task_id or not task_id.strip():
         return "Error: task_id is required"
     if re.fullmatch(r"[A-Za-z0-9._-]+", task_id) is None:
         return "Error: task_id may contain only letters, digits, dot, underscore, and dash"
     repo_path = Path(repo).expanduser().resolve()
     if not repo_path.is_dir():
         return f"Error: repository directory not found: {repo_path}"
 
-    from app.models import get_model_flags, resolve_model
-
-    normalized = []
-    for index, task in enumerate(tasks):
-        if not isinstance(task, dict) or not isinstance(task.get("prompt"), str) or not task["prompt"].strip():
-            return f"Error: tasks[{index}].prompt must be a non-empty string"
-        row = {"prompt": task["prompt"]}
-        model = task.get("model", "luna")
-        if not isinstance(model, str) or not model.strip():
-            return f"Error: tasks[{index}].model must be a non-empty string"
-        try:
-            model_id = resolve_model(model)
-        except (ValueError, TypeError) as error:
-            return f"Error: tasks[{index}].model: {error}"
-        if model_id in {"gpt-6-astra", "gpt-6-sol", "gpt-5.6-sol"}:
-            return f"Error: model '{model}' is not allowed for dynamic workflows"
-        if not get_model_flags(model_id)["agents"]:
-            return f"Error: model '{model}' is not enabled for agents"
-        row["model"] = model_id
-        schema = task.get("schema")
-        if schema is not None:
-            if not isinstance(schema, dict):
-                return f"Error: tasks[{index}].schema must be a JSON object"
-            row["schema"] = schema
-        normalized.append(row)
-
     runner_root = Path(__file__).resolve().parents[1]
     run_id = f"{task_id}-{uuid.uuid4().hex[:12]}"
-    spec = json.dumps({"tasks": normalized, "mode": mode}, ensure_ascii=False, separators=(",", ":"))
-    tasks_b64 = base64.urlsafe_b64encode(spec.encode()).decode()
-    if len(tasks_b64) > 64 * 1024:
-        return "Error: encoded tasks exceed the 64 KiB command limit"
+    spec = json.dumps(spec_payload, ensure_ascii=False, separators=(",", ":"))
+    spec_bytes = spec.encode("utf-8")
+    if len(spec_bytes) > 1024 * 1024:
+        return "Error: workflow specification exceeds 1 MiB"
+    run_dir = runner_root / "data" / "workflow-runs" / run_id
+    try:
+        run_dir.mkdir(parents=True, exist_ok=False)
+        (run_dir / "request.json").write_bytes(spec_bytes)
+    except OSError as error:
+        return f"Error: cannot save workflow specification: {error}"
     command_parts = [
         "env", f"ORCHESTRA_TASK_ID={task_id}", f"ORCHESTRA_SCOPE={SCOPE}",
         sys.executable, str(runner_root / "scripts" / "wf_run.py"),
-        "--tasks-b64", tasks_b64, "--run-id", run_id,
+        "--spec", str(run_dir / "request.json"), "--run-id", run_id,
         "--budget-usd", f"{budget_usd:g}", "--max-calls", str(max_calls),
         "--max-concurrency", str(max_concurrency), "--repo", str(repo_path),
     ]
     command = shlex.join(command_parts)
     manifest_path = runner_root / "data" / "workflow-runs" / run_id / "manifest.json"
     result = await _api("POST", "/api/bg/jobs", json={
         "type": "run",
         "config": {
             "command": command,
             "cwd": str(repo_path),
             "success_file": str(manifest_path),
             "success_pattern": r'"complete"\s*:\s*true',
         },
-        "message": f"Dynamic workflow {run_id} ({len(tasks)} tasks, {mode})",
+        "message": f"Dynamic workflow {run_id} ({total_tasks if stages is not None else len(tasks)} tasks, {mode})",
         "target_name": WORKER_NAME,
         "target_scope": SCOPE,
         "timeout_seconds": 3600,
         "created_by": WORKER_NAME,
     })
     if isinstance(result, dict) and result.get("error"):
         return f"Error: {result['error']}"
     return (f"Dynamic workflow queued: run_id={run_id}, job_id={result.get('id', '?')}, "
-            f"tasks={len(tasks)}, mode={mode}. The completion message will include answers and result paths.")
+            f"tasks={total_tasks if stages is not None else len(tasks)}, mode={mode}. The completion message will include answers and result paths.")
+
+
+def _normalize_dynamic_task(
+    task: dict[str, Any], *, default_model: str = "luna",
+    default_schema: dict | None = None, label: str,
+) -> tuple[dict[str, Any], str | None]:
+    from app.models import get_model_flags, resolve_model
+
+    model = task.get("model", default_model)
+    if not isinstance(model, str) or not model.strip():
+        return {}, f"{label}.model must be a non-empty string"
+    try:
+        model_id = resolve_model(model)
+    except (ValueError, TypeError) as error:
+        return {}, f"{label}.model: {error}"
+    if model_id in {"gpt-6-astra", "gpt-6-sol", "gpt-5.6-sol"}:
+        return {}, f"model '{model}' is not allowed for dynamic workflows"
+    if not get_model_flags(model_id)["agents"]:
+        return {}, f"model '{model}' is not enabled for agents"
+    schema = task.get("schema", default_schema)
+    if schema is not None and not isinstance(schema, dict):
+        return {}, f"{label}.schema must be a JSON object"
+    normalized = {"prompt": task["prompt"], "model": model_id}
+    if schema is not None:
+        normalized["schema"] = schema
+    return normalized, None
 
 
 @mcp.tool()
 async def bg_create(type: str, message: str = "", target: str = "",
                     delay_seconds: int = 0, path: str = "", pattern: str = "",
                     command: str = "", host: str = "", cron_expr: str = "",
                     interval_seconds: int = 60,
                     timeout_seconds: int = 3600) -> str:
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index 0c9ea4a6b..a490e303e 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -1065,51 +1065,81 @@ class WorkflowEngine:
                 results.append(prior)
                 if prior is None:
                     break
             self.result = results
         else:
             raise ValueError("mode must be 'parallel' or 'chain'")
         return self.result
 
+    async def execute_stages(self, stages: list[dict[str, Any]]) -> Any:
+        results_by_stage = []
+        previous: list[WorkflowValue] = []
+        for stage in stages:
+            stage_tasks = stage["tasks"]
+            results = await self.parallel([
+                lambda task=task, prior=tuple(previous): self.agent(
+                    task["prompt"], model=task.get("model", "luna"),
+                    schema=task.get("schema"), inputs=prior,
+                )
+                for task in stage_tasks
+            ])
+            results_by_stage.append(results)
+            if any(value is None for value in results):
+                break
+            previous = results
+        self.result = results_by_stage
+        return self.result
+
+    async def execute_spec(self, spec: dict[str, Any]) -> Any:
+        if spec.get("mode") == "stages":
+            return await self.execute_stages(spec["stages"])
+        return await self.execute_tasks(spec)
+
 
 def _args() -> argparse.Namespace:
     parser = argparse.ArgumentParser(description=__doc__)
     parser.add_argument("workflow", type=Path, nargs="?")
     group = parser.add_mutually_exclusive_group(required=True)
     group.add_argument("--run-id")
     group.add_argument("--resume")
     parser.add_argument("--budget-usd", type=float, required=True)
     parser.add_argument("--max-calls", type=int, default=100)
     parser.add_argument("--max-concurrency", type=int, default=None)
     parser.add_argument("--repo", type=Path, help="Target repository for isolated writable calls")
+    parser.add_argument("--spec", type=Path, help="JSON workflow specification file")
     parser.add_argument("--tasks-b64", help="Base64-encoded declarative tasks; avoids a workflow file")
     return parser.parse_args()
 
 
 async def _main() -> int:
     args = _args()
     run_id = args.resume or args.run_id
-    if bool(args.workflow) == bool(args.tasks_b64):
-        raise ValueError("provide exactly one of workflow or --tasks-b64")
+    if sum(bool(value) for value in (args.workflow, args.tasks_b64, args.spec)) != 1:
+        raise ValueError("provide exactly one of workflow, --spec, or --tasks-b64")
     workflow = args.workflow.resolve() if args.workflow else None
     spec = None
     if args.tasks_b64:
         spec = json.loads(base64.urlsafe_b64decode(args.tasks_b64.encode()).decode())
+    elif args.spec:
+        spec = json.loads(args.spec.read_text(encoding="utf-8"))
     run_dir = ROOT / "data" / "workflow-runs" / run_id
     encoded_spec = args.tasks_b64 or ""
     command_parts = [
         "env", f"ORCHESTRA_TASK_ID={os.environ.get('ORCHESTRA_TASK_ID', '')}",
         f"ORCHESTRA_SCOPE={os.environ.get('ORCHESTRA_SCOPE', '')}",
         sys.executable, str(ROOT / "scripts" / "wf_run.py"),
-        "--tasks-b64", encoded_spec,
         "--budget-usd", f"{args.budget_usd:g}",
         "--max-calls", str(args.max_calls),
         "--max-concurrency", str(args.max_concurrency or 3),
     ] if spec is not None else []
+    if args.spec:
+        command_parts.extend(["--spec", str(args.spec.resolve())])
+    elif args.tasks_b64:
+        command_parts.extend(["--tasks-b64", encoded_spec])
     if args.repo:
         command_parts.extend(["--repo", str(args.repo.resolve())])
     if spec is not None:
         command_parts.extend(["--resume", run_id])
     command = shlex.join(command_parts) if command_parts else ""
     engine = WorkflowEngine(
         run_id,
         run_dir,
@@ -1121,31 +1151,40 @@ async def _main() -> int:
         resume_command_override=command,
     )
     resume = engine.resume_command()
     print(f"WF_BG_MESSAGE={json.dumps(f'wf_run {run_id} interrupted; resume with: {resume}')}", flush=True)
     try:
         if spec is None:
             await engine.execute(workflow)
         else:
-            await engine.execute_tasks(spec)
+            await engine.execute_spec(spec)
     except BaseException:
         engine.partial_reason = engine.partial_reason or "error"
         raise
     finally:
         manifest = engine.write_manifest()
         print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), flush=True)
         if spec is not None:
             print(_notification_summary(manifest), flush=True)
     return 0
 
 
 def _notification_summary(manifest: dict) -> str:
     steps = manifest.get("steps", [])
-    results = manifest.get("result") or []
+    results = []
+
+    def flatten(value):
+        if isinstance(value, list):
+            for item in value:
+                flatten(item)
+        else:
+            results.append(value)
+
+    flatten(manifest.get("result") or [])
     successful = sum(step.get("reason") == "completed" for step in steps)
     total = max(len(steps), len(results))
     lines = [
         f"WORKFLOW_SUMMARY run={manifest.get('run_id')} "
         f"successful={successful}/{total} "
         f"complete={str(bool(manifest.get('complete'))).lower()} "
         f"manifest={ROOT / 'data' / 'workflow-runs' / str(manifest.get('run_id')) / 'manifest.json'}"
     ]
diff --git a/tests/test_dynamic_workflows.py b/tests/test_dynamic_workflows.py
index 5660c12a8..452ca35a2 100644
--- a/tests/test_dynamic_workflows.py
+++ b/tests/test_dynamic_workflows.py
@@ -1,11 +1,10 @@
 """Prevent lost workflow routing, wrong-project edits and obsolete MCP dispatch."""
 import asyncio
-import base64
 import json
 import shlex
 import sys
 from pathlib import Path
 
 import pytest
 
 from app import mcp_stdio, pipeline
@@ -81,41 +80,73 @@ async def test_dynamic_workflow_tool_builds_durable_run_and_manifest_delivery(tm
 
     async def fake_api(method, path, **kwargs):
         captured.update(method=method, path=path, body=kwargs['json'])
         return {'id': 'bg-test', 'status': 'active'}
 
     monkeypatch.setattr(mcp_stdio, '_api', fake_api)
     monkeypatch.setattr(mcp_stdio, 'SCOPE', 'test-scope')
     monkeypatch.setattr(mcp_stdio, 'WORKER_NAME', 'test-orchestrator')
+    fake_install = tmp_path / 'install'
+    (fake_install / 'app').mkdir(parents=True)
+    monkeypatch.setattr(mcp_stdio, '__file__', str(fake_install / 'app' / 'mcp_stdio.py'))
+    large_prompt = 'context ' * 9000
     response = await mcp_stdio.dynamic_workflow(
-        tasks=[{'prompt': 'first', 'schema': {'type': 'object'}}, {'prompt': 'second'}],
-        mode='parallel', budget_usd=1, max_calls=2, max_concurrency=2,
+        stages=[{
+            'prompt': large_prompt + 'persona={item}',
+            'items': [{'id': 1, 'profile': 'first'}, {'id': 2, 'profile': 'second'}],
+            'schema': {'type': 'object'},
+        }],
+        mode='stages', budget_usd=1, max_calls=2, max_concurrency=2,
         task_id='V-720', repo=str(tmp_path),
     )
     assert 'queued' in response
     body = captured['body']
     assert captured['method'] == 'POST' and captured['path'] == '/api/bg/jobs'
     assert body['type'] == 'run'
     assert body['target_name'] == 'test-orchestrator'
     assert body['target_scope'] == 'test-scope'
     assert body['config']['cwd'] == str(tmp_path.resolve())
     assert body['config']['success_file'].endswith('/manifest.json')
     assert body['config']['success_pattern'] == r'"complete"\s*:\s*true'
     args = shlex.split(body['config']['command'])
     assert args[:3] == ['env', 'ORCHESTRA_TASK_ID=V-720', 'ORCHESTRA_SCOPE=test-scope']
-    assert '--tasks-b64' in args and '--run-id' in args and '--repo' in args
-    spec = json.loads(base64.urlsafe_b64decode(args[args.index('--tasks-b64') + 1]))
-    assert spec == {
-        'tasks': [
-            {'prompt': 'first', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}},
-            {'prompt': 'second', 'model': 'gpt-6-luna'},
-        ],
-        'mode': 'parallel',
-    }
+    assert '--spec' in args and '--run-id' in args and '--repo' in args
+    assert '--tasks-b64' not in args and large_prompt not in body['config']['command']
+    spec_path = Path(args[args.index('--spec') + 1])
+    assert spec_path.stat().st_size > 64 * 1024
+    spec = json.loads(spec_path.read_text())
+    assert spec['mode'] == 'stages' and len(spec['stages'][0]['tasks']) == 2
+    assert spec['stages'][0]['tasks'] == [
+        {'prompt': large_prompt + 'persona={"id": 1, "profile": "first"}', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}},
+        {'prompt': large_prompt + 'persona={"id": 2, "profile": "second"}', 'model': 'gpt-6-luna', 'schema': {'type': 'object'}},
+    ]
+
+
+@pytest.mark.asyncio
+@pytest.mark.parametrize('mode', ['parallel', 'chain'])
+async def test_dynamic_workflow_keeps_legacy_task_modes(mode, tmp_path, monkeypatch):
+    captured = {}
+
+    async def fake_api(_method, _path, **kwargs):
+        captured.update(kwargs['json'])
+        return {'id': 'bg-legacy'}
+
+    fake_install = tmp_path / 'install'
+    (fake_install / 'app').mkdir(parents=True)
+    monkeypatch.setattr(mcp_stdio, '__file__', str(fake_install / 'app' / 'mcp_stdio.py'))
+    monkeypatch.setattr(mcp_stdio, '_api', fake_api)
+    response = await mcp_stdio.dynamic_workflow(
+        budget_usd=1, max_calls=2, max_concurrency=2, task_id='V-738', repo=str(tmp_path),
+        tasks=[{'prompt': 'legacy task'}], mode=mode,
+    )
+    assert 'queued' in response
+    args = shlex.split(captured['config']['command'])
+    spec = json.loads(Path(args[args.index('--spec') + 1]).read_text())
+    assert spec == {'tasks': [{'prompt': 'legacy task', 'model': 'gpt-6-luna'}], 'mode': mode}
 
 
 @pytest.mark.asyncio
 @pytest.mark.parametrize('model', ['astra', 'sol', 'gpt-5.6-sol'])
 async def test_dynamic_workflow_rejects_platform_blocked_models(model, monkeypatch):
     async def unexpected_api(*_args, **_kwargs):
         pytest.fail('blocked models must not create a background job')
 
@@ -130,21 +161,24 @@ async def test_dynamic_workflow_rejects_platform_blocked_models(model, monkeypat
 
 @pytest.mark.asyncio
 async def test_inline_workflow_run_writes_manifest_and_completion_summary(tmp_path, monkeypatch, capsys):
     from scripts.wf_adapters import AdapterResult, Usage
 
     repo = _git_repo(tmp_path / 'target')
     runner = tmp_path / 'runner'
     runner.mkdir()
+    spec_path = runner / 'data/workflow-runs/inline-test/request.json'
+    spec_path.parent.mkdir(parents=True)
+    spec_path.write_text(json.dumps({
+        'tasks': [{'prompt': 'one'}, {'prompt': 'two'}], 'mode': 'parallel',
+    }))
     monkeypatch.setattr(wf_run, 'ROOT', runner)
     monkeypatch.setattr(sys, 'argv', [
-        'wf_run.py', '--tasks-b64', base64.urlsafe_b64encode(json.dumps({
-            'tasks': [{'prompt': 'one'}, {'prompt': 'two'}], 'mode': 'parallel',
-        }).encode()).decode(), '--repo', str(repo), '--run-id', 'inline-test',
+        'wf_run.py', '--spec', str(spec_path), '--repo', str(repo), '--run-id', 'inline-test',
         '--budget-usd', '1', '--max-calls', '2', '--max-concurrency', '2',
     ])
     arrived = []
     both = asyncio.Event()
 
     async def adapter(prompt, **_kwargs):
         arrived.append(prompt)
         if len(arrived) == 2:
@@ -163,17 +197,18 @@ async def test_inline_workflow_run_writes_manifest_and_completion_summary(tmp_pa
     monkeypatch.setattr(wf_run, 'persist_turn_usage', lambda **_kwargs: True)
     assert await wf_run._main() == 0
     output = capsys.readouterr().out
     manifest = json.loads((runner / 'data/workflow-runs/inline-test/manifest.json').read_text())
     assert manifest['complete'] and len(manifest['steps']) == 2
     assert 'WORKFLOW_SUMMARY run=inline-test successful=2/2 complete=true' in output
     assert 'answer one' in output and 'answer two' in output
     resume = shlex.split(manifest['resume_command'])
-    assert '--tasks-b64' in resume and '--resume' in resume
+    assert resume[resume.index('--spec') + 1] == str(spec_path)
+    assert '--resume' in resume
 
 
 @pytest.mark.asyncio
 async def test_inline_chain_passes_each_result_as_structured_input(tmp_path):
     prompts = []
 
     async def adapter(prompt, **_kwargs):
         prompts.append(prompt)
@@ -189,8 +224,69 @@ async def test_inline_chain_passes_each_result_as_structured_input(tmp_path):
     )
     result = await engine.execute_tasks({
         'mode': 'chain',
         'tasks': [{'prompt': 'first'}, {'prompt': 'second'}],
     })
     assert [item.data for item in result] == ['result-1', 'result-2']
     assert prompts[0] == 'first'
     assert prompts[1].startswith('second\n\nStructured inputs:\n["result-1"]')
+
+
+@pytest.mark.asyncio
+async def test_stages_give_every_next_stage_task_all_previous_results(tmp_path):
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
+        'all-inputs-check', tmp_path, budget_usd=1, max_calls=4,
+        adapter=adapter, usage_writer=None, readiness_checker=readiness,
+        default_modules=(),
+    )
+    result = await engine.execute_stages([
+        {'tasks': [{'prompt': 'first'}, {'prompt': 'second'}]},
+        {'tasks': [{'prompt': 'third'}, {'prompt': 'fourth'}]},
+    ])
+    assert len(result) == 2 and len(result[0]) == len(result[1]) == 2
+    assert prompts[2].startswith('third\n\nStructured inputs:\n["result-1", "result-2"]')
+    assert prompts[3].startswith('fourth\n\nStructured inputs:\n["result-1", "result-2"]')
+
+
+@pytest.mark.asyncio
+async def test_stage_budget_is_global_and_resume_replays_prior_stage(tmp_path):
+    prompts = []
+
+    async def adapter(prompt, **_kwargs):
+        prompts.append(prompt)
+        return _result(f"result-{len(prompts)}", cost=1.1 if len(prompts) == 1 else 0.01)
+
+    async def readiness(_model):
+        return {'state': 'available'}
+
+    stages = [
+        {'tasks': [{'prompt': 'first'}]},
+        {'tasks': [{'prompt': 'second'}]},
+    ]
+    first = wf_run.WorkflowEngine(
+        'stage-budget', tmp_path, budget_usd=1, max_calls=2,
+        adapter=adapter, usage_writer=None, readiness_checker=readiness,
+        default_modules=(),
+    )
+    partial = await first.execute_stages(stages)
+    assert partial[0][0].data == 'result-1' and partial[1] == [None]
+    assert first.write_manifest()['partial_reason'] == 'budget'
+    assert prompts == ['first']
+
+    resumed = wf_run.WorkflowEngine(
+        'stage-budget', tmp_path, budget_usd=2, max_calls=2,
+        adapter=adapter, usage_writer=None, readiness_checker=readiness,
+        default_modules=(),
+    )
+    complete = await resumed.execute_stages(stages)
+    assert [item[0].data for item in complete] == ['result-1', 'result-2']
+    assert prompts[0] == 'first'
+    assert prompts[1].startswith('second\n\nStructured inputs:\n["result-1"]')


## LATER FIX 532c73f620 (11.1 days later): V-916: #V-916: fix workflow schema, identity, and resume races
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