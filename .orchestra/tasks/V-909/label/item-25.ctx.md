# Context for item-25

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/harness/oneshot.py b/app/harness/oneshot.py
index 977d314bb..82480ff34 100644
--- a/app/harness/oneshot.py
+++ b/app/harness/oneshot.py
@@ -1,82 +1,95 @@
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
         run_oneshot(prompt=os.sys.stdin.read(), model=args.model, cwd=args.cwd.resolve())
     )
     print(json.dumps(row, ensure_ascii=False))
     return 0 if row["ok"] else 1
 
 
 if __name__ == "__main__":
     raise SystemExit(main())
diff --git a/app/pipeline.py b/app/pipeline.py
index 02f11b94c..d5cc57f6a 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -548,73 +548,80 @@ def known_roles(pipeline_name: str) -> list[str]:
     """Отсортированный список имён ролей пайплайна."""
     return sorted(load_pipeline(pipeline_name).roles)
 
 
 # ── Резолв путей промпта (полная изоляция: только .orchestra/pipelines/<name>/prompts/) ─
 
 def prompt_path(pipeline_name: str, rel: str) -> Path:
     """Путь к слою промпта. ВСЕГДА внутри ``.orchestra/pipelines/<name>/prompts/``.
 
     ``rel`` — элемент prompt_layers (``base.md``, ``roles/coder.md``, ``_pipeline.md``).
     Единственный источник — ``.orchestra/pipelines/<name>/prompts/`` (app/prompts/ удалён).
     """
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
 
     После слоёв роли инлайнятся ``modules`` — переиспользуемые блоки промпта из
     ``prompts/modules/{m}.md`` (та же изоляция). Отсутствующий модуль пропускается с
     warning (роль не должна падать из-за недостающего блока).
 
     :raises FileNotFoundError: если манифест пайплайна отсутствует (на Этапе 3 manager
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
 
     1) ``parent_pipeline`` (от родителя при спавне) — главный источник: дети
        наследуют пайплайн родителя.
     2) пусто/корневой оркестратор → :data:`DEFAULT_PIPELINE`.
 
     Один пайплайн на дерево агентов — в середине цепочки сменить нельзя. Полная
     логика (чтение колонки sessions.pipeline) — Этап 7; здесь зафиксирована
     сигнатура и базовое поведение наследования.
     """
     if parent_pipeline:
         return parent_pipeline
     return DEFAULT_PIPELINE
 
diff --git a/scripts/wf_adapters.py b/scripts/wf_adapters.py
index ff9c3f9b4..42f5a0046 100644
--- a/scripts/wf_adapters.py
+++ b/scripts/wf_adapters.py
@@ -1,32 +1,35 @@
 #!/usr/bin/env python3
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
 
 
 @dataclass(frozen=True)
 class AdapterResult:
     text: str
     runtime: str
     model: str
     ok: bool
     stop_reason: str
     cost_usd: float | None
     usage: Usage = field(default_factory=Usage)
     cost_unaccounted: bool = False
@@ -143,50 +146,51 @@ def persist_turn_usage(
 
     return turn_usage_add(
         event_id=event_id,
         session_id=session_id,
         scope=scope,
         task_id=task_id,
         runtime=result.runtime,
         model=result.model,
         ok=result.ok,
         stop_reason=result.stop_reason,
         cost_usd=result.cost_usd,
         cost_unaccounted=result.cost_unaccounted,
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
     except asyncio.TimeoutError:
         if proc.returncode is None:
             try:
                 os.killpg(proc.pid, signal.SIGTERM)
             except (ProcessLookupError, PermissionError):
                 pass
             try:
                 await asyncio.wait_for(proc.wait(), 3)
             except asyncio.TimeoutError:
                 if proc.returncode is None:
                     try:
                         os.killpg(proc.pid, signal.SIGKILL)
@@ -197,113 +201,208 @@ async def _run_process(
     return (
         int(proc.returncode or 0),
         stdout.decode("utf-8", errors="replace"),
         stderr.decode("utf-8", errors="replace"),
     )
 
 
 def _failed(runtime: str, model: str, reason: str, *, stop_reason: str) -> AdapterResult:
     return AdapterResult(
         text="",
         runtime=runtime,
         model=model,
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
         runtime="harness",
         model=model,
         ok=bool(row.get("ok")),
         stop_reason=str(row.get("stop_reason") or "error"),
         cost_usd=float(row.get("cost_usd") or 0),
         usage=Usage(
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
@@ -1,54 +1,63 @@
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
+import shutil
+import subprocess
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
@@ -57,58 +66,61 @@ class Journal:
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
@@ -238,89 +250,234 @@ async def _allow_all(_model: str) -> dict:
 
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
@@ -375,74 +532,96 @@ class WorkflowEngine:
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
 
@@ -460,97 +639,100 @@ class WorkflowEngine:
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
+        workspace_path = ""
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
@@ -559,82 +741,213 @@ class WorkflowEngine:
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
@@ -669,45 +982,51 @@ class WorkflowEngine:
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
diff --git a/tests/test_wf_run.py b/tests/test_wf_run.py
index 59f9e6e7a..5ad06795b 100644
--- a/tests/test_wf_run.py
+++ b/tests/test_wf_run.py
@@ -1,532 +1,1049 @@
 import json
 import sqlite3
+import subprocess
 from pathlib import Path
 
 import pytest
 
 from scripts.wf_adapters import (
     AdapterResult,
     Usage,
     parse_claude_output,
     parse_codex_output,
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
 
-    resumed = WorkflowEngine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
+    resumed = _engine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
     cached = await resumed.agent("first", model="luna")
     second = await resumed.agent("second", model="luna")
 
     assert cached.data == "first-result"
     assert second.data == "second-result"
     assert resumed_calls == ["second"]
-    replay = WorkflowEngine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
+    replay = _engine("resume-case", tmp_path, budget_usd=2, adapter=resumed_adapter)
     assert (await replay.agent("first", model="luna")).data == "first-result"
     assert (await replay.agent("second", model="luna")).data == "second-result"
     assert resumed_calls == ["second"]
 
 
 @pytest.mark.asyncio
 async def test_budget_exhaustion_returns_none_and_marks_manifest_partial(tmp_path):
     calls = []
 


## Later history of the touched files on main (after this commit)

18 later commits touch these paths; the first 40 (oldest first):
fa3657e78 2026-09-06 промпты: memory-search и knowledge-and-context слиты в модуль knowledge, мёртвый семантический поиск выкинут
5f8894ec9 2026-09-07 #532: enforce role and persistent worker tool exclusions at MCP dispatch
360c846b7 2026-09-12 V-555: #V-555: replace retired fan launcher with dynamic workflows
a8d2e20ad 2026-09-17 V-582: #V-582: харнес-маршруты из живого каталога, допуск по данным провайдера
bbfd3641c 2026-09-22 V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели
038f06b7b 2026-10-05 V-720: #V-720: add one-call dynamic workflows
382660ab4 2026-10-06 V-738: #V-738: add staged dynamic workflow execution
25eb55af9 2026-10-06 V-739: #V-739: curate model catalog and preserve session compatibility
17a7d398b 2026-10-07 V-756: #V-756: fix repeated workflow prompts and wakes
b02e52f23 2026-10-08 V-757: #V-757: add Claude Haiku 5.5
023861fce 2026-10-08 V-776: #V-776: add readable dynamic workflow cards
e47c66866 2026-10-08 V-780: #V-780: support dynamic workflows from linked worktrees
62e76da50 2026-10-08 V-782: shared workflow admission scheduler and agent cgroup isolation
11e7581b7 2026-10-09 V-790: wf_run proceeds without admission when scheduler route is absent (404)
da86af311 2026-10-09 V-794: pre-approve the level's tools for Claude workflow calls (Bash stays closed)
62174b96b 2026-10-09 V-800: #V-800: route Claude API credits only to chosen workflows
84de265c8 2026-10-11 V-814: #V-814: fix schema workflow retries and response evidence
4bd9c2eaf 2026-10-14 V-821: #V-821: sparse worker worktrees for all projects: manifest rule, task-switch retarget, merge refusal with fix, converter, prompt, tests

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### fa3657e78 промпты: memory-search и knowledge-and-context слиты в модуль knowledge, мёртвый семантический поиск выкинут

diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index b651cbebf..7788ac7c4 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -35,12 +35,11 @@ ReadinessChecker = Callable[[str], Awaitable[dict]]
 _RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
 _SCHEMA_META = {"$schema", "$id", "title", "description", "default", "examples"}
 DEFAULT_WORKFLOW_MODULES: tuple[str, ...] = (
     "communication-style",
     "user-values",
-    "knowledge-and-context",
-    "memory-search",
+    "knowledge",
     "code-quality",
 )
 
 
 class Journal:
diff --git a/tests/test_wf_run.py b/tests/test_wf_run.py
index 5ad06795b..999111ca5 100644
--- a/tests/test_wf_run.py
+++ b/tests/test_wf_run.py
@@ -169,12 +169,11 @@ def test_default_workflow_module_interface_is_frozen():
     from scripts.wf_run import DEFAULT_WORKFLOW_MODULES
 
     assert DEFAULT_WORKFLOW_MODULES == (
         "communication-style",
         "user-values",
-        "knowledge-and-context",
-        "memory-search",
+        "knowledge",
         "code-quality",
     )
 
 
 @pytest.mark.asyncio
### 5f8894ec9 #532: enforce role and persistent worker tool exclusions at MCP dispatch

diff --git a/app/pipeline.py b/app/pipeline.py
index d5cc57f6a..8ee19609f 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -17,10 +17,11 @@ from typing import Literal, Union
 
 import yaml
 from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
 
 from app.models import ALIASES, MODELS
+from app.tool_scoping import parse_disabled_tools
 
 logger = logging.getLogger(__name__)
 
 # Корень с пайплайнами: <repo>/.orchestra/pipelines/. В гите только default.
 PIPELINES_DIR = Path(__file__).parent.parent / ".orchestra" / "pipelines"
@@ -220,10 +221,12 @@ class RoleSpec(BaseModel):
     """
     model_config = ConfigDict(extra="forbid")
     kind: Kind
     label: str
     order: int = 100
+    disabled_tools: list[str] = Field(default_factory=list)
+    _disabled_tools_valid = field_validator("disabled_tools", mode="before")(parse_disabled_tools)
     can_spawn: list[str] = Field(default_factory=list)  # "*" = любая роль; [] = терминал
     allow_unrouted_workers: bool = False
     # Модули — переиспользуемые блоки промпта (prompts/modules/{m}.md), инлайнятся
     # в system_prompt после слоёв роли. Пусто → ничего не добавляется.
     modules: list[str] = Field(default_factory=list)
@@ -347,10 +350,11 @@ class ResolvedRole(BaseModel):
     pipeline: str
     kind: Kind
     label: str
     order: int
     can_spawn: list[str]
+    disabled_tools: list[str] = Field(default_factory=list)
     allow_unrouted_workers: bool
     modules: list[str]
     model: str
     effort: EffortSpec | None
     skills: AllOrList
@@ -505,11 +509,11 @@ def resolve_role(pipeline: PipelineConfig, role: str) -> ResolvedRole:
                    else d.prompt_layers.worker)
     return ResolvedRole(
         name=role, pipeline=pipeline.name, kind=spec.kind, label=spec.label,
         order=spec.order, can_spawn=spec.can_spawn,
         allow_unrouted_workers=spec.allow_unrouted_workers,
-        modules=spec.modules,
+        modules=spec.modules, disabled_tools=spec.disabled_tools,
         model=_merge_scalar(d.model, spec.model),
         effort=spec.effort,
         skills=_merge_list(d.skills, spec.skills),
         mcp_servers=_merge_list(d.mcp_servers, spec.mcp_servers),
         base_branch_strategy=_merge_scalar(d.base_branch_strategy, spec.base_branch_strategy),
### 360c846b7 V-555: #V-555: replace retired fan launcher with dynamic workflows

diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index 7788ac7c4..e106a76a9 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -523,12 +523,10 @@ class WorkflowEngine:
             candidates = [model]
         elif model is not None:
             candidates = [str(item) for item in model]
         elif hard:
             candidates = ["opus"]
-        elif purpose == "verify" or escalate:
-            candidates = ["sol"]
         else:
             candidates = ["luna"]
         if not candidates or any(not item.strip() for item in candidates):
             raise ValueError("model candidates must be non-empty strings")
         from app.models import resolve_model
@@ -981,10 +979,11 @@ class WorkflowEngine:
             self.run_id,
             "--budget-usd",
             f"{self.budget.maximum_usd:g}",
             "--max-calls",
             str(self.budget.maximum_calls),
+            *(["--repo", str(self.workspace_repo)] if self.workspace_repo is not None else []),
         ])
 
     def write_manifest(self) -> dict:
         resume = self.resume_command()
         manifest = {
@@ -1046,10 +1045,11 @@ def _args() -> argparse.Namespace:
     group.add_argument("--run-id")
     group.add_argument("--resume")
     parser.add_argument("--budget-usd", type=float, required=True)
     parser.add_argument("--max-calls", type=int, default=100)
     parser.add_argument("--max-concurrency", type=int, default=None)
+    parser.add_argument("--repo", type=Path, help="Target repository for isolated writable calls")
     return parser.parse_args()
 
 
 async def _main() -> int:
     args = _args()
@@ -1061,10 +1061,11 @@ async def _main() -> int:
         run_dir,
         budget_usd=args.budget_usd,
         workflow_path=workflow,
         max_calls=args.max_calls,
         max_concurrency=args.max_concurrency,
+        workspace_repo=args.repo,
     )
     resume = engine.resume_command()
     print(f"WF_BG_MESSAGE={json.dumps(f'wf_run {run_id} interrupted; resume with: {resume}')}", flush=True)
     try:
         await engine.execute(workflow)
### a8d2e20ad V-582: #V-582: харнес-маршруты из живого каталога, допуск по данным провайдера

diff --git a/tests/test_wf_run.py b/tests/test_wf_run.py
index 999111ca5..3aa2dcce6 100644
--- a/tests/test_wf_run.py
+++ b/tests/test_wf_run.py
@@ -535,15 +535,18 @@ async def test_restricted_capabilities_require_an_inline_reason(tmp_path):
     with pytest.raises(ValueError, match="capability_reason"):
         await engine.agent("work", model="luna", tools="read")
 
 
 @pytest.mark.asyncio
-async def test_harness_read_capability_rejects_a_hallucinated_write(tmp_path, monkeypatch):
+async def test_harness_read_capability_rejects_a_hallucinated_write(
+    tmp_path, monkeypatch, live_harness_route,
+):
     from app.harness.llm import LLMEvent
     from app.harness.oneshot import run_oneshot
 
     monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
+    live_harness_route("vendor/free-x:free")
 
     class FakeLLM:
         def __init__(self):
             self.round = 0
             self.saw_refusal = False
@@ -570,11 +573,11 @@ async def test_harness_read_capability_rejects_a_hallucinated_write(tmp_path, mo
             return None
 
     llm = FakeLLM()
     row = await run_oneshot(
         prompt="try to write",
-        model="z-ai/glm-5.2:free",
+        model="vendor/free-x:free",
         cwd=tmp_path,
         tools_level="read",
         network=True,
         mcp=False,
         system_prompt="",
@@ -584,15 +587,18 @@ async def test_harness_read_capability_rejects_a_hallucinated_write(tmp_path, mo
     assert llm.saw_refusal is True
     assert not (tmp_path / "forbidden.txt").exists()
 
 
 @pytest.mark.asyncio
-async def test_standalone_harness_default_is_not_writable(tmp_path, monkeypatch):
+async def test_standalone_harness_default_is_not_writable(
+    tmp_path, monkeypatch, live_harness_route,
+):
     from app.harness.llm import LLMEvent
     from app.harness.oneshot import run_oneshot
 
     monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
+    live_harness_route("vendor/free-x:free")
 
     class FakeLLM:
         def __init__(self):
             self.round = 0
 
@@ -610,38 +616,39 @@ async def test_standalone_harness_default_is_not_writable(tmp_path, monkeypatch)
 
         async def aclose(self):
             return None
 
     row = await run_oneshot(
-        prompt="write", model="z-ai/glm-5.2:free", cwd=tmp_path,
+        prompt="write", model="vendor/free-x:free", cwd=tmp_path,
         network=True, mcp=False, system_prompt="", llm=FakeLLM(),
     )
     assert row["ok"] is True
     assert not (tmp_path / "escaped.txt").exists()
 
 
 @pytest.mark.asyncio
-async def test_free_output_requires_a_verify_step_before_synthesis(tmp_path):
+async def test_free_output_requires_a_verify_step_before_synthesis(tmp_path, live_harness_route):
+    live_harness_route("vendor/free-x:free")
     calls = []
 
     async def adapter(prompt, model, **_kwargs):
         calls.append((prompt, model))
         runtime = "harness" if model.endswith(":free") else "codex"
         return _result('{"ok": true}', runtime=runtime, model=model)
 
     engine = _engine("free-gate", tmp_path, budget_usd=2, adapter=adapter)
     with pytest.raises(ValueError, match="loss_tolerant"):
-        await engine.agent("unsafe draft", model="z-ai/glm-5.2:free")
+        await engine.agent("unsafe draft", model="vendor/free-x:free")
     free = await engine.agent(
-        "draft", model="z-ai/glm-5.2:free", loss_tolerant=True,
+        "draft", model="vendor/free-x:free", loss_tolerant=True,
     )
     with pytest.raises(ValueError, match="non-free"):
         await engine.agent(
             "self check",
             purpose="verify",
             inputs=[free],
-            model="z-ai/glm-5.2:free",
+            model="vendor/free-x:free",
             loss_tolerant=True,
         )
     with pytest.raises(ValueError, match="verify"):
         await engine.agent("synthesize", purpose="synthesis", inputs=[free])
 
### bbfd3641c V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели

diff --git a/app/harness/oneshot.py b/app/harness/oneshot.py
index 82480ff34..4dec2c6f1 100644
--- a/app/harness/oneshot.py
+++ b/app/harness/oneshot.py
@@ -7,11 +7,11 @@ import asyncio
 import json
 import os
 from pathlib import Path
 
 from app.harness import prompts, tools
-from app.harness.llm import OpenRouterClient
+from app.harness.llm import GigaChatClient, OpenRouterClient
 from app.harness.loop import AgentLoop
 from app.harness.mcp import MCPClient
 from app.models import get_model_spec, validate_harness_model_spec
 
 
@@ -19,20 +19,23 @@ async def run_oneshot(
     *, prompt: str, model: str, cwd: Path, tools_level: str = "read",
     network: bool = True, mcp: bool = True, system_prompt: str = "", llm=None,
 ) -> dict:
     spec = get_model_spec(model)
     validate_harness_model_spec(spec)
-    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
-    if not key:
-        raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY)")
-    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
-    if not base_url.rstrip("/").endswith("/v1"):
-        base_url = base_url.rstrip("/") + "/v1"
-    llm = llm or OpenRouterClient(
-        api_key=key, model=model, base_url=base_url,
-        supported_parameters=spec.supported_parameters,
-    )
+    if llm is None and spec.provider == "gigachat":
+        llm = GigaChatClient(model=model)
+    elif llm is None:
+        key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENROUTER_KEY", "")
+        if not key:
+            raise RuntimeError("No API key found (checked OPENROUTER_API_KEY, OPENROUTER_KEY)")
+        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
+        if not base_url.rstrip("/").endswith("/v1"):
+            base_url = base_url.rstrip("/") + "/v1"
+        llm = OpenRouterClient(
+            api_key=key, model=model, base_url=base_url,
+            supported_parameters=spec.supported_parameters,
+        )
     mcp_client = MCPClient()
     try:
         if mcp and tools_level == "all" and network:
             from app.runtime_registry import _load_scope_mcp_servers
 
### 038f06b7b V-720: #V-720: add one-call dynamic workflows

diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index e106a76a9..0c9ea4a6b 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -4,10 +4,11 @@
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
@@ -210,10 +211,14 @@ def _validate_schema(value: Any, schema: dict, path: str = "$") -> None:
 
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
 
 
@@ -1035,48 +1040,133 @@ class WorkflowEngine:
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
### 382660ab4 V-738: #V-738: add staged dynamic workflow execution

diff --git a/scripts/wf_run.py b/scripts/wf_run.py
index 0c9ea4a6b..a490e303e 100644
--- a/scripts/wf_run.py
+++ b/scripts/wf_run.py
@@ -1068,10 +1068,34 @@ class WorkflowEngine:
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
@@ -1079,34 +1103,40 @@ def _args() -> argparse.Namespace:
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
@@ -1124,11 +1154,11 @@ async def _main() -> int:
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
@@ -1138,11 +1168,20 @@ async def _main() -> int:
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
### 25eb55af9 V-739: #V-739: curate model catalog and preserve session compatibility

diff --git a/app/pipeline.py b/app/pipeline.py
index 8ee19609f..d38e14eb3 100644
--- a/app/pipeline.py
+++ b/app/pipeline.py
@@ -282,11 +282,11 @@ class RoleSpec(BaseModel):
             if val not in CODEX_REASONING_EFFORTS:
                 raise ValueError(
                     f"effort['{key}']: unknown level '{val}'; "
                     f"known={sorted(CODEX_REASONING_EFFORTS)}")
             # Порядок проверок: рантайм раньше модели, иначе ключи "codex"/"grok" (они же
-            # алиасы моделей gpt-5.6-sol и grok-4.5) читались бы как модель — и ключ
+            # алиасы моделей gpt-6.1-sol и grok-4.6) читались бы как модель — и ключ
             # "codex" не покрывал бы Luna. Имена рантаймов здесь ЗАРЕЗЕРВИРОВАНЫ: выбрать
             # ими конкретную модель нельзя, для этого есть полный id.
             if key == "default" or _is_runtime(key):
                 out[key] = val
             elif _model_is_known(key):