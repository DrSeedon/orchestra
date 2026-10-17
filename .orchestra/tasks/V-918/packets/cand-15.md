# Candidate cand-15

## ORIGIN commit 21b7a2a72d (2026-07-01): refactor: remove Opus 4.6, redirect all aliases to 4.8
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/models.py b/app/models.py
index d38cbeb4b..9844520f2 100644
--- a/app/models.py
+++ b/app/models.py
@@ -12,82 +12,82 @@ import httpx
 
 logger = logging.getLogger(__name__)
 
 _proxy_connected: bool = False
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
-    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
-    "claude-sonnet-4-6": "Sonnet 4.6",
+    "claude-sonnet-5[1m]": "Sonnet 5 (1M)",
     "claude-haiku-4-5": "Haiku 4.5",
     "gpt-5.5": "GPT-5.5",
     "gpt-5.4": "GPT-5.4",
     "gpt-5.4-mini": "GPT-5.4 Mini",
 }
 
 CONTEXT_LIMITS = {
     "claude-fable-5[1m]": 1000000,
     "claude-opus-4-8[1m]": 1000000,
-    "claude-opus-4-6[1m]": 1000000,
-    "claude-sonnet-4-6": 200000,
+    "claude-sonnet-5[1m]": 1000000,
     "claude-haiku-4-5": 200000,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
 }
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
 # knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
     "fable": "claude-fable-5[1m]",
     "fable5": "claude-fable-5[1m]",
     "claude-fable-5": "claude-fable-5[1m]",
     "claude-fable-5-1m": "claude-fable-5[1m]",
     "mythos": "claude-fable-5[1m]",
-    "opus": "claude-opus-4-6[1m]",
+    "opus": "claude-opus-4-8[1m]",
     "opus4.8": "claude-opus-4-8[1m]",
     "claude-opus-4-8": "claude-opus-4-8[1m]",
     "claude-opus-4-8-1m": "claude-opus-4-8[1m]",
-    "opus4.6": "claude-opus-4-6[1m]",
-    "claude-opus-4-6": "claude-opus-4-6[1m]",
-    "claude-opus-4-6-1m": "claude-opus-4-6[1m]",
-    "sonnet": "claude-sonnet-4-6",
-    "claude-sonnet-4-5": "claude-sonnet-4-6",
+    "opus4.6": "claude-opus-4-8[1m]",
+    "claude-opus-4-6": "claude-opus-4-8[1m]",
+    "claude-opus-4-6-1m": "claude-opus-4-8[1m]",
+    "claude-opus-4-6[1m]": "claude-opus-4-8[1m]",
+    "sonnet": "claude-sonnet-5[1m]",
+    "sonnet5": "claude-sonnet-5[1m]",
+    "claude-sonnet-5-1m": "claude-sonnet-5[1m]",
+    "claude-sonnet-4-6": "claude-sonnet-5[1m]",
+    "claude-sonnet-4-5": "claude-sonnet-5[1m]",
     "haiku": "claude-haiku-4-5",
     "gpt5.5": "gpt-5.5",
     "codex": "gpt-5.5",
     "gpt5.4": "gpt-5.4",
     "gpt5.4mini": "gpt-5.4-mini",
     "gpt-5.4mini": "gpt-5.4-mini",
 }
 
 BACKENDS = {
     "claude-fable-5[1m]": "claude",
     "claude-opus-4-8[1m]": "claude",
-    "claude-opus-4-6[1m]": "claude",
-    "claude-sonnet-4-6": "claude",
+    "claude-sonnet-5[1m]": "claude",
     "claude-haiku-4-5": "claude",
     "gpt-5.5": "codex",
     "gpt-5.4": "codex",
     "gpt-5.4-mini": "codex",
 }
 
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
 # Codex models intentionally absent — their prices live in backend_codex.py
 TOKEN_PRICES = {
     "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
     "claude-opus-4-8[1m]": {"input": 15.0, "output": 75.0},
-    "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0},
-    "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
+    "claude-sonnet-5[1m]": {"input": 2.0,  "output": 10.0},
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
-DEFAULT_MODEL = "claude-sonnet-4-6"
+DEFAULT_MODEL = "claude-sonnet-5[1m]"
 
 _VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
 
 
 def _generate_aliases(model_id: str) -> list[str]:
     """Auto-generate short alias candidates for a model ID."""
     aliases = []
     if "/" in model_id:
@@ -205,17 +205,16 @@ async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
     logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
     return True
 
 
 # Semantic alias patterns: short name → match first model containing substring
 _SEMANTIC_PATTERNS = [
     ("opus", "opus"),
     ("opus4.8", "opus-4-8"),
-    ("opus4.6", "opus-4-6"),
     ("sonnet", "sonnet"),
     ("haiku", "haiku"),
     ("fable", "fable"),
     ("deepseek", "deepseek"),
     ("deepseek-flash", "deepseek-v4-flash"),
     ("deepseek-pro", "deepseek-v4-pro"),
     ("gemini", "gemini"),
     ("gemini-flash", "gemini-2.5-flash"),


## LATER FIX ae8031299e (2.3 days later): Restore Opus 4.6 as real model, switch all orchestrators to 4.6
lines of origin it changed/deleted: 4
(code only, capped 400 lines)

Restore Opus 4.6 as real model, switch all orchestrators to 4.6

4.6 was redirect-aliased to 4.8; restore as first-class model (catalog,
context, backend, price). Orchestrators default to 4.6 — 4.8's literal
instruction-following regresses conversational orchestration (needs
proactive gap-filling, not verbatim spec parsing).


diff --git a/app/models.py b/app/models.py
index 9224f0954..ee4d48411 100644
--- a/app/models.py
+++ b/app/models.py
@@ -12,26 +12,28 @@ import httpx
 
 logger = logging.getLogger(__name__)
 
 _proxy_connected: bool = False
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
+    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
     "claude-sonnet-5[1m]": "Sonnet 5 (1M)",
     "claude-haiku-4-5": "Haiku 4.5",
     "gpt-5.5": "GPT-5.5",
     "gpt-5.4": "GPT-5.4",
     "gpt-5.4-mini": "GPT-5.4 Mini",
 }
 
 CONTEXT_LIMITS = {
     "claude-fable-5[1m]": 1000000,
     "claude-opus-4-8[1m]": 1000000,
+    "claude-opus-4-6[1m]": 1000000,
     "claude-sonnet-5[1m]": 1000000,
     "claude-haiku-4-5": 200000,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
 }
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
@@ -41,48 +43,49 @@ ALIASES = {
     "fable5": "claude-fable-5[1m]",
     "claude-fable-5": "claude-fable-5[1m]",
     "claude-fable-5-1m": "claude-fable-5[1m]",
     "mythos": "claude-fable-5[1m]",
     "opus": "claude-opus-4-8[1m]",
     "opus4.8": "claude-opus-4-8[1m]",
     "claude-opus-4-8": "claude-opus-4-8[1m]",
     "claude-opus-4-8-1m": "claude-opus-4-8[1m]",
-    "opus4.6": "claude-opus-4-8[1m]",
-    "claude-opus-4-6": "claude-opus-4-8[1m]",
-    "claude-opus-4-6-1m": "claude-opus-4-8[1m]",
-    "claude-opus-4-6[1m]": "claude-opus-4-8[1m]",
+    "opus4.6": "claude-opus-4-6[1m]",
+    "claude-opus-4-6": "claude-opus-4-6[1m]",
+    "claude-opus-4-6-1m": "claude-opus-4-6[1m]",
     "sonnet": "claude-sonnet-5[1m]",
     "sonnet5": "claude-sonnet-5[1m]",
     "claude-sonnet-5-1m": "claude-sonnet-5[1m]",
     "claude-sonnet-4-6": "claude-sonnet-5[1m]",
     "claude-sonnet-4-5": "claude-sonnet-5[1m]",
     "haiku": "claude-haiku-4-5",
     "gpt5.5": "gpt-5.5",
     "codex": "gpt-5.5",
     "gpt5.4": "gpt-5.4",
     "gpt5.4mini": "gpt-5.4-mini",
     "gpt-5.4mini": "gpt-5.4-mini",
 }
 
 BACKENDS = {
     "claude-fable-5[1m]": "claude",
     "claude-opus-4-8[1m]": "claude",
+    "claude-opus-4-6[1m]": "claude",
     "claude-sonnet-5[1m]": "claude",
     "claude-haiku-4-5": "claude",
     "gpt-5.5": "codex",
     "gpt-5.4": "codex",
     "gpt-5.4-mini": "codex",
 }
 
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
 # Codex models intentionally absent — their prices live in backend_codex.py
 TOKEN_PRICES = {
     "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
     "claude-opus-4-8[1m]": {"input": 5.0,  "output": 25.0},
+    "claude-opus-4-6[1m]": {"input": 5.0,  "output": 25.0},
     "claude-sonnet-5[1m]": {"input": 2.0,  "output": 10.0},
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-5[1m]"
 
 _VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
 
diff --git a/pipelines/default/pipeline.yaml b/pipelines/default/pipeline.yaml
index 37c6f8a93..9bf4c1f29 100644
--- a/pipelines/default/pipeline.yaml
+++ b/pipelines/default/pipeline.yaml
@@ -14,31 +14,31 @@ defaults:
     copies:   [CLAUDE.md, .mcp.json, .env, .worktreeinclude]
   base_branch_strategy: main
   docs_scaffold: false
 roles:
   orchestrator:
     kind: orchestrator
     label: Orchestrator
     order: 0
-    model: opus
+    model: opus4.6
     skills: [html-artifacts, vps-deploy, codex-debate, grill-me]
     modules: [git-workflow, orchestration, background-jobs, task-management, self-improvement]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     when: Managing a team of workers, decomposing tasks, approving plans
     not_for: Direct implementation — delegate to workers
     description: >
       Manages worker agents. Decomposes tasks, spawns workers, reviews results.
       Available worker roles are injected automatically from roles/ directory.
   sub-orchestrator:
     kind: orchestrator
     label: Sub-Orchestrator
     order: 1
-    model: opus
+    model: opus4.6
     modules: [git-workflow, orchestration, background-jobs, task-management, self-improvement]
     can_spawn: ["*"]
     allow_unrouted_workers: true
     tg: {emoji: "🎯"}
     when: Managing a sub-team within a larger hierarchy (department lead, tech lead, team lead)
     not_for: Direct implementation — delegate to workers
     description: >
       Manages a subset of workers under a parent orchestrator.