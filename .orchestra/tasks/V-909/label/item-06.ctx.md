# Context for item-06

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/models.py b/app/models.py
index 0e4b38c0d..186b7a172 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,88 +1,103 @@
 """Available models — single source of truth."""
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
     "claude-sonnet-4-6": "Sonnet 4.6",
     "claude-haiku-4-5": "Haiku 4.5",
     "gpt-5.5": "GPT-5.5",
     "gpt-5.4": "GPT-5.4",
     "gpt-5.4-mini": "GPT-5.4 Mini",
+    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro (1M)",
+    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash (1M)",
 }
 
 CONTEXT_LIMITS = {
     "claude-fable-5[1m]": 1000000,
     "claude-opus-4-8[1m]": 1000000,
     "claude-opus-4-6[1m]": 1000000,
     "claude-sonnet-4-6": 200000,
     "claude-haiku-4-5": 200000,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
+    "deepseek/deepseek-v4-pro": 1000000,
+    "deepseek/deepseek-v4-flash": 1000000,
 }
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
 # knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
     "fable": "claude-fable-5[1m]",
     "fable5": "claude-fable-5[1m]",
     "claude-fable-5": "claude-fable-5[1m]",
     "claude-fable-5-1m": "claude-fable-5[1m]",
     "mythos": "claude-fable-5[1m]",
     "opus": "claude-opus-4-6[1m]",
     "opus4.8": "claude-opus-4-8[1m]",
     "claude-opus-4-8": "claude-opus-4-8[1m]",
     "claude-opus-4-8-1m": "claude-opus-4-8[1m]",
     "opus4.6": "claude-opus-4-6[1m]",
     "claude-opus-4-6": "claude-opus-4-6[1m]",
     "claude-opus-4-6-1m": "claude-opus-4-6[1m]",
     "sonnet": "claude-sonnet-4-6",
     "claude-sonnet-4-5": "claude-sonnet-4-6",
     "haiku": "claude-haiku-4-5",
     "gpt5.5": "gpt-5.5",
     "codex": "gpt-5.5",
     "gpt5.4": "gpt-5.4",
     "gpt5.4mini": "gpt-5.4-mini",
     "gpt-5.4mini": "gpt-5.4-mini",
+    "deepseek": "deepseek/deepseek-v4-pro",
+    "deepseek-pro": "deepseek/deepseek-v4-pro",
+    "v4-pro": "deepseek/deepseek-v4-pro",
+    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
+    "deepseek-flash": "deepseek/deepseek-v4-flash",
+    "v4-flash": "deepseek/deepseek-v4-flash",
+    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
 }
 
 BACKENDS = {
     "claude-fable-5[1m]": "claude",
     "claude-opus-4-8[1m]": "claude",
     "claude-opus-4-6[1m]": "claude",
     "claude-sonnet-4-6": "claude",
     "claude-haiku-4-5": "claude",
     "gpt-5.5": "codex",
     "gpt-5.4": "codex",
     "gpt-5.4-mini": "codex",
+    "deepseek/deepseek-v4-pro": "claude",
+    "deepseek/deepseek-v4-flash": "claude",
 }
 
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
 # Codex models intentionally absent — their prices live in backend_codex.py
 TOKEN_PRICES = {
     "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
     "claude-opus-4-8[1m]": {"input": 15.0, "output": 75.0},
     "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0},
     "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
+    "deepseek/deepseek-v4-pro":   {"input": 0.435, "output": 0.87},
+    "deepseek/deepseek-v4-flash": {"input": 0.098, "output": 0.197},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
 
 def resolve_model(model: str) -> str:
     m = model.lower().strip()
     if m in ALIASES:
         return ALIASES[m]
     if m in MODELS:
         return m
     return model
 
 
 def backend_for_model(model: str) -> str:
     return BACKENDS.get(model, "claude")
 
 
 def available_models_block() -> str:
     """Prompt block listing all available models for spawn_worker."""


## Later history of the touched files on main (after this commit)

53 later commits touch these paths; the first 40 (oldest first):
6ad906508 2026-06-12 #86: dynamic model list from proxy /v1/models
f36f1fdb1 2026-06-13 Revert "#85: #85: add DeepSeek V4 Pro/Flash models"
f1a5ba6e4 2026-06-13 remove proxy model fetching — enterprise-only feature, open source uses hardcoded MODELS dict
a755646c6 2026-06-13 #91: client info page + proxy-only models + connection indicator
cbe4f00b0 2026-06-13 Revert "#91: client info page + proxy-only models + connection indicator"
79cc3fa0f 2026-06-13 #91: #91: client info page + proxy-only models + connection indicator
2364a9e25 2026-06-13 #91: fix proxy URL — read ANTHROPIC_BASE_URL (set in container .env)
200d6c33c 2026-06-13 #91: semantic aliases for dynamic models (opus/sonnet/deepseek) + resolve warning
920f7d9f3 2026-06-13 fix: model dropdown sync + resolve_model fallback to first available
3651919d7 2026-06-14 #96 phase 2: route non-Claude/non-GPT models to opencode backend
21b7a2a72 2026-07-01 refactor: remove Opus 4.6, redirect all aliases to 4.8
b9acb11fc 2026-07-03 docs: cleanup research — dead-code list + super-full-cycle roles plan
9088adc98 2026-07-03 fix: Opus 4.8 price 15/75 → 5/25 (was outdated Opus 4.1-era pricing; 4.6+ dropped 67%)
ae8031299 2026-07-03 Restore Opus 4.6 as real model, switch all orchestrators to 4.6
f897ad6a9 2026-07-06 Skip fetch_models_from_proxy when no proxy configured (fixes VPS log spam)
6f4b244ca 2026-07-11 Codex → GPT-5.6 Sol + compact: accept all summary content (no garbage/length filter)
b929710c1 2026-07-16 Sol runtime fixes: context accounting, cost delta, limit retry, codex_review atomicity, orphan pipe
0c1804441 2026-07-17 refactor: make agent runtimes provider-agnostic
77c0f8198 2026-07-18 feat: expose Codex Spark usage and workers
e3fa5a89e 2026-07-18 #codex-cache-research: plan Codex cache indicator
d817f4796 2026-07-25 Add Opus 5 as Claude default
789b8d9e5 2026-07-27 models: выпилить Opus 4.6/4.8, старые id ремапить на Opus 5
a5f0ef925 2026-07-27 docs(95): research — Grok Build as third Orchestra runtime
66604dcd1 2026-07-28 #95: WIP #95: T6 — grok provider bucketing, cache policy, orchestrator subagents flag
ec1b180f7 2026-07-28 #98: #98 T3: explicit model routing, opencode inventory, no catch-all
0e15dcd31 2026-07-31 #108: #108: план правок по результатам аудита (фаза 2)
6ed76f56b 2026-08-13 #232, #251: #232: установлен grok CLI 1.0.3, ресёрч Grok 4.6 по первоисточникам, черновик правила допуска под третий пул
80eefd5b4 2026-08-13 #1: #1: единая точка истины для моделей + Opus 4.6 в список выбора
9e92823b2 2026-08-17 #306: #306: support sol and luna model aliases
9248be4cd 2026-08-22 #365: харнес на OpenRouter из приватного форка — рантайм harness, шесть бесплатных моделей
ee094a511 2026-08-22 #365: stealth/ox-alpha в манифест — свободный превью, 1M контекста, тулы и картинки
37e186ddd 2026-08-22 #365: #365: оставить три бесплатные модели OpenRouter
dc09cc236 2026-08-22 Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral red reasons (no external reviewer: quota) - #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv) - #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild - #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions) - WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6 - #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught - #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched - #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot - #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught - #366: report + personal memory - #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы - #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)
4d58b176a 2026-08-24 refactor: remove OpenCode runtime
ebb38764a 2026-08-25 #365: harden free OpenRouter harness
0349fc14c 2026-08-26 Repair Orchestra startup and dashboard resilience
d6155f9d4 2026-09-05 #503: freeze Astra registry regression oracle
50945dd00 2026-09-10 models: Fable 5 → Fable 5.1 (claude-fable-5-1[1m]) — полная замена в каталоге
7069c42a6 2026-09-11 V-540: #V-540: capture live Claude usage baseline and reproducible query
4c8cb1d70 2026-09-12 каталог: убрать неиспользуемые GPT-5.4 и 5.4 Mini вместе с их устаревшими тарифами

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 6ad906508 #86: dynamic model list from proxy /v1/models

diff --git a/app/models.py b/app/models.py
index 186b7a172..88ca5e355 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,6 +1,18 @@
-"""Available models — single source of truth."""
+"""Available models — single source of truth.
+
+Hardcoded dicts are the fallback. On startup, fetch_models_from_proxy()
+merges dynamic models from the upstream proxy's /v1/models endpoint.
+"""
+
+import logging
+import os
+import re
+
+import httpx
+
+logger = logging.getLogger(__name__)
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -83,10 +95,110 @@ TOKEN_PRICES = {
     "deepseek/deepseek-v4-flash": {"input": 0.098, "output": 0.197},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
+# Version-like suffixes to strip when generating short aliases
+_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
+
+
+def _generate_aliases(model_id: str) -> list[str]:
+    """Auto-generate short alias candidates for a model ID."""
+    aliases = []
+    # "deepseek/deepseek-v4-flash" → "deepseek-v4-flash"
+    if "/" in model_id:
+        tail = model_id.rsplit("/", 1)[1]
+        aliases.append(tail)
+        # strip version suffix: "deepseek-v4-flash" → "deepseek-flash" (only if different)
+        stripped = _VERSION_RE.sub("", tail)
+        if stripped and stripped != tail:
+            aliases.append(stripped)
+    return aliases
+
+
+def _infer_backend(model_id: str) -> str:
+    if model_id.startswith("gpt-"):
+        return "codex"
+    return "claude"
+
+
+async def fetch_models_from_proxy() -> bool:
+    """Fetch model list from upstream proxy and merge into module-level dicts.
+
+    Returns True on success, False on failure (hardcoded fallback stays).
+    """
+    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
+    url = f"{base_url.rstrip('/')}/v1/models"
+
+    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
+
+    try:
+        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
+            resp = await client.get(
+                url,
+                headers={"Authorization": f"Bearer {api_key}"},
+            )
+            resp.raise_for_status()
+            data = resp.json()
+    except Exception as e:
+        logger.warning(f"fetch_models_from_proxy failed: {e}")
+        return False
+
+    models_list = data.get("data", [])
+    if not models_list:
+        logger.warning("fetch_models_from_proxy: empty model list")
+        return False
+
+    added = 0
+    for m in models_list:
+        mid = m.get("id", "")
+        if not mid:
+            continue
+
+        # Display name: capitalize last segment
+        if "/" in mid:
+            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
+        else:
+            label = mid.replace("-", " ").title()
+
+        ctx = m.get("context_length") or 200000
+
+        pricing = m.get("pricing", {})
+        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
+        completion_price = float(pricing.get("completion", "0")) * 1_000_000
+
+        backend = _infer_backend(mid)
+
+        # Merge — don't overwrite existing hardcoded entries
+        if mid not in MODELS:
+            MODELS[mid] = label
+            added += 1
+        if mid not in CONTEXT_LIMITS:
+            CONTEXT_LIMITS[mid] = ctx
+        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
+            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
+        if mid not in BACKENDS:
+            BACKENDS[mid] = backend
+
+        # Auto-generate aliases for new models
+        for alias in _generate_aliases(mid):
+            if alias not in ALIASES and alias != mid:
+                ALIASES[alias] = mid
+
+    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new)")
+    return True
+
+
+async def refresh_models() -> None:
+    """Startup helper — fetch models, log result."""
+    ok = await fetch_models_from_proxy()
+    if ok:
+        logger.info(f"Models ready: {len(MODELS)} total")
+    else:
+        logger.warning(f"Proxy unreachable, using {len(MODELS)} hardcoded models")
+
 
 def resolve_model(model: str) -> str:
     m = model.lower().strip()
     if m in ALIASES:
         return ALIASES[m]
### f36f1fdb1 Revert "#85: #85: add DeepSeek V4 Pro/Flash models"

diff --git a/app/models.py b/app/models.py
index 88ca5e355..709f377b2 100644
--- a/app/models.py
+++ b/app/models.py
@@ -19,12 +19,10 @@ MODELS = {
     "claude-sonnet-4-6": "Sonnet 4.6",
     "claude-haiku-4-5": "Haiku 4.5",
     "gpt-5.5": "GPT-5.5",
     "gpt-5.4": "GPT-5.4",
     "gpt-5.4-mini": "GPT-5.4 Mini",
-    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro (1M)",
-    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash (1M)",
 }
 
 CONTEXT_LIMITS = {
     "claude-fable-5[1m]": 1000000,
     "claude-opus-4-8[1m]": 1000000,
@@ -32,12 +30,10 @@ CONTEXT_LIMITS = {
     "claude-sonnet-4-6": 200000,
     "claude-haiku-4-5": 200000,
     "gpt-5.5": 258400,
     "gpt-5.4": 258400,
     "gpt-5.4-mini": 258400,
-    "deepseek/deepseek-v4-pro": 1000000,
-    "deepseek/deepseek-v4-flash": 1000000,
 }
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
 # knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
@@ -59,17 +55,10 @@ ALIASES = {
     "gpt5.5": "gpt-5.5",
     "codex": "gpt-5.5",
     "gpt5.4": "gpt-5.4",
     "gpt5.4mini": "gpt-5.4-mini",
     "gpt-5.4mini": "gpt-5.4-mini",
-    "deepseek": "deepseek/deepseek-v4-pro",
-    "deepseek-pro": "deepseek/deepseek-v4-pro",
-    "v4-pro": "deepseek/deepseek-v4-pro",
-    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
-    "deepseek-flash": "deepseek/deepseek-v4-flash",
-    "v4-flash": "deepseek/deepseek-v4-flash",
-    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
 }
 
 BACKENDS = {
     "claude-fable-5[1m]": "claude",
     "claude-opus-4-8[1m]": "claude",
@@ -77,24 +66,20 @@ BACKENDS = {
     "claude-sonnet-4-6": "claude",
     "claude-haiku-4-5": "claude",
     "gpt-5.5": "codex",
     "gpt-5.4": "codex",
     "gpt-5.4-mini": "codex",
-    "deepseek/deepseek-v4-pro": "claude",
-    "deepseek/deepseek-v4-flash": "claude",
 }
 
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
 # Codex models intentionally absent — their prices live in backend_codex.py
 TOKEN_PRICES = {
     "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
     "claude-opus-4-8[1m]": {"input": 15.0, "output": 75.0},
     "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0},
     "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
-    "deepseek/deepseek-v4-pro":   {"input": 0.435, "output": 0.87},
-    "deepseek/deepseek-v4-flash": {"input": 0.098, "output": 0.197},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
 # Version-like suffixes to strip when generating short aliases
### f1a5ba6e4 remove proxy model fetching — enterprise-only feature, open source uses hardcoded MODELS dict

diff --git a/app/models.py b/app/models.py
index 709f377b2..0e4b38c0d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,18 +1,6 @@
-"""Available models — single source of truth.
-
-Hardcoded dicts are the fallback. On startup, fetch_models_from_proxy()
-merges dynamic models from the upstream proxy's /v1/models endpoint.
-"""
-
-import logging
-import os
-import re
-
-import httpx
-
-logger = logging.getLogger(__name__)
+"""Available models — single source of truth."""
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -80,110 +68,10 @@ TOKEN_PRICES = {
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
-# Version-like suffixes to strip when generating short aliases
-_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
-
-
-def _generate_aliases(model_id: str) -> list[str]:
-    """Auto-generate short alias candidates for a model ID."""
-    aliases = []
-    # "deepseek/deepseek-v4-flash" → "deepseek-v4-flash"
-    if "/" in model_id:
-        tail = model_id.rsplit("/", 1)[1]
-        aliases.append(tail)
-        # strip version suffix: "deepseek-v4-flash" → "deepseek-flash" (only if different)
-        stripped = _VERSION_RE.sub("", tail)
-        if stripped and stripped != tail:
-            aliases.append(stripped)
-    return aliases
-
-
-def _infer_backend(model_id: str) -> str:
-    if model_id.startswith("gpt-"):
-        return "codex"
-    return "claude"
-
-
-async def fetch_models_from_proxy() -> bool:
-    """Fetch model list from upstream proxy and merge into module-level dicts.
-
-    Returns True on success, False on failure (hardcoded fallback stays).
-    """
-    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
-    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
-    url = f"{base_url.rstrip('/')}/v1/models"
-
-    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
-
-    try:
-        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
-            resp = await client.get(
-                url,
-                headers={"Authorization": f"Bearer {api_key}"},
-            )
-            resp.raise_for_status()
-            data = resp.json()
-    except Exception as e:
-        logger.warning(f"fetch_models_from_proxy failed: {e}")
-        return False
-
-    models_list = data.get("data", [])
-    if not models_list:
-        logger.warning("fetch_models_from_proxy: empty model list")
-        return False
-
-    added = 0
-    for m in models_list:
-        mid = m.get("id", "")
-        if not mid:
-            continue
-
-        # Display name: capitalize last segment
-        if "/" in mid:
-            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
-        else:
-            label = mid.replace("-", " ").title()
-
-        ctx = m.get("context_length") or 200000
-
-        pricing = m.get("pricing", {})
-        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
-        completion_price = float(pricing.get("completion", "0")) * 1_000_000
-
-        backend = _infer_backend(mid)
-
-        # Merge — don't overwrite existing hardcoded entries
-        if mid not in MODELS:
-            MODELS[mid] = label
-            added += 1
-        if mid not in CONTEXT_LIMITS:
-            CONTEXT_LIMITS[mid] = ctx
-        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
-            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
-        if mid not in BACKENDS:
-            BACKENDS[mid] = backend
-
-        # Auto-generate aliases for new models
-        for alias in _generate_aliases(mid):
-            if alias not in ALIASES and alias != mid:
-                ALIASES[alias] = mid
-
-    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new)")
-    return True
-
-
-async def refresh_models() -> None:
-    """Startup helper — fetch models, log result."""
-    ok = await fetch_models_from_proxy()
-    if ok:
-        logger.info(f"Models ready: {len(MODELS)} total")
-    else:
-        logger.warning(f"Proxy unreachable, using {len(MODELS)} hardcoded models")
-
 
 def resolve_model(model: str) -> str:
     m = model.lower().strip()
     if m in ALIASES:
         return ALIASES[m]
### a755646c6 #91: client info page + proxy-only models + connection indicator

diff --git a/app/models.py b/app/models.py
index 0e4b38c0d..a4801b9af 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,6 +1,20 @@
-"""Available models — single source of truth."""
+"""Available models — single source of truth.
+
+Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
+fetch_models_from_proxy() replaces them with proxy-only models.
+"""
+
+import logging
+import os
+import re
+
+import httpx
+
+logger = logging.getLogger(__name__)
+
+_proxy_connected: bool = False
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -68,10 +82,138 @@ TOKEN_PRICES = {
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
+_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
+
+
+def _generate_aliases(model_id: str) -> list[str]:
+    """Auto-generate short alias candidates for a model ID."""
+    aliases = []
+    if "/" in model_id:
+        tail = model_id.rsplit("/", 1)[1]
+        aliases.append(tail)
+        stripped = _VERSION_RE.sub("", tail)
+        if stripped and stripped != tail:
+            aliases.append(stripped)
+    return aliases
+
+
+def _infer_backend(model_id: str) -> str:
+    if model_id.startswith("gpt-"):
+        return "codex"
+    return "claude"
+
+
+def is_proxy_connected() -> bool:
+    return _proxy_connected
+
+
+async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
+    """Fetch model list from upstream proxy and populate module-level dicts.
+
+    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
+    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
+    """
+    global _proxy_connected
+    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
+    url = f"{base_url.rstrip('/')}/v1/models"
+
+    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
+
+    try:
+        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
+            resp = await client.get(
+                url,
+                headers={"Authorization": f"Bearer {api_key}"},
+            )
+            resp.raise_for_status()
+            data = resp.json()
+    except Exception as e:
+        logger.warning(f"fetch_models_from_proxy failed: {e}")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    models_list = data.get("data", [])
+    if not models_list:
+        logger.warning("fetch_models_from_proxy: empty model list")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    if enterprise_mode:
+        MODELS.clear()
+        CONTEXT_LIMITS.clear()
+        TOKEN_PRICES.clear()
+        BACKENDS.clear()
+        ALIASES.clear()
+
+    added = 0
+    for m in models_list:
+        mid = m.get("id", "")
+        if not mid:
+            continue
+
+        if "/" in mid:
+            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
+        else:
+            label = mid.replace("-", " ").title()
+
+        ctx = m.get("context_length") or 200000
+
+        pricing = m.get("pricing", {})
+        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
+        completion_price = float(pricing.get("completion", "0")) * 1_000_000
+
+        backend = _infer_backend(mid)
+
+        if mid not in MODELS:
+            MODELS[mid] = label
+            added += 1
+        if mid not in CONTEXT_LIMITS:
+            CONTEXT_LIMITS[mid] = ctx
+        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
+            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
+        if mid not in BACKENDS:
+            BACKENDS[mid] = backend
+
+        for alias in _generate_aliases(mid):
+            if alias not in ALIASES and alias != mid:
+                ALIASES[alias] = mid
+
+    _proxy_connected = True
+    mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
+    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
+    return True
+
+
+async def refresh_models() -> None:
### cbe4f00b0 Revert "#91: client info page + proxy-only models + connection indicator"

diff --git a/app/models.py b/app/models.py
index a4801b9af..0e4b38c0d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,20 +1,6 @@
-"""Available models — single source of truth.
-
-Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
-fetch_models_from_proxy() replaces them with proxy-only models.
-"""
-
-import logging
-import os
-import re
-
-import httpx
-
-logger = logging.getLogger(__name__)
-
-_proxy_connected: bool = False
+"""Available models — single source of truth."""
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -82,138 +68,10 @@ TOKEN_PRICES = {
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
-_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
-
-
-def _generate_aliases(model_id: str) -> list[str]:
-    """Auto-generate short alias candidates for a model ID."""
-    aliases = []
-    if "/" in model_id:
-        tail = model_id.rsplit("/", 1)[1]
-        aliases.append(tail)
-        stripped = _VERSION_RE.sub("", tail)
-        if stripped and stripped != tail:
-            aliases.append(stripped)
-    return aliases
-
-
-def _infer_backend(model_id: str) -> str:
-    if model_id.startswith("gpt-"):
-        return "codex"
-    return "claude"
-
-
-def is_proxy_connected() -> bool:
-    return _proxy_connected
-
-
-async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
-    """Fetch model list from upstream proxy and populate module-level dicts.
-
-    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
-    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
-    """
-    global _proxy_connected
-    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
-    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
-    url = f"{base_url.rstrip('/')}/v1/models"
-
-    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
-
-    try:
-        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
-            resp = await client.get(
-                url,
-                headers={"Authorization": f"Bearer {api_key}"},
-            )
-            resp.raise_for_status()
-            data = resp.json()
-    except Exception as e:
-        logger.warning(f"fetch_models_from_proxy failed: {e}")
-        _proxy_connected = False
-        if enterprise_mode:
-            MODELS.clear()
-            CONTEXT_LIMITS.clear()
-            TOKEN_PRICES.clear()
-            BACKENDS.clear()
-            ALIASES.clear()
-        return False
-
-    models_list = data.get("data", [])
-    if not models_list:
-        logger.warning("fetch_models_from_proxy: empty model list")
-        _proxy_connected = False
-        if enterprise_mode:
-            MODELS.clear()
-            CONTEXT_LIMITS.clear()
-            TOKEN_PRICES.clear()
-            BACKENDS.clear()
-            ALIASES.clear()
-        return False
-
-    if enterprise_mode:
-        MODELS.clear()
-        CONTEXT_LIMITS.clear()
-        TOKEN_PRICES.clear()
-        BACKENDS.clear()
-        ALIASES.clear()
-
-    added = 0
-    for m in models_list:
-        mid = m.get("id", "")
-        if not mid:
-            continue
-
-        if "/" in mid:
-            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
-        else:
-            label = mid.replace("-", " ").title()
-
-        ctx = m.get("context_length") or 200000
-
-        pricing = m.get("pricing", {})
-        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
-        completion_price = float(pricing.get("completion", "0")) * 1_000_000
-
-        backend = _infer_backend(mid)
-
-        if mid not in MODELS:
-            MODELS[mid] = label
-            added += 1
-        if mid not in CONTEXT_LIMITS:
-            CONTEXT_LIMITS[mid] = ctx
-        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
-            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
-        if mid not in BACKENDS:
-            BACKENDS[mid] = backend
-
-        for alias in _generate_aliases(mid):
-            if alias not in ALIASES and alias != mid:
-                ALIASES[alias] = mid
-
-    _proxy_connected = True
-    mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
-    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
-    return True
-
-
-async def refresh_models() -> None:
### 79cc3fa0f #91: #91: client info page + proxy-only models + connection indicator

diff --git a/app/models.py b/app/models.py
index 0e4b38c0d..a4801b9af 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,6 +1,20 @@
-"""Available models — single source of truth."""
+"""Available models — single source of truth.
+
+Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
+fetch_models_from_proxy() replaces them with proxy-only models.
+"""
+
+import logging
+import os
+import re
+
+import httpx
+
+logger = logging.getLogger(__name__)
+
+_proxy_connected: bool = False
 
 MODELS = {
     "claude-fable-5[1m]": "Fable 5 (1M)",
     "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
     "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
@@ -68,10 +82,138 @@ TOKEN_PRICES = {
     "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
 }
 
 DEFAULT_MODEL = "claude-sonnet-4-6"
 
+_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
+
+
+def _generate_aliases(model_id: str) -> list[str]:
+    """Auto-generate short alias candidates for a model ID."""
+    aliases = []
+    if "/" in model_id:
+        tail = model_id.rsplit("/", 1)[1]
+        aliases.append(tail)
+        stripped = _VERSION_RE.sub("", tail)
+        if stripped and stripped != tail:
+            aliases.append(stripped)
+    return aliases
+
+
+def _infer_backend(model_id: str) -> str:
+    if model_id.startswith("gpt-"):
+        return "codex"
+    return "claude"
+
+
+def is_proxy_connected() -> bool:
+    return _proxy_connected
+
+
+async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
+    """Fetch model list from upstream proxy and populate module-level dicts.
+
+    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
+    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
+    """
+    global _proxy_connected
+    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
+    url = f"{base_url.rstrip('/')}/v1/models"
+
+    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
+
+    try:
+        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
+            resp = await client.get(
+                url,
+                headers={"Authorization": f"Bearer {api_key}"},
+            )
+            resp.raise_for_status()
+            data = resp.json()
+    except Exception as e:
+        logger.warning(f"fetch_models_from_proxy failed: {e}")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    models_list = data.get("data", [])
+    if not models_list:
+        logger.warning("fetch_models_from_proxy: empty model list")
+        _proxy_connected = False
+        if enterprise_mode:
+            MODELS.clear()
+            CONTEXT_LIMITS.clear()
+            TOKEN_PRICES.clear()
+            BACKENDS.clear()
+            ALIASES.clear()
+        return False
+
+    if enterprise_mode:
+        MODELS.clear()
+        CONTEXT_LIMITS.clear()
+        TOKEN_PRICES.clear()
+        BACKENDS.clear()
+        ALIASES.clear()
+
+    added = 0
+    for m in models_list:
+        mid = m.get("id", "")
+        if not mid:
+            continue
+
+        if "/" in mid:
+            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
+        else:
+            label = mid.replace("-", " ").title()
+
+        ctx = m.get("context_length") or 200000
+
+        pricing = m.get("pricing", {})
+        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
+        completion_price = float(pricing.get("completion", "0")) * 1_000_000
+
+        backend = _infer_backend(mid)
+
+        if mid not in MODELS:
+            MODELS[mid] = label
+            added += 1
+        if mid not in CONTEXT_LIMITS:
+            CONTEXT_LIMITS[mid] = ctx
+        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
+            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
+        if mid not in BACKENDS:
+            BACKENDS[mid] = backend
+
+        for alias in _generate_aliases(mid):
+            if alias not in ALIASES and alias != mid:
+                ALIASES[alias] = mid
+
+    _proxy_connected = True
+    mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
+    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
+    return True
+
+
+async def refresh_models() -> None:
### 2364a9e25 #91: fix proxy URL — read ANTHROPIC_BASE_URL (set in container .env)

diff --git a/app/models.py b/app/models.py
index a4801b9af..b9f98ddf7 100644
--- a/app/models.py
+++ b/app/models.py
@@ -114,11 +114,11 @@ async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
 
     enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
     enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
     """
     global _proxy_connected
-    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
+    base_url = os.environ.get("ANTHROPIC_BASE_URL", os.environ.get("UPSTREAM_API", "https://api.anthropic.com"))
     api_key = os.environ.get("ANTHROPIC_API_KEY", "")
     url = f"{base_url.rstrip('/')}/v1/models"
 
     proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
 
### 200d6c33c #91: semantic aliases for dynamic models (opus/sonnet/deepseek) + resolve warning

diff --git a/app/models.py b/app/models.py
index b9f98ddf7..9ad00d583 100644
--- a/app/models.py
+++ b/app/models.py
@@ -191,16 +191,47 @@ async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
 
         for alias in _generate_aliases(mid):
             if alias not in ALIASES and alias != mid:
                 ALIASES[alias] = mid
 
+    _generate_semantic_aliases()
     _proxy_connected = True
     mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
     logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
     return True
 
 
+# Semantic alias patterns: short name → match first model containing substring
+_SEMANTIC_PATTERNS = [
+    ("opus", "opus"),
+    ("opus4.8", "opus-4-8"),
+    ("opus4.6", "opus-4-6"),
+    ("sonnet", "sonnet"),
+    ("haiku", "haiku"),
+    ("fable", "fable"),
+    ("deepseek", "deepseek"),
+    ("deepseek-flash", "deepseek-v4-flash"),
+    ("deepseek-pro", "deepseek-v4-pro"),
+    ("gemini", "gemini"),
+    ("gemini-flash", "gemini-2.5-flash"),
+    ("llama", "llama"),
+    ("mistral", "mistral"),
+    ("gpt-mini", "gpt-4o-mini"),
+]
+
+
+def _generate_semantic_aliases():
+    """Generate standard short aliases (opus, sonnet, etc.) from loaded models."""
+    for alias, pattern in _SEMANTIC_PATTERNS:
+        if alias in ALIASES:
+            continue
+        for mid in MODELS:
+            if pattern in mid:
+                ALIASES[alias] = mid
+                break
+
+
 async def refresh_models() -> None:
     """Startup helper — fetch models, enterprise-aware."""
     from app.auth import is_auth_enabled
     enterprise = is_auth_enabled()
     ok = await fetch_models_from_proxy(enterprise_mode=enterprise)
@@ -217,10 +248,12 @@ def resolve_model(model: str) -> str:
     m = model.lower().strip()
     if m in ALIASES:
         return ALIASES[m]
     if m in MODELS:
         return m
+    if MODELS:
+        logger.warning(f"resolve_model: '{model}' not found in {len(MODELS)} loaded models, returning as-is")
     return model
 
 
 def backend_for_model(model: str) -> str:
     return BACKENDS.get(model, "claude")