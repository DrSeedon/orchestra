# Candidate cand-59

## ORIGIN commit 45e3bbcd9f (2026-09-05): #494: freeze capability and isolation oracles
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/harness/oneshot.py b/app/harness/oneshot.py
index 977d314bb..82480ff34 100644
--- a/app/harness/oneshot.py
+++ b/app/harness/oneshot.py
@@ -1,74 +1,87 @@
-"""Stateless read-only entry point for one Harness turn."""
+"""Stateless capability-scoped entry point for one Harness turn."""
 
 from __future__ import annotations
 
 import argparse
 import asyncio
 import json
 import os
 from pathlib import Path
 
-from app.harness import tools
+from app.harness import prompts, tools
 from app.harness.llm import OpenRouterClient
 from app.harness.loop import AgentLoop
 from app.harness.mcp import MCPClient
 from app.models import get_model_spec, validate_harness_model_spec
 
 
-async def run_oneshot(*, prompt: str, model: str, cwd: Path) -> dict:
+async def run_oneshot(
+    *, prompt: str, model: str, cwd: Path, tools_level: str = "read",
+    network: bool = True, mcp: bool = True, system_prompt: str = "", llm=None,
+) -> dict:
     spec = get_model_spec(model)
     validate_harness_model_spec(spec)
     key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
     if not key:
         raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY)")
     base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
     if not base_url.rstrip("/").endswith("/v1"):
         base_url = base_url.rstrip("/") + "/v1"
-    llm = OpenRouterClient(
-        api_key=key,
-        model=model,
-        base_url=base_url,
+    llm = llm or OpenRouterClient(
+        api_key=key, model=model, base_url=base_url,
         supported_parameters=spec.supported_parameters,
     )
-    loop = AgentLoop(
-        llm=llm,
-        mcp=MCPClient(),
-        cwd=str(cwd),
-        history=[{
-            "role": "system",
-            "content": (
-                "You are a read-only workflow agent. Use read, glob, and grep only when needed. "
-                "Return the requested result and do not modify files."
-            ),
-        }],
-        tool_schemas=tools.readonly_tool_schemas(),
-        max_context=spec.context_length,
-        readonly_mode=True,
-    )
-    text: list[str] = []
+    mcp_client = MCPClient()
     try:
+        if mcp and tools_level == "all" and network:
+            from app.runtime_registry import _load_scope_mcp_servers
+
+            await mcp_client.connect(_load_scope_mcp_servers(str(cwd)))
+        own_schemas = (
+            tools.tool_schemas() if tools_level == "all" else tools.readonly_tool_schemas()
+        )
+        if not network:
+            own_schemas = [
+                item
+                for item in own_schemas
+                if item.get("function", {}).get("name") != "bash"
+            ]
+        schemas = prompts.merge_tool_schemas(own_schemas, mcp_client.tool_schemas())
+        loop = AgentLoop(
+            llm=llm,
+            mcp=mcp_client,
+            cwd=str(cwd),
+            history=[{"role": "system", "content": system_prompt.strip()}],
+            tool_schemas=schemas,
+            max_context=spec.context_length,
+            readonly_mode=tools_level != "all",
+        )
+        text: list[str] = []
         async for event in loop.run(prompt):
             if event.type == "text":
                 text.append(event.content)
+        usages = loop.round_usages
+        return {
+            "text": "".join(text).strip(),
+            "ok": loop.ok,
+            "stop_reason": loop.stop_reason,
+            "error": loop.error_detail,
+            "cost_usd": sum(float(item.get("cost") or 0) for item in usages),
+            "usage": {
+                "input_tokens": sum(int(item.get("prompt_tokens") or 0) for item in usages),
+                "output_tokens": sum(
+                    int(item.get("completion_tokens") or 0) for item in usages
+                ),
+            },
+        }
     finally:
+        await mcp_client.disconnect()
         await llm.aclose()
-    usages = loop.round_usages
-    return {
-        "text": "".join(text).strip(),
-        "ok": loop.ok,
-        "stop_reason": loop.stop_reason,
-        "error": loop.error_detail,
-        "cost_usd": sum(float(item.get("cost") or 0) for item in usages),
-        "usage": {
-            "input_tokens": sum(int(item.get("prompt_tokens") or 0) for item in usages),
-            "output_tokens": sum(int(item.get("completion_tokens") or 0) for item in usages),
-        },
-    }
 
 
 def main() -> int:
     parser = argparse.ArgumentParser()
     parser.add_argument("--model", required=True)
     parser.add_argument("--cwd", type=Path, required=True)
     args = parser.parse_args()
     row = asyncio.run(
diff --git a/app/pipeline.py b/app/pipeline.py
index 02f11b94c..d5cc57f6a 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -560,16 +560,31 @@ def prompt_path(pipeline_name: str, rel: str) -> Path:
     return PIPELINES_DIR / pipeline_name / "prompts" / rel
 
 
 def template_path(pipeline_name: str, template: str) -> Path:
     """Путь к шаблону doc-папки внутри ``.orchestra/pipelines/<name>/templates/``."""
     return PIPELINES_DIR / pipeline_name / "templates" / template
 
 
+def build_prompt_modules(pipeline_name: str, modules: list[str] | tuple[str, ...]) -> str:
+    """Assemble named modules from the canonical pipeline prompt library."""
+    parts: list[str] = []
+    for module in modules:
+        if not _is_safe_rel(module):
+            raise ValueError(f"unsafe module name '{module}' (abs или '..')")
+        path = prompt_path(pipeline_name, f"modules/{module}.md")
+        if not path.is_file():
+            raise FileNotFoundError(
+                f"pipeline '{pipeline_name}' module '{module}' not found at {path}"
+            )
+        parts.append(path.read_text().strip())
+    return "\n\n".join(parts)
+
+
 def build_system_prompt(pipeline_name: str, role: str, scope: str = "") -> str:
     """Собрать system_prompt из prompt_layers резолвнутой роли.
 
     Каждый слой читается из ``.orchestra/pipelines/<name>/prompts/<layer>`` через
     :func:`prompt_path` (единственный источник — app/prompts/ удалён). Отсутствующий
     слой-файл пропускается. Конкатенация через ``\\n\\n``. Динамика (каталог ролей,
     блоки других оркестраторов/воркеров) добавляется вызывающим в manager — здесь
     только статика из файлов.
@@ -582,27 +597,19 @@ def build_system_prompt(pipeline_name: str, role: str, scope: str = "") -> str:
         ловит и делегирует в legacy-путь апстрима).
     """
     rr = resolve_role(load_pipeline(pipeline_name), role)
     parts: list[str] = []
     for layer in rr.prompt_layers:
         p = prompt_path(pipeline_name, layer)
         if p.is_file():
             parts.append(p.read_text())
-    for m in rr.modules:
-        mp = prompt_path(pipeline_name, f"modules/{m}.md")
-        if mp.is_file():
-            # ``.strip()`` — точное соответствие upstream ``_load_modules`` (manager.py):
-            # модули инлайнятся обрезанными, разделитель между ними ровно ``\n\n``.
-            # Без strip хвостовые ``\n`` в файле дают ``\n\n\n`` и расхождение с upstream.
-            parts.append(mp.read_text().strip())
-        else:
-            logger.warning(
-                "pipeline '%s' role '%s': module '%s' not found at %s — skipped",
-                pipeline_name, role, m, mp)
+    module_text = build_prompt_modules(pipeline_name, rr.modules)
+    if module_text:
+        parts.append(module_text)
     return "\n\n".join(parts)
 
 
 # ── Активный пайплайн ──────────────────────────────────────────────────────
 
 def get_active_pipeline(scope: str = "", parent_pipeline: str = "") -> str:
     """Определить активный пайплайн для НОВОЙ сессии.
 
diff --git a/scripts/wf_adapters.py b/scripts/wf_adapters.py
index ff9c3f9b4..42f5a0046 100644
--- a/scripts/wf_adapters.py
+++ b/scripts/wf_adapters.py
@@ -2,19 +2,22 @@
 """One-shot runtime adapters for scripted workflows."""
 
 from __future__ import annotations
 
 import asyncio
 import json
 import os
 import signal
+import shutil
+import stat
 from dataclasses import dataclass, field
 from pathlib import Path
 from typing import Any
+from uuid import uuid4
 
 
 @dataclass(frozen=True)
 class Usage:
     input_tokens: int = 0
     output_tokens: int = 0
     cache_read_tokens: int = 0
     cache_create_tokens: int = 0
@@ -155,26 +158,27 @@ def persist_turn_usage(
         input_tokens=result.usage.input_tokens,
         output_tokens=result.usage.output_tokens,
         cache_read_tokens=result.usage.cache_read_tokens,
         cache_create_tokens=result.usage.cache_create_tokens,
     )
 
 
 async def _run_process(
-    argv: list[str], prompt: str, cwd: Path, timeout: float
+    argv: list[str], prompt: str, cwd: Path, timeout: float,
+    *, env: dict[str, str] | None = None,
 ) -> tuple[int, str, str]:
     try:
         proc = await asyncio.create_subprocess_exec(
             *argv,
             stdin=asyncio.subprocess.PIPE,
             stdout=asyncio.subprocess.PIPE,
             stderr=asyncio.subprocess.PIPE,
             cwd=cwd,
-            env=os.environ.copy(),
+            env=env or os.environ.copy(),
             start_new_session=True,
         )
     except OSError as error:
         return 127, "", f"{type(error).__name__}: {error}"
     try:
         stdout, stderr = await asyncio.wait_for(
             proc.communicate(prompt.encode()), timeout=max(1.0, timeout)
         )
@@ -209,75 +213,156 @@ def _failed(runtime: str, model: str, reason: str, *, stop_reason: str) -> Adapt
         ok=False,
         stop_reason=stop_reason,
         cost_usd=None,
         cost_unaccounted=True,
         error=reason[:2000],
     )
 
 
-async def run_codex(prompt: str, *, model: str, cwd: Path, timeout: float) -> AdapterResult:
+def _prompt_with_rules(prompt: str, system_prompt: str) -> str:
+    if not system_prompt.strip():
+        return prompt
+    return f"<workflow_rules>\n{system_prompt.strip()}\n</workflow_rules>\n\n{prompt}"
+
+
+def _claude_tools(tools_level: str, network: bool) -> str:
+    if tools_level == "all" and network:
+        return "default"
+    if tools_level == "all":
+        return "Read,Write,Edit,Glob,Grep"
+    if tools_level == "read" and network:
+        return "Read,Glob,Grep,WebFetch,WebSearch"
+    return "Read,Glob,Grep"
+
+
+def _write_claude_mcp_config(cwd: Path, enabled: bool) -> Path:
+    from app.runtime_registry import _load_scope_mcp_servers
+
+    servers = _load_scope_mcp_servers(str(cwd)) if enabled else {}
+    path = cwd / ".wf-mcp.json"
+    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
+    with os.fdopen(fd, "w", encoding="utf-8") as fh:
+        json.dump({"mcpServers": servers}, fh, ensure_ascii=False)
+    if stat.S_IMODE(path.stat().st_mode) != 0o600:
+        raise PermissionError(f"unsafe MCP config permissions: {path}")
+    return path
+
+
+async def run_codex(
+    prompt: str, *, model: str, cwd: Path, timeout: float,
+    tools: str = "all", network: bool = True, mcp: bool = True,
+    system_prompt: str = "", state_dir: Path | None = None,
+) -> AdapterResult:
     binary = os.environ.get("WF_CODEX_BIN", "codex")
+    sandbox = "danger-full-access" if tools == "all" and network else (
+        "workspace-write" if tools == "all" else "read-only"
+    )
     argv = [
         binary,
         "-m",
         model,
         "-s",
-        "read-only",
+        sandbox,
         "-a",
         "never",
         "exec",
         "--ephemeral",
-        "--ignore-user-config",
         "--ignore-rules",
+        "-c",
+        f'web_search="{"live" if network else "disabled"}"',
         "--skip-git-repo-check",
         "--json",
         "-",
     ]
-    rc, stdout, stderr = await _run_process(argv, prompt, cwd, timeout)
+    run_env = os.environ.copy()
+    private_home = None
+    if mcp:
+        from app.backend_codex import CodexBackend, _write_private
+        from app.runtime_registry import _load_scope_mcp_servers
+
+        root = (state_dir or cwd).resolve()
+        root.mkdir(parents=True, exist_ok=True)
+        private_home = root / f".wf-codex-home-{uuid4().hex}"
+        private_home.mkdir(mode=0o700)
+        servers = _load_scope_mcp_servers(str(cwd))
+        backend = CodexBackend(model=model, cwd=str(cwd), mcp_servers=servers)
+        _write_private(private_home / "config.toml", backend._mcp_servers_toml() + "\n")
+        base_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
+        auth = base_home / "auth.json"
+        if auth.is_file():
+            (private_home / "auth.json").symlink_to(auth)
+        run_env["CODEX_HOME"] = str(private_home)
+    else:
+        argv.insert(argv.index("--ignore-rules"), "--ignore-user-config")
+    try:
+        rc, stdout, stderr = await _run_process(
+            argv, _prompt_with_rules(prompt, system_prompt), cwd, timeout, env=run_env
+        )
+    finally:
+        if private_home is not None:
+            shutil.rmtree(private_home)
     if rc != 0:
         return _failed("codex", model, stderr or stdout or f"exit code {rc}", stop_reason="timeout" if rc == 124 else "error")
     try:
         return parse_codex_output(stdout, model)
     except ValueError as error:
         return _failed("codex", model, str(error), stop_reason="invalid_output")
 
 
-async def run_claude(prompt: str, *, model: str, cwd: Path, timeout: float) -> AdapterResult:
+async def run_claude(
+    prompt: str, *, model: str, cwd: Path, timeout: float,
+    tools: str = "all", network: bool = True, mcp: bool = True,
+    system_prompt: str = "", state_dir: Path | None = None,
+) -> AdapterResult:
     binary = os.environ.get("WF_CLAUDE_BIN", "claude")
+    mcp_config = _write_claude_mcp_config(cwd, mcp)
     argv = [
         binary,
         "-p",
         "--model",
         model,
         "--output-format",
         "json",
         "--setting-sources",
         "",
         "--strict-mcp-config",
         "--mcp-config",
-        '{"mcpServers":{}}',
+        str(mcp_config),
         "--tools",
-        "",
+        _claude_tools(tools, network),
     ]
-    rc, stdout, stderr = await _run_process(argv, prompt, cwd, timeout)
+    if system_prompt.strip():
+        argv.extend(["--system-prompt", system_prompt.strip()])
+    try:
+        rc, stdout, stderr = await _run_process(argv, prompt, cwd, timeout)
+    finally:
+        mcp_config.unlink(missing_ok=True)
     if rc != 0:
         return _failed("claude", model, stderr or stdout or f"exit code {rc}", stop_reason="timeout" if rc == 124 else "error")
     try:
         return parse_claude_output(stdout, model)
     except ValueError as error:
         return _failed("claude", model, str(error), stop_reason="invalid_output")
 
 
-async def run_harness(prompt: str, *, model: str, cwd: Path, timeout: float) -> AdapterResult:
+async def run_harness(
+    prompt: str, *, model: str, cwd: Path, timeout: float,
+    tools: str = "all", network: bool = True, mcp: bool = True,
+    system_prompt: str = "", state_dir: Path | None = None,
+) -> AdapterResult:
     from app.harness.oneshot import run_oneshot
 
     try:
         row = await asyncio.wait_for(
-            run_oneshot(prompt=prompt, model=model, cwd=cwd), timeout=max(1.0, timeout)
+            run_oneshot(
+                prompt=prompt, model=model, cwd=cwd, tools_level=tools,
+                network=network, mcp=mcp, system_prompt=system_prompt,
+            ),
+            timeout=max(1.0, timeout),
         )
     except asyncio.TimeoutError:
         return _failed("harness", model, f"timed out after {timeout:g}s", stop_reason="timeout")
     except Exception as error:
         return _failed("harness", model, f"{type(error).__name__}: {error}", stop_reason="error")
     usage = row.get("usage") or {}
     return AdapterResult(
         text=str(row.get("text") or ""),
@@ -290,20 +375,34 @@ async def run_harness(prompt: str, *, model: str, cwd: Path, timeout: float) ->
             input_tokens=int(usage.get("input_tokens") or 0),
             output_tokens=int(usage.get("output_tokens") or 0),
         ),
         error=str(row.get("error") or ""),
     )
 
 
 async def run_adapter(
-    prompt: str, *, model: str, cwd: Path, timeout: float
+    prompt: str, *, model: str, cwd: Path, timeout: float,
+    tools: str = "all", network: bool = True, mcp: bool = True,
+    system_prompt: str = "", state_dir: Path | None = None,
 ) -> AdapterResult:
     from app.models import backend_for_model
 
     runtime = backend_for_model(model)
     if runtime == "codex":
-        return await run_codex(prompt, model=model, cwd=cwd, timeout=timeout)
+        return await run_codex(
+            prompt, model=model, cwd=cwd, timeout=timeout, tools=tools,
+            network=network, mcp=mcp, system_prompt=system_prompt,
+            state_dir=state_dir,
+        )
     if runtime == "claude":
-        return await run_claude(prompt, model=model, cwd=cwd, timeout=timeout)
+        return await run_claude(
+            prompt, model=model, cwd=cwd, timeout=timeout, tools=tools,
+            network=network, mcp=mcp, system_prompt=system_prompt,
+            state_dir=state_dir,
+        )
     if runtime == "harness":
-        return await run_harness(prompt, model=model, cwd=cwd, timeout=timeout)
+        return await run_harness(
+            prompt, model=model, cwd=cwd, timeout=timeout, tools=tools,
+            network=network, mcp=mcp, system_prompt=system_prompt,
+            state_dir=state_dir,
+        )
     return _failed(runtime, model, f"runtime '{runtime}' has no wf_run one-shot adapter", stop_reason="unsupported")
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index d93a2fdee..b651cbebf 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -7,16 +7,18 @@ import argparse
 import asyncio
 import ast
 import hashlib
 import inspect
 import json
 import os
 import re
 import shlex
+import shutil
+import subprocess
 import sys
 import urllib.error
 import urllib.parse
 import urllib.request
 from dataclasses import dataclass, field
 from pathlib import Path
 from typing import Any, Awaitable, Callable, Iterable
 
@@ -27,16 +29,23 @@ if str(ROOT) not in sys.path:
 from scripts.wf_adapters import AdapterResult, persist_turn_usage, run_adapter
 
 
 Adapter = Callable[..., Awaitable[AdapterResult]]
 UsageWriter = Callable[..., bool]
 ReadinessChecker = Callable[[str], Awaitable[dict]]
 _RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
 _SCHEMA_META = {"$schema", "$id", "title", "description", "default", "examples"}
+DEFAULT_WORKFLOW_MODULES: tuple[str, ...] = (
+    "communication-style",
+    "user-values",
+    "knowledge-and-context",
+    "memory-search",
+    "code-quality",
+)
 
 
 class Journal:
     def __init__(self, path: Path):
         self.path = path
         self.path.parent.mkdir(parents=True, exist_ok=True)
 
     def append(self, row: dict) -> None:
@@ -69,34 +78,37 @@ class Journal:
         return rows
 
 
 @dataclass(frozen=True)
 class WorkflowValue:
     data: Any
     value_id: str
     result_path: str
+    workspace_path: str = ""
     free_sources: frozenset[str] = field(default_factory=frozenset)
     verified_sources: frozenset[str] = field(default_factory=frozenset)
 
     def to_record(self) -> dict:
         return {
             "data": self.data,
             "value_id": self.value_id,
             "result_path": self.result_path,
+            "workspace_path": self.workspace_path,
             "free_sources": sorted(self.free_sources),
             "verified_sources": sorted(self.verified_sources),
         }
 
     @classmethod
     def from_record(cls, row: dict) -> "WorkflowValue":
         return cls(
             data=row.get("data"),
             value_id=str(row["value_id"]),
             result_path=str(row["result_path"]),
+            workspace_path=str(row.get("workspace_path") or ""),
             free_sources=frozenset(str(item) for item in row.get("free_sources") or []),
             verified_sources=frozenset(
                 str(item) for item in row.get("verified_sources") or []
             ),
         )
 
 
 class Budget:
@@ -250,42 +262,170 @@ async def _readiness(model: str) -> dict:
                 row = json.loads(response.read())
         except (OSError, urllib.error.URLError, json.JSONDecodeError):
             return {"state": "unknown"}
         return row if isinstance(row, dict) else {"state": "unknown"}
 
     return await asyncio.to_thread(request)
 
 
+async def _await_despite_cancellation(task: asyncio.Task) -> tuple[Any, int]:
+    cancellations = 0
+    current = asyncio.current_task()
+    while True:
+        try:
+            return await asyncio.shield(task), cancellations
+        except asyncio.CancelledError:
+            cancellations += 1
+            if current is not None:
+                current.uncancel()
+
+
 def _mem_available_bytes() -> int | None:
     try:
         for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
             if line.startswith("MemAvailable:"):
                 return int(line.split()[1]) * 1024
     except (OSError, ValueError, IndexError):
         return None
     return None
 
 
+def _current_branch(repository: Path) -> str:
+    result = subprocess.run(
+        ["git", "branch", "--show-current"],
+        cwd=repository, capture_output=True, text=True,
+    )
+    branch = result.stdout.strip()
+    if result.returncode != 0 or not branch:
+        detail = result.stderr.strip() or result.stdout.strip() or "detached HEAD"
+        raise RuntimeError(f"cannot resolve workflow workspace base branch: {detail}")
+    return branch
+
+
+_WORKSPACE_PRIVATE_TOPLEVEL = frozenset({
+    ".git", ".env", ".mcp.json", ".claude", ".codex", ".wf-mcp.json",
+    ".pytest_cache", "__pycache__",
+})
+
+
+def _workspace_files(worktree: Path) -> set[str]:
+    files: set[str] = set()
+    for root, dirs, names in os.walk(worktree):
+        relative_root = Path(root).relative_to(worktree)
+        dirs[:] = [
+            name for name in dirs
+            if name not in _WORKSPACE_PRIVATE_TOPLEVEL
+        ]
+        for name in names:
+            relative = relative_root / name
+            if any(part in _WORKSPACE_PRIVATE_TOPLEVEL for part in relative.parts):
+                continue
+            files.add(str(relative))
+    return files
+
+
+def _snapshot_worktree(
+    worktree: Path, destination: Path, initial_head: str, baseline_files: set[str],
+) -> None:
+    changed = subprocess.run(
+        ["git", "diff", "--name-only", "-z", initial_head, "--"],
+        cwd=worktree, check=True, capture_output=True,
+    ).stdout.split(b"\0")
+    local = subprocess.run(
+        ["git", "ls-files", "-m", "-o", "--exclude-standard", "-z"],
+        cwd=worktree, check=True, capture_output=True,
+    ).stdout.split(b"\0")
+    after_files = _workspace_files(worktree)
+    names = sorted(
+        {os.fsdecode(item) for item in changed + local if item}
+        | (after_files - baseline_files)
+    )
+    copied: list[str] = []
+    deleted: list[str] = []
+    destination.mkdir(parents=True, exist_ok=True)
+    root = worktree.resolve()
+    for name in names:
+        source = (worktree / name).resolve()
+        if source != root and root not in source.parents:
+            raise ValueError(f"workspace output escapes worktree: {name}")
+        if not source.is_file():
+            deleted.append(name)
+            continue
+        target = destination / name
+        target.parent.mkdir(parents=True, exist_ok=True)
+        shutil.copy2(source, target)
+        copied.append(name)
+    manifest = destination / "workspace.json"
+    manifest.write_text(json.dumps({"copied": copied, "deleted": deleted}, ensure_ascii=False))
+
+
+def _reset_prepared_worktree(repository: Path, prepared: Any) -> None:
+    from app.workspace import _reset_worktree_to_ref, repo_mutation_lock
+
+    with repo_mutation_lock(repository):
+        _reset_worktree_to_ref(
+            prepared.path, prepared.initial_head, str(repository)
+        )
+
+
+def _prepare_workspace_sync(
+    repository: Path, name: str, base_branch: str,
+) -> tuple[Any, set[str]]:
+    from app.workspace import create_worktree, discard_prepared_worktree
+
+    prepared = create_worktree(str(repository), name, "", base_branch)
+    try:
+        return prepared, _workspace_files(Path(prepared.path))
+    except BaseException:
+        discard_prepared_worktree(str(repository), prepared)
+        raise
+
+
+def _cleanup_workspace_sync(
+    repository: Path,
+    prepared: Any,
+    archive: Path,
+    baseline_files: set[str],
+) -> None:
+    from app.workspace import discard_prepared_worktree
+
+    snapshot_error = None
+    try:
+        _snapshot_worktree(
+            Path(prepared.path), archive, prepared.initial_head, baseline_files
+        )
+    except Exception as error:
+        snapshot_error = error
+    _reset_prepared_worktree(repository, prepared)
+    discard_prepared_worktree(str(repository), prepared)
+    if snapshot_error is not None:
+        raise snapshot_error
+
+
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
+        workspace_repo: Path | None = None,
+        workspace_base_branch: str = "",
+        pipeline_name: str = "default",
+        default_modules: Iterable[str] = DEFAULT_WORKFLOW_MODULES,
     ):
         if not _RUN_ID.fullmatch(run_id):
             raise ValueError("run_id must contain only letters, digits, dot, underscore, or dash")
         self.run_id = run_id
         self.run_dir = Path(run_dir)
         self.run_dir.mkdir(parents=True, exist_ok=True)
         self.steps_dir = self.run_dir / "steps"
         self.steps_dir.mkdir(exist_ok=True)
@@ -299,16 +439,33 @@ class WorkflowEngine:
         self.readiness_checker = readiness_checker or (_readiness if adapter is None else _allow_all)
         concurrency = max_concurrency or int(os.environ.get("WF_MAX_CONCURRENCY", "3"))
         self._semaphore = asyncio.Semaphore(max(1, concurrency))
         self._codex_semaphore = asyncio.Semaphore(2)
         self._state_lock = asyncio.Lock()
         self.budget = Budget(budget_usd, max_calls)
         self.scope = scope if scope is not None else os.environ.get("ORCHESTRA_SCOPE", "")
         self.task_id = task_id if task_id is not None else os.environ.get("ORCHESTRA_TASK_ID", "")
+        if workspace_repo is None and adapter is None:
+            from app.workspace import repo_root
+
+            self.workspace_repo = Path(repo_root(str(ROOT))).resolve()
+        else:
+            self.workspace_repo = (
+                Path(workspace_repo).resolve() if workspace_repo is not None else None
+            )
+        self.workspace_base_branch = workspace_base_branch or (
+            _current_branch(
+                ROOT if workspace_repo is None and adapter is None else self.workspace_repo
+            )
+            if self.workspace_repo is not None
+            else ""
+        )
+        self.pipeline_name = pipeline_name
+        self.default_modules = tuple(default_modules)
         self.session_id = f"wf:{run_id}"
         self.partial_reason = ""
         self._occurrences: dict[str, int] = {}
         self._completed: dict[str, WorkflowValue | None] = {}
         self._completed_reason: dict[str, str] = {}
         self._unknown_calls: set[str] = set()
         self._retry_state: dict[str, tuple[int, str]] = {}
         self._step_records: dict[str, dict] = {}
@@ -387,19 +544,36 @@ class WorkflowEngine:
         schema: dict | None = None,
         timeout: float = 300,
         loss_tolerant: bool = False,
         purpose: str = "work",
         inputs: Iterable[WorkflowValue] = (),
         escalate: bool = False,
         hard: bool = False,
         label: str = "",
+        tools: str = "all",
+        network: bool = True,
+        mcp: bool = True,
+        modules: Iterable[str] | None = None,
+        capability_reason: str = "",
     ) -> WorkflowValue | None:
         if purpose not in {"work", "verify", "synthesis"}:
             raise ValueError("purpose must be work, verify, or synthesis")
+        if tools not in {"all", "read"}:
+            raise ValueError("tools must be 'all' or 'read'")
+        downgraded = tools != "all" or not network or not mcp
+        if downgraded and not capability_reason.strip():
+            raise ValueError("restricted capabilities require capability_reason")
+        module_names = tuple(self.default_modules if modules is None else modules)
+        if any(not isinstance(name, str) or not name for name in module_names):
+            raise ValueError("modules must contain non-empty names")
+        from app.pipeline import build_prompt_modules
+
+        system_prompt = build_prompt_modules(self.pipeline_name, module_names)
+        effective_mcp = bool(mcp and tools == "all" and network)
         input_values = list(inputs)
         if any(not isinstance(item, WorkflowValue) for item in input_values):
             raise TypeError("inputs must contain WorkflowValue objects")
         free_sources = frozenset().union(*(item.free_sources for item in input_values))
         verified_sources = frozenset().union(
             *(item.verified_sources for item in input_values)
         )
         if purpose == "synthesis" and not free_sources.issubset(verified_sources):
@@ -421,16 +595,21 @@ class WorkflowEngine:
             )
         call_key = await self._call_key({
             "prompt": rendered,
             "models": candidates,
             "schema": schema,
             "purpose": purpose,
             "loss_tolerant": loss_tolerant,
             "label": label,
+            "tools": tools,
+            "network": bool(network),
+            "mcp": effective_mcp,
+            "modules": module_names,
+            "capability_reason": capability_reason.strip(),
         })
         if call_key in self._completed:
             if self._completed[call_key] is None:
                 self.partial_reason = self.partial_reason or self._completed_reason[call_key]
             return self._completed[call_key]
         if call_key in self._unknown_calls:
             self.partial_reason = self.partial_reason or "outcome_unknown"
             self.journal.append({
@@ -472,16 +651,17 @@ class WorkflowEngine:
             })
             return None
         scratch = self.run_dir / "calls" / call_key.replace(":", "-")
         scratch.mkdir(parents=True, exist_ok=True)
         current_prompt = rendered
         total_cost = 0.0
         final_data: Any = None
         result: AdapterResult | None = None
+        workspace_path = ""
         start_attempt, schema_error = self._retry_state.get(call_key, (0, ""))
         if schema_error and schema is not None:
             current_prompt = _schema_retry_prompt(rendered, schema_error, schema)
         if schema_error and start_attempt >= 3:
             self.partial_reason = self.partial_reason or "schema"
             self._finish(call_key, None, reason="schema")
             return None
         deferred_budget = False
@@ -493,52 +673,54 @@ class WorkflowEngine:
                     self.journal.append({
                         "event": "retry_deferred",
                         "call_key": call_key,
                         "reason": "budget",
                         "next_attempt": attempt,
                     })
                     break
                 self.budget.dispatched_calls += 1
-                self.journal.append({
-                    "event": "dispatched",
-                    "call_key": call_key,
-                    "attempt": attempt + 1,
-                    "model": selected,
-                    "runtime": runtime,
-                })
             semaphore = self._codex_semaphore if runtime == "codex" else self._semaphore
+            event_id = f"wf:{self.run_id}:{call_key}:{attempt + 1}"
             async with self._semaphore:
                 if semaphore is self._semaphore:
-                    result = await self.adapter(
-                        current_prompt, model=selected, cwd=scratch, timeout=timeout
+                    result, workspace_path = await self._run_attempt(
+                        current_prompt,
+                        model=selected,
+                        runtime=runtime,
+                        scratch=scratch,
+                        timeout=timeout,
+                        call_key=call_key,
+                        attempt=attempt + 1,
+                        event_id=event_id,
+                        tools=tools,
+                        network=bool(network),
+                        mcp=effective_mcp,
+                        system_prompt=system_prompt,
+                        modules=module_names,
+                        capability_reason=capability_reason.strip(),
                     )
                 else:
                     async with semaphore:
-                        result = await self.adapter(
-                            current_prompt, model=selected, cwd=scratch, timeout=timeout
+                        result, workspace_path = await self._run_attempt(
+                            current_prompt,
+                            model=selected,
+                            runtime=runtime,
+                            scratch=scratch,
+                            timeout=timeout,
+                            call_key=call_key,
+                            attempt=attempt + 1,
+                            event_id=event_id,
+                            tools=tools,
+                            network=bool(network),
+                            mcp=effective_mcp,
+                            system_prompt=system_prompt,
+                            modules=module_names,
+                            capability_reason=capability_reason.strip(),
                         )
-            event_id = f"wf:{self.run_id}:{call_key}:{attempt + 1}"
-            if self.usage_writer is not None:
-                try:
-                    self.usage_writer(
-                        result=result,
-                        event_id=event_id,
-                        session_id=self.session_id,
-                        scope=self.scope,
-                        task_id=self.task_id,
-                    )
-                except Exception as error:
-                    self.journal.append({
-                        "event": "accounting_failed",
-                        "call_key": call_key,
-                        "attempt": attempt + 1,
-                        "error": f"{type(error).__name__}: {error}",
-                    })
-                    raise RuntimeError(f"turn_usage accounting failed: {error}") from error
             realized = float(result.cost_usd or 0)
             total_cost += realized
             async with self._state_lock:
                 self.budget.spent_usd += realized
                 self.journal.append({
                     "event": "attempt_finished",
                     "call_key": call_key,
                     "attempt": attempt + 1,
@@ -571,58 +753,189 @@ class WorkflowEngine:
         if deferred_budget:
             return None
         if result is None or not result.ok or schema_error:
             reason = "budget" if result is None else ("schema" if schema_error else result.stop_reason)
             if reason == "budget":
                 self.partial_reason = "budget"
             else:
                 self.partial_reason = self.partial_reason or reason
-            self._finish(call_key, None, reason=reason, cost_usd=total_cost)
+            self._finish(
+                call_key,
+                None,
+                reason=reason,
+                cost_usd=total_cost,
+                error=result.error if result is not None else "",
+            )
             return None
 
         own_id = call_key
         output_free = free_sources | ({own_id} if runtime == "harness" else set())
         output_verified = verified_sources | (free_sources if purpose == "verify" else set())
         step_path = self.steps_dir / f"{call_key.replace(':', '-')}.json"
         value = WorkflowValue(
             data=final_data,
             value_id=own_id,
             result_path=str(step_path),
+            workspace_path=workspace_path,
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
 
+    async def _run_attempt(
+        self,
+        prompt: str,
+        *,
+        model: str,
+        runtime: str,
+        scratch: Path,
+        timeout: float,
+        call_key: str,
+        attempt: int,
+        event_id: str,
+        tools: str,
+        network: bool,
+        mcp: bool,
+        system_prompt: str,
+        modules: tuple[str, ...],
+        capability_reason: str,
+    ) -> tuple[AdapterResult, str]:
+        prepared = None
+        cwd = scratch
+        archive = ""
+        baseline_files: set[str] = set()
+        if tools == "all" and self.workspace_repo is not None:
+            name = f"wf-{self.run_id[:24]}-{call_key[:12]}-a{attempt}"
+            prepare_task = asyncio.create_task(asyncio.to_thread(
+                _prepare_workspace_sync,
+                self.workspace_repo,
+                name,
+                self.workspace_base_branch,
+            ))
+            try:
+                (prepared, baseline_files), cancellations = (
+                    await _await_despite_cancellation(prepare_task)
+                )
+            except BaseException:
+                async with self._state_lock:
+                    self.budget.dispatched_calls -= 1
+                    self.journal.append({
+                        "event": "prepare_failed",
+                        "call_key": call_key,
+                        "attempt": attempt,
+                    })
+                raise
+            if cancellations:
+                cleanup_task = asyncio.create_task(asyncio.to_thread(
+                    _cleanup_workspace_sync,
+                    self.workspace_repo,
+                    prepared,
+                    self.run_dir / "cancelled-workspaces" / name,
+                    baseline_files,
+                ))
+                await _await_despite_cancellation(cleanup_task)
+                async with self._state_lock:
+                    self.budget.dispatched_calls -= 1
+                    self.journal.append({
+                        "event": "prepare_cancelled",
+                        "call_key": call_key,
+                        "attempt": attempt,
+                    })
+                raise asyncio.CancelledError
+            cwd = Path(prepared.path)
+            archive_path = (
+                self.run_dir / "workspaces" / call_key.replace(":", "-") / f"attempt-{attempt}"
+            )
+            archive = str(archive_path)
+        async with self._state_lock:
+            self.journal.append({
+                "event": "dispatched",
+                "call_key": call_key,
+                "attempt": attempt,
+                "model": model,
+                "runtime": runtime,
+                "tools": tools,
+                "network": network,
+                "mcp": mcp,
+                "modules": list(modules),
+                "system_prompt_bytes": len(system_prompt.encode()),
+                "capability_reason": capability_reason,
+            })
+        try:
+            result = await self.adapter(
+                prompt,
+                model=model,
+                cwd=cwd,
+                timeout=timeout,
+                tools=tools,
+                network=network,
+                mcp=mcp,
+                system_prompt=system_prompt,
+                state_dir=scratch,
+            )
+            if self.usage_writer is not None:
+                try:
+                    self.usage_writer(
+                        result=result,
+                        event_id=event_id,
+                        session_id=self.session_id,
+                        scope=self.scope,
+                        task_id=self.task_id,
+                    )
+                except Exception as error:
+                    self.journal.append({
+                        "event": "accounting_failed",
+                        "call_key": call_key,
+                        "attempt": attempt,
+                        "error": f"{type(error).__name__}: {error}",
+                    })
+                    raise RuntimeError(f"turn_usage accounting failed: {error}") from error
+            return result, archive
+        finally:
+            if prepared is not None:
+                cleanup_task = asyncio.create_task(asyncio.to_thread(
+                    _cleanup_workspace_sync,
+                    self.workspace_repo,
+                    prepared,
+                    Path(archive),
+                    baseline_files,
+                ))
+                _, cancellations = await _await_despite_cancellation(cleanup_task)
+                if cancellations:
+                    raise asyncio.CancelledError
+
     def _finish(
         self,
         call_key: str,
         value: WorkflowValue | None,
         *,
         reason: str,
         cost_usd: float = 0,
         model: str = "",
         runtime: str = "",
+        error: str = "",
     ) -> None:
         row = {
             "event": "completed",
             "call_key": call_key,
             "reason": reason,
             "cost_usd": cost_usd,
             "model": model,
             "runtime": runtime,
+            "error": error,
             "value": value.to_record() if value is not None else None,
         }
         self.journal.append(row)
         self._completed[call_key] = value
         self._completed_reason[call_key] = reason
         self._step_records[call_key] = row
 
     @staticmethod
@@ -681,21 +994,27 @@ class WorkflowEngine:
             "partial_reason": self.partial_reason or None,
             "spent_usd": round(self.budget.spent_usd, 9),
             "budget_usd": self.budget.maximum_usd,
             "dispatched_calls": self.budget.dispatched_calls,
             "steps": [
                 {
                     "call_key": key,
                     "reason": row.get("reason"),
+                    "error": row.get("error") or None,
                     "result_path": (
                         row.get("value", {}).get("result_path")
                         if isinstance(row.get("value"), dict)
                         else None
                     ),
+                    "workspace_path": (
+                        row.get("value", {}).get("workspace_path")
+                        if isinstance(row.get("value"), dict)
+                        else None
+                    ),
                 }
                 for key, row in self._step_records.items()
             ],
             "result": _jsonable(self.result),
             "resume_command": resume,
             "wake_message": f"wf_run {self.run_id} interrupted; resume with: {resume}",
         }
         self._atomic_json(self.run_dir / "manifest.json", manifest)
diff --git a/tests/test_wf_run.py b/tests/test_wf_run.py
index 59f9e6e7a..5ad06795b 100644
--- a/tests/test_wf_run.py
+++ b/tests/test_wf_run.py
@@ -1,10 +1,11 @@
 import json
 import sqlite3
+import subprocess
 from pathlib import Path
 
 import pytest
 
 from scripts.wf_adapters import (
     AdapterResult,
     Usage,
     parse_claude_output,
@@ -12,89 +13,402 @@ from scripts.wf_adapters import (
     persist_turn_usage,
 )
 from scripts.wf_run import WorkflowEngine, validate_pilot_manifest
 
 
 FIXTURES = Path(__file__).parent / "fixtures" / "wf"
 
 
+def _git_repo(path: Path) -> Path:
+    path.mkdir()
+    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
+    subprocess.run(["git", "config", "user.email", "wf@example.invalid"], cwd=path, check=True)
+    subprocess.run(["git", "config", "user.name", "WF Test"], cwd=path, check=True)
+    (path / "seed.txt").write_text("seed\n")
+    subprocess.run(["git", "add", "seed.txt"], cwd=path, check=True)
+    subprocess.run(["git", "commit", "-m", "seed"], cwd=path, check=True, capture_output=True)
+    return path
+
+
 def _result(text: str, *, cost: float = 0.01, runtime: str = "codex", model: str = "gpt-5.6-luna"):
     return AdapterResult(
         text=text,
         runtime=runtime,
         model=model,
         ok=True,
         stop_reason="end_turn",
         cost_usd=cost,
         usage=Usage(input_tokens=10, output_tokens=2),
     )
 
 
+def _engine(*args, **kwargs):
+    kwargs.setdefault("default_modules", ())
+    return WorkflowEngine(*args, **kwargs)
+
+
 @pytest.mark.asyncio
 async def test_resume_ignores_a_truncated_tail_and_continues_after_completed_calls(tmp_path):
     first_calls = []
 
     async def first_adapter(prompt, **_kwargs):
         first_calls.append(prompt)
         return _result("first-result")
 
-    engine = WorkflowEngine("resume-case", tmp_path, budget_usd=2, adapter=first_adapter)
+    engine = _engine("resume-case", tmp_path, budget_usd=2, adapter=first_adapter)
     first = await engine.agent("first", model="luna")
     assert first.data == "first-result"
     with engine.journal.path.open("ab") as fh:
         fh.write(b'{"event":"completed","call_key":')
 
     resumed_calls = []
 
     async def resumed_adapter(prompt, **_kwargs):
         resumed_calls.append(prompt)
         return _result("second-result")


## LATER FIX 17a7d398b9 (32.7 days later): V-756: #V-756: fix repeated workflow prompts and wakes
lines of origin it changed/deleted: 21
(code only, capped 400 lines)

V-756: #V-756: fix repeated workflow prompts and wakes

Squashed commits:
- #V-756: fix repeated workflow prompts and wakes
- #V-756: import workflow runner in regression test
- #V-756: record merge gate verification

Orchestra-Operation: a3291105-3158-41af-aecd-f325f21e867f


diff --git a/app/bg_jobs.py b/app/bg_jobs.py
index c88f5ca4d..147005f5b 100644
--- a/app/bg_jobs.py
+++ b/app/bg_jobs.py
@@ -478,38 +478,52 @@ class BgJobManager:
             lambda finished: (
                 self._tasks.pop(job_id, None)
                 if self._tasks.get(job_id) is finished
                 else None
             )
         )
 
     async def cancel(self, job_id: str) -> dict:
+        row = bg_get_job(job_id) or {}
         ok = bg_cancel_job(job_id)
         if not ok:
             return {"error": "job not found or not active"}
         task = self._tasks.pop(job_id, None)
         if task and not task.done():
             task.cancel()
         proc = self._procs.pop(job_id, None)
         if proc:
             await _kill_proc(proc)
+        if row.get("type") == "run":
+            await self._interrupt_run_notify(
+                job_id, row.get("message") or "Background run", row.get("target_name") or "?",
+                row.get("target_scope") or "",
+                reason="Отменён вызывающим агентом; повторный запуск не выполнялся.",
+                output=row.get("last_output") or "",
+            )
         return {"ok": True}
 
     async def cancel_by_session(self, session_id: str) -> None:
         active = bg_get_jobs(session_id=session_id, active_only=True)
         job_ids = [j["id"] for j in active]
         cancelled_count = bg_cancel_by_session(session_id)
         for jid in job_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
             proc = self._procs.pop(jid, None)
             if proc:
                 await _kill_proc(proc)
+            row = next((job for job in active if job["id"] == jid), {})
+            if row.get("type") == "run":
+                await self._report_undelivered_job(
+                    jid, row.get("target_name") or "?", row.get("target_scope") or "",
+                    "target session stopped while its run job was active",
+                )
         if cancelled_count:
             logger.info(f"bg_jobs: cancelled {cancelled_count} jobs for session {session_id}")
 
     async def restore_from_db(self) -> None:
         legacy_idle = bg_cancel_removed_idle()
         if legacy_idle:
             logger.info("bg_jobs: cancelled %s legacy idle watches (type removed)", legacy_idle)
         cleaned = bg_cleanup_old(24)
@@ -521,16 +535,27 @@ class BgJobManager:
                 "bg_jobs: reset %s interrupted wake jobs",
                 len(wake_reset_ids),
             )
         expired_ids = bg_expire_overdue()
         for jid in expired_ids:
             task = self._tasks.pop(jid, None)
             if task and not task.done():
                 task.cancel()
+            row = bg_get_job(jid)
+            if row and row.get("type") == "run":
+                timeout = max(
+                    1,
+                    (datetime.fromisoformat(row["expires_at"])
+                     - datetime.fromisoformat(row["created_at"])).total_seconds(),
+                )
+                await self._expire_notify(
+                    jid, row["message"], row["target_name"], row["target_scope"],
+                    timeout, row.get("last_output") or "",
+                )
         reset_ids = bg_reset_stale_triggering()
         if reset_ids:
             logger.info(f"bg_jobs: reset {len(reset_ids)} stale triggering jobs")
         interrupted_delivery = set(reset_ids)
         active = bg_get_active_all()
         restored = 0
         for row in active:
             if row["id"] in self._tasks:
@@ -620,129 +645,128 @@ class BgJobManager:
         if not session:
             logger.warning(
                 f"bg_job {job_id}: target session {target_session_id} "
                 f"(name at creation: {target_name!r}) not found"
             )
             return None, "target session not found"
         return session, ""
 
-    async def _trigger(self, job_id: str, message: str,
-                       target_name: str, target_scope: str, output: str = "") -> None:
-        claimed = bg_claim_trigger(job_id)
-        if not claimed:
-            return
+    async def _notify_job_target(
+        self, job_id: str, outcome: str, body: str,
+        target_name: str, target_scope: str,
+    ) -> str | None:
         try:
             session, failure = await self._load_job_target(job_id, target_name)
             if not session:
-                bg_fail_job(job_id, failure)
-                return
-            body = f"[Background job completed] {message}"
-            if output:
-                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+                raise RuntimeError(failure or "target session not found")
             self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "completed", body)
+            injected = self._terminal_message(job_id, outcome, body)
             await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
+                session.id, injected, provenance=injected.provenance,
             )
-            bg_finish_trigger(job_id, output)
-            logger.info(f"bg_job {job_id}: triggered → {target_name}")
-        except Exception as e:
-            bg_fail_job(job_id, str(e)[:500])
-            logger.error(f"bg_job {job_id}: trigger failed: {e}")
-            # Факт в состоянии джоба виден только глазами в дашборде — это не уведомление.
-            # Адресат — оркестратор scope: он ставил джоб, ему и решать (#30).
-            from app.notify import report_undelivered
+            return None
+        except Exception as error:
+            reason = f"{type(error).__name__}: {error}"
+            logger.error("bg_job %s: %s notification failed: %s", job_id, outcome, reason)
+            await self._report_undelivered_job(
+                job_id, target_name, target_scope, reason,
+            )
+            return reason
+
+    async def _report_undelivered_job(
+        self, job_id: str, target_name: str, target_scope: str, reason: str,
+    ) -> None:
+        from app.notify import report_undelivered
 
+        try:
             await report_undelivered(
                 self._session_manager,
                 scope=target_scope,
                 worker=target_name,
-                what=f"результат фоновой задачи {job_id}",
-                reason=f"{type(e).__name__}: {e}",
+                what=f"result of background job {job_id}",
+                reason=reason,
                 dedupe_key=f"bgjob:{job_id}",
             )
+        except Exception as fallback_error:
+            logger.error(
+                "bg_job %s: undelivered report failed (%s): %s",
+                job_id, type(fallback_error).__name__, fallback_error,
+            )
+
+    async def _trigger(self, job_id: str, message: str,
+                       target_name: str, target_scope: str, output: str = "") -> None:
+        claimed = bg_claim_trigger(job_id)
+        if not claimed:
+            return
+        body = f"[Background job completed] {message}"
+        if output:
+            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "completed", body, target_name, target_scope,
+        )
+        if failure is None:
+            bg_finish_trigger(job_id, output)
+            logger.info(f"bg_job {job_id}: triggered → {target_name}")
+        else:
+            bg_fail_job(job_id, failure)
 
     def _expire(self, job_id: str) -> None:
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
 
     async def _expire_notify(self, job_id, message, target_name, target_scope,
                              timeout, output=""):
         """Timeout for a `run` job: NOTIFY the worker instead of expiring silently.
         Without this, a hung process leaves the worker waiting forever."""
         bg_expire_job(job_id)
         self._procs.pop(job_id, None)
         dur = f"{round(timeout / 60, 1)} min" if timeout >= 60 else f"{int(timeout)}s"
         err = (f"{message}\n[TIMEOUT] killed after {dur} — no completion. "
                f"The process produced no output or hung. Check the target tool "
                f"(codex auth/proxy/sandbox) and retry.")
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job TIMED OUT] {err}"
-            if output:
-                body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "timed_out", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job TIMED OUT] {err}"
+        if output:
+            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "timed_out", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(f"bg_job {job_id}: TIMED OUT after {dur} → notified {target_name}")
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: timeout-notify failed: {e}")
 
     async def _fail_notify(self, job_id, message, target_name, target_scope,
                            error, output=""):
         """Persist a failed run and wake the waiting agent with an explicit failure."""
         bg_fail_job(job_id, error)
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job FAILED] {message}\n{error}"
-            if output:
-                body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "failed", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job FAILED] {message}\n{error}"
+        if output:
+            body += f"\n\nOutput (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "failed", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(f"bg_job {job_id}: FAILED → notified {target_name}: {error}")
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: failure-notify failed: {e}")
 
-    async def _interrupt_run_notify(self, job_id, message, target_name, target_scope):
-        reason = "Прерван рестартом сервиса, повторный запуск не выполнялся."
+    async def _interrupt_run_notify(
+        self, job_id, message, target_name, target_scope,
+        reason="Прерван рестартом сервиса, повторный запуск не выполнялся.",
+        output="",
+    ):
         bg_fail_job(job_id, reason)
-        try:
-            session, _failure = await self._load_job_target(job_id, target_name)
-            if not session:
-                return
-            body = f"[Background job INTERRUPTED] {message}\n{reason}"
-            self._restore_report_provenance(session)
-            injected = self._terminal_message(job_id, "interrupted", body)
-            await self._session_manager.send(
-                session.id,
-                injected,
-                provenance=injected.provenance,
-            )
+        body = f"[Background job INTERRUPTED] {message}\n{reason}"
+        if output:
+            body += f"\n\nPartial output (last 3000 chars):\n{output[-3000:]}"
+        failure = await self._notify_job_target(
+            job_id, "interrupted", body, target_name, target_scope,
+        )
+        if failure is None:
             logger.warning(
-                "bg_job %s: interrupted by service restart → notified %s",
+                "bg_job %s: interrupted → notified %s",
                 job_id, target_name,
             )
-        except Exception as e:
-            logger.error(f"bg_job {job_id}: restart-interrupt notify failed: {e}")
 
     def _fail_if_active(self, job_id: str, error: str) -> None:
         bg_fail_job_if_active(job_id, error)
 
     # ── Runners ──
 
     async def _run_merge_watch(self, job_id, operation_id, message,
                                target_name, target_scope, timeout):
@@ -1133,24 +1157,38 @@ class BgJobManager:
                     job_id, message, target_name, target_scope,
                     validation_error, full_output,
                 )
                 return
 
             trigger_msg = f"{message}\nExit code: 0"
             await self._trigger(job_id, trigger_msg, target_name, target_scope, full_output)
         except asyncio.TimeoutError:
+            kill_error = ""
             if proc:
-                await _kill_proc(proc)
-            await self._expire_notify(job_id, message, target_name, target_scope,
-                                      timeout, "".join(output_buf))
+                try:
+                    await _kill_proc(proc)
+                except Exception as error:
+                    kill_error = f"; process kill failed: {type(error).__name__}: {error}"
+            output = "".join(output_buf)
+            if kill_error:
+                output += f"\n{kill_error}"
+            await self._expire_notify(
+                job_id, message, target_name, target_scope, timeout,
+                output,
+            )
+            if kill_error:
+                logger.error("bg_job %s: %s", job_id, kill_error.lstrip("; "))
         except asyncio.CancelledError:
             pass
         except Exception as e:
-            bg_fail_job(job_id, str(e)[:500])
+            await self._fail_notify(
+                job_id, message, target_name, target_scope,
+                f"{type(e).__name__}: {e}", "".join(output_buf),
+            )
         finally:
             if reader_task and not reader_task.done():
                 reader_task.cancel()
                 await asyncio.gather(reader_task, return_exceptions=True)
             self._procs.pop(job_id, None)
             if proc:
                 await _kill_proc(proc)
                 transport = getattr(proc, "_transport", None)
diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index a490e303e..49a76f9b8 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -106,16 +106,20 @@ class WorkflowValue:
             workspace_path=str(row.get("workspace_path") or ""),
             free_sources=frozenset(str(item) for item in row.get("free_sources") or []),
             verified_sources=frozenset(
                 str(item) for item in row.get("verified_sources") or []
             ),
         )
 
 
+class WorkspacePreparationError(RuntimeError):
+    pass
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
@@ -492,29 +496,37 @@ class WorkflowEngine:
                 self.budget.spent_usd += float(row.get("cost_usd") or 0)
             elif event == "schema_invalid":
                 call_key = str(row.get("call_key") or "")
                 last_state[call_key] = "schema_invalid"
                 self._retry_state[call_key] = (
                     int(row.get("next_attempt") or 0),
                     str(row.get("error") or "schema validation failed"),
                 )
+            elif event == "prepare_failed":
+                call_key = str(row.get("call_key") or "")
+                last_state[call_key] = "prepare_failed"
+                self.budget.dispatched_calls = max(0, self.budget.dispatched_calls - 1)
+                self._step_records[call_key] = {
+                    **row, "reason": "prepare_failed", "value": None,
+                }
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
-            if call_key not in self._completed and last_state.get(call_key) != "schema_invalid"
+            if call_key not in self._completed
+            and last_state.get(call_key) not in {"schema_invalid", "prepare_failed"}
         }
         if self._unknown_calls:
             self.budget.spent_usd = max(self.budget.spent_usd, self.budget.maximum_usd)
 