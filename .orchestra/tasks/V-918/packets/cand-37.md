# Candidate cand-37

## ORIGIN commit 80eefd5b42 (2026-08-13): #1: #1: единая точка истины для моделей + Opus 4.6 в список выбора
(diff of code only, excluding .orchestra/ and *.md; capped 1200 lines)

diff --git a/app/models.py b/app/models.py
index 35649c3ba..47d990bd6 100644
--- a/app/models.py
+++ b/app/models.py
@@ -35,67 +35,120 @@ class ProviderMetadata:
     title: str
     ui_provider: str
     cache_ttl_seconds: int
     cache_ttl_approximate: bool
     legacy_model_prefixes: tuple[str, ...] = ()
     model_providers: tuple[str, ...] = ()
 
 
-MODELS = {
-    "claude-fable-5[1m]": "Fable 5 (1M)",
-    "claude-opus-5[1m]": "Opus 5 (1M)",
-    "claude-sonnet-5[1m]": "Sonnet 5 (1M)",
-    "claude-haiku-4-5": "Haiku 4.5",
-    "gpt-5.3-codex-spark": "GPT-5.3 Codex Spark",
-    "gpt-5.6-sol": "GPT-5.6 Sol",
-    "gpt-5.6-terra": "GPT-5.6 Terra",
-    "gpt-5.6-luna": "GPT-5.6 Luna",
-    "gpt-5.5": "GPT-5.5",
-    "gpt-5.4": "GPT-5.4",
-    "gpt-5.4-mini": "GPT-5.4 Mini",
-    "grok-4.6": "Grok 4.6",
-    "grok-4.5": "Grok 4.5",
-}
-
-CONTEXT_LIMITS = {
-    "claude-fable-5[1m]": 1000000,
-    "claude-opus-5[1m]": 1000000,
-    "claude-sonnet-5[1m]": 1000000,
-    "claude-haiku-4-5": 200000,
+# THE single place a selectable model is declared. Everything below —
+# MODELS, CONTEXT_LIMITS, BACKENDS, MODEL_PROVIDERS, TOKEN_PRICES — is derived
+# from this list, so adding a model means adding exactly one ModelSpec here.
+# Prices are per million tokens; omit them for runtimes that price elsewhere
+# (Codex in backend_codex.py, Grok in backend_grok.py).
+SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
+    ModelSpec(
+        id="claude-fable-5[1m]", name="Fable 5 (1M)",
+        runtime="claude", provider="anthropic",
+        context_length=1000000, price_input=10.0, price_output=50.0,
+    ),
+    ModelSpec(
+        id="claude-opus-5[1m]", name="Opus 5 (1M)",
+        runtime="claude", provider="anthropic",
+        context_length=1000000, price_input=5.0, price_output=25.0,
+    ),
+    ModelSpec(
+        id="claude-sonnet-5[1m]", name="Sonnet 5 (1M)",
+        runtime="claude", provider="anthropic",
+        context_length=1000000, price_input=2.0, price_output=10.0,
+    ),
+    ModelSpec(
+        id="claude-haiku-4-5", name="Haiku 4.5",
+        runtime="claude", provider="anthropic",
+        context_length=200000, price_input=0.80, price_output=4.0,
+    ),
+    # Still served on the subscription: `claude --model claude-opus-4-6 --print`
+    # answers. Priced as Opus 5; the plain id gets Anthropic's standard 200k
+    # window, only the [1m] id carries the extended one.
+    ModelSpec(
+        id="claude-opus-4-6[1m]", name="Opus 4.6 (1M)",
+        runtime="claude", provider="anthropic",
+        context_length=1000000, price_input=5.0, price_output=25.0,
+    ),
+    ModelSpec(
+        id="claude-opus-4-6", name="Opus 4.6",
+        runtime="claude", provider="anthropic",
+        context_length=200000, price_input=5.0, price_output=25.0,
+    ),
     # Effective ChatGPT-auth Codex runtime budget. Public API window is larger, but
     # Orchestra's GPT workers run through Codex CLI and must use its runtime contract.
-    "gpt-5.3-codex-spark": 128000,
-    "gpt-5.6-sol": 258400,
-    "gpt-5.6-terra": 258400,
-    "gpt-5.6-luna": 258400,
-    "gpt-5.5": 258400,
-    "gpt-5.4": 258400,
-    "gpt-5.4-mini": 258400,
+    ModelSpec(
+        id="gpt-5.3-codex-spark", name="GPT-5.3 Codex Spark",
+        runtime="codex", provider="openai", context_length=128000,
+    ),
+    ModelSpec(
+        id="gpt-5.6-sol", name="GPT-5.6 Sol",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
+    ModelSpec(
+        id="gpt-5.6-terra", name="GPT-5.6 Terra",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
+    ModelSpec(
+        id="gpt-5.6-luna", name="GPT-5.6 Luna",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
+    ModelSpec(
+        id="gpt-5.5", name="GPT-5.5",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
+    ModelSpec(
+        id="gpt-5.4", name="GPT-5.4",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
+    ModelSpec(
+        id="gpt-5.4-mini", name="GPT-5.4 Mini",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
     # Reported by the Grok runtime itself (initialize + session/new agree). The bundled
     # vendor README disagrees with the runtime on other numbers, so the runtime wins.
-    "grok-4.6": 500000,
-    "grok-4.5": 500000,
-}
+    ModelSpec(
+        id="grok-4.6", name="Grok 4.6",
+        runtime="grok", provider="x-ai", context_length=500000,
+    ),
+    ModelSpec(
+        id="grok-4.5", name="Grok 4.5",
+        runtime="grok", provider="x-ai", context_length=500000,
+    ),
+)
+
+# Derived views. They stay plain dicts with the same contract because callers
+# import them by name and fetch_models_from_proxy() mutates them in place;
+# _rebuild_derived_views() below is the only writer at import time.
+MODELS: dict[str, str] = {}
+CONTEXT_LIMITS: dict[str, int] = {}
 
 # Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
 # knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
 ALIASES = {
     "fable": "claude-fable-5[1m]",
     "fable5": "claude-fable-5[1m]",
     "claude-fable-5": "claude-fable-5[1m]",
     "claude-fable-5-1m": "claude-fable-5[1m]",
     "mythos": "claude-fable-5[1m]",
     "opus": "claude-opus-5[1m]",
     "opus5": "claude-opus-5[1m]",
     "claude-opus-5": "claude-opus-5[1m]",
     "claude-opus-4-8[1m]": "claude-opus-5[1m]",
     "claude-opus-4-8": "claude-opus-5[1m]",
-    "claude-opus-4-6[1m]": "claude-opus-5[1m]",
-    "claude-opus-4-6": "claude-opus-5[1m]",
+    # 4.6 is selectable again, so its ids must resolve to itself, not upgrade away.
+    "claude-opus-4-6[1m]": "claude-opus-4-6[1m]",
+    "claude-opus-4-6": "claude-opus-4-6",
+    "opus4.6": "claude-opus-4-6",
     "sonnet": "claude-sonnet-5[1m]",
     "sonnet5": "claude-sonnet-5[1m]",
     "claude-sonnet-5-1m": "claude-sonnet-5[1m]",
     "claude-sonnet-4-6": "claude-sonnet-5[1m]",
     "claude-sonnet-4-5": "claude-sonnet-5[1m]",
     "haiku": "claude-haiku-4-5",
     "spark": "gpt-5.3-codex-spark",
     "codexspark": "gpt-5.3-codex-spark",
@@ -110,47 +163,19 @@ ALIASES = {
     "gpt5.4mini": "gpt-5.4-mini",
     "gpt-5.4mini": "gpt-5.4-mini",
     "grok": "grok-4.5",
     "grok4.6": "grok-4.6",
     "grok4.5": "grok-4.5",
     "grok-build": "grok-4.5",
 }
 
-BACKENDS = {
-    "claude-fable-5[1m]": "claude",
-    "claude-opus-5[1m]": "claude",
-    "claude-sonnet-5[1m]": "claude",
-    "claude-haiku-4-5": "claude",
-    "gpt-5.3-codex-spark": "codex",
-    "gpt-5.6-sol": "codex",
-    "gpt-5.6-terra": "codex",
-    "gpt-5.6-luna": "codex",
-    "gpt-5.5": "codex",
-    "gpt-5.4": "codex",
-    "gpt-5.4-mini": "codex",
-    "grok-4.6": "grok",
-    "grok-4.5": "grok",
-}
+BACKENDS: dict[str, str] = {}
 
-MODEL_PROVIDERS = {
-    "claude-fable-5[1m]": "anthropic",
-    "claude-opus-5[1m]": "anthropic",
-    "claude-sonnet-5[1m]": "anthropic",
-    "claude-haiku-4-5": "anthropic",
-    "gpt-5.3-codex-spark": "openai",
-    "gpt-5.6-sol": "openai",
-    "gpt-5.6-terra": "openai",
-    "gpt-5.6-luna": "openai",
-    "gpt-5.5": "openai",
-    "gpt-5.4": "openai",
-    "gpt-5.4-mini": "openai",
-    "grok-4.6": "x-ai",
-    "grok-4.5": "x-ai",
-}
+MODEL_PROVIDERS: dict[str, str] = {}
 
 # Runtime ids double as the accounting buckets emitted by usage analytics. The
 # explicit `unknown` bucket is intentionally conservative: absence of evidence
 # about a cache window must never acquire Claude's exact one-hour policy.
 PROVIDER_METADATA: dict[str, ProviderMetadata] = {
     "claude": ProviderMetadata(
         id="claude",
         title="Claude Max",
@@ -202,23 +227,19 @@ def cache_policy_for_runtime(runtime: str) -> dict[str, int | bool]:
     metadata = PROVIDER_METADATA.get(runtime, PROVIDER_METADATA["unknown"])
     return {
         "cache_ttl_seconds": metadata.cache_ttl_seconds,
         "cache_ttl_approximate": metadata.cache_ttl_approximate,
     }
 
 
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
-# Codex models intentionally absent — their prices live in backend_codex.py
-TOKEN_PRICES = {
-    "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
-    "claude-opus-5[1m]":   {"input": 5.0,  "output": 25.0},
-    "claude-sonnet-5[1m]": {"input": 2.0,  "output": 10.0},
-    "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
-}
+# Codex and Grok models intentionally absent — a spec without prices stays out of
+# this view, and their prices live in backend_codex.py / backend_grok.py.
+TOKEN_PRICES: dict[str, dict[str, float]] = {}
 
 DEFAULT_MODEL = "claude-sonnet-5[1m]"
 MODEL_SPECS: dict[str, ModelSpec] = {}
 
 # These exact ids occur in persisted sessions but are no longer selectable.
 # Keeping them outside MODELS prevents retired models from returning to the UI
 # while making resume deterministic without any prefix inference.
 COMPAT_MODEL_SPECS: dict[str, ModelSpec] = {
@@ -249,42 +270,23 @@ COMPAT_MODEL_SPECS: dict[str, ModelSpec] = {
     ),
     "claude-opus-4-8": ModelSpec(
         id="claude-opus-4-8",
         name="Opus 4.8 (legacy)",
         runtime="claude",
         provider="anthropic",
         context_length=1000000,
     ),
-    "claude-opus-4-6[1m]": ModelSpec(
-        id="claude-opus-4-6[1m]",
-        name="Opus 4.6 (legacy, 1M)",
-        runtime="claude",
-        provider="anthropic",
-        context_length=1000000,
-        price_input=15.0,
-        price_output=75.0,
-    ),
-    "claude-opus-4-6": ModelSpec(
-        id="claude-opus-4-6",
-        name="Opus 4.6 (legacy)",
-        runtime="claude",
-        provider="anthropic",
-        context_length=1000000,
-    ),
 }
 
 # The only proxy models observed on a registered deployment that omit both
 # runtime and provider. Exact ids make this a reviewed compatibility contract,
 # not another family-wide catch-all.
 _REVIEWED_PROXY_ROUTES: dict[str, tuple[str, str]] = {
-    **{
-        model_id: (BACKENDS[model_id], MODEL_PROVIDERS[model_id])
-        for model_id in MODELS
-    },
+    **{spec.id: (spec.runtime, spec.provider) for spec in SELECTABLE_MODEL_SPECS},
     "deepseek/deepseek-v4-flash": ("opencode", "deepseek"),
     "deepseek/deepseek-v4-pro": ("opencode", "deepseek"),
 }
 
 _VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")
 
 
 def _generate_aliases(model_id: str) -> list[str]:
@@ -294,16 +296,29 @@ def _generate_aliases(model_id: str) -> list[str]:
         tail = model_id.rsplit("/", 1)[1]
         aliases.append(tail)
         stripped = _VERSION_RE.sub("", tail)
         if stripped and stripped != tail:
             aliases.append(stripped)
     return aliases
 
 
+def _apply_derived_views(spec: ModelSpec) -> None:
+    """Project one spec onto the five legacy dict views — the only writer of them."""
+    MODELS[spec.id] = spec.name
+    CONTEXT_LIMITS[spec.id] = spec.context_length
+    BACKENDS[spec.id] = spec.runtime
+    MODEL_PROVIDERS[spec.id] = spec.provider
+    if spec.price_input is not None or spec.price_output is not None:
+        TOKEN_PRICES[spec.id] = {
+            "input": float(spec.price_input or 0),
+            "output": float(spec.price_output or 0),
+        }
+
+
 def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
     """Register one explicit provider/model/runtime route and legacy lookup views."""
     if not spec.id:
         raise ValueError("model id must not be empty")
     if not spec.provider or spec.provider == "unknown":
         raise ValueError(f"model '{spec.id}' must declare an explicit provider")
     from app.runtime_registry import get_runtime
     get_runtime(spec.runtime)
@@ -315,31 +330,25 @@ def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
         allowed = ", ".join(PROVIDER_METADATA[spec.runtime].model_providers) or "(none)"
         raise ValueError(
             f"model '{spec.id}' provider '{spec.provider}' is not registered for "
             f"runtime '{spec.runtime}'; registered providers: {allowed}"
         )
     if spec.id in MODEL_SPECS and not replace:
         raise ValueError(f"model '{spec.id}' is already registered")
     MODEL_SPECS[spec.id] = spec
-    MODELS[spec.id] = spec.name
-    CONTEXT_LIMITS[spec.id] = spec.context_length
-    BACKENDS[spec.id] = spec.runtime
-    if spec.price_input is not None or spec.price_output is not None:
-        TOKEN_PRICES[spec.id] = {
-            "input": float(spec.price_input or 0),
-            "output": float(spec.price_output or 0),
-        }
+    _apply_derived_views(spec)
 
 
 def unregister_model(model_id: str) -> None:
     MODEL_SPECS.pop(model_id, None)
     MODELS.pop(model_id, None)
     CONTEXT_LIMITS.pop(model_id, None)
     BACKENDS.pop(model_id, None)
+    MODEL_PROVIDERS.pop(model_id, None)
     TOKEN_PRICES.pop(model_id, None)
 
 
 def get_model_spec(model_id: str) -> ModelSpec:
     """Return an explicit selectable or persisted-session compatibility route."""
     if model_id in MODEL_SPECS:
         return MODEL_SPECS[model_id]
     if model_id in COMPAT_MODEL_SPECS:
@@ -348,27 +357,26 @@ def get_model_spec(model_id: str) -> ModelSpec:
     compatibility = ", ".join(sorted(COMPAT_MODEL_SPECS))
     raise ValueError(
         f"unknown model '{model_id}'; registered models: {registered}; "
         f"persisted-session compatibility routes: {compatibility}"
     )
 
 
 def _seed_model_specs() -> None:
-    for model_id, name in list(MODELS.items()):
-        prices = TOKEN_PRICES.get(model_id, {})
-        MODEL_SPECS[model_id] = ModelSpec(
-            id=model_id,
-            name=name,
-            runtime=BACKENDS[model_id],
-            provider=MODEL_PROVIDERS[model_id],
-            context_length=CONTEXT_LIMITS[model_id],
-            price_input=prices.get("input"),
-            price_output=prices.get("output"),
-        )
+    """Populate MODEL_SPECS and every derived view from SELECTABLE_MODEL_SPECS."""
+    for spec in SELECTABLE_MODEL_SPECS:
+        if spec.id in MODEL_SPECS:
+            raise ValueError(f"model '{spec.id}' is declared twice in SELECTABLE_MODEL_SPECS")
+        if spec.id in COMPAT_MODEL_SPECS:
+            raise ValueError(
+                f"model '{spec.id}' is both selectable and a compatibility route"
+            )
+        MODEL_SPECS[spec.id] = spec
+        _apply_derived_views(spec)
 
 
 _seed_model_specs()
 
 
 def validate_model_registry() -> None:
     """Fail if model, runtime, provider, or legacy lookup views disagree."""
     from app.runtime_registry import get_runtime
@@ -400,16 +408,18 @@ def validate_model_registry() -> None:
 
     for model_id, spec in MODEL_SPECS.items():
         if MODELS.get(model_id) != spec.name:
             errors.append(f"{model_id}: MODELS view differs from ModelSpec")
         if BACKENDS.get(model_id) != spec.runtime:
             errors.append(f"{model_id}: BACKENDS view differs from ModelSpec")
         if CONTEXT_LIMITS.get(model_id) != spec.context_length:
             errors.append(f"{model_id}: CONTEXT_LIMITS view differs from ModelSpec")
+        if MODEL_PROVIDERS.get(model_id) != spec.provider:
+            errors.append(f"{model_id}: MODEL_PROVIDERS view differs from ModelSpec")
 
     for provider_id, metadata in PROVIDER_METADATA.items():
         if provider_id != metadata.id:
             errors.append(
                 f"provider metadata key '{provider_id}' differs from id '{metadata.id}'"
             )
 
     if errors:
@@ -434,16 +444,17 @@ def is_proxy_connected() -> bool:
     return _proxy_connected
 
 
 def _clear_selectable_models() -> None:
     MODELS.clear()
     CONTEXT_LIMITS.clear()
     TOKEN_PRICES.clear()
     BACKENDS.clear()
+    MODEL_PROVIDERS.clear()
     MODEL_SPECS.clear()
     ALIASES.clear()
 
 
 def _proxy_model_spec(raw: dict) -> ModelSpec | None:
     model_id = str(raw.get("id") or "").strip()
     if not model_id:
         return None
diff --git a/tests/test_backend_routing.py b/tests/test_backend_routing.py
index 804907a26..22579ace6 100644
--- a/tests/test_backend_routing.py
+++ b/tests/test_backend_routing.py
@@ -27,16 +27,17 @@ from app.backend_opencode import OpenCodeBackend
 def isolated_model_registry(monkeypatch):
     import app.models as registry
 
     for name in (
         "MODELS",
         "CONTEXT_LIMITS",
         "ALIASES",
         "BACKENDS",
+        "MODEL_PROVIDERS",
         "TOKEN_PRICES",
         "MODEL_SPECS",
     ):
         monkeypatch.setattr(registry, name, dict(getattr(registry, name)))
     monkeypatch.setattr(registry, "_proxy_connected", False)
     return registry
 
 
@@ -57,19 +58,19 @@ def test_opus5_registry_and_aliases():
     assert MODELS[model_id] == "Opus 5 (1M)"
     assert spec.runtime == "claude"
     assert spec.provider == "anthropic"
     assert spec.context_length == 1_000_000
     assert TOKEN_PRICES[model_id] == {"input": 5.0, "output": 25.0}
     assert resolve_model("opus") == model_id
     assert resolve_model("opus5") == model_id
     assert resolve_model("claude-opus-5") == model_id
-    # New requests upgrade aliases; persisted rows keep exact compatibility specs.
+    # Retired ids upgrade to Opus 5; 4.6 is selectable again and resolves to itself.
     assert resolve_model("claude-opus-4-8[1m]") == model_id
-    assert resolve_model("claude-opus-4-6") == model_id
+    assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"
     assert "claude-opus-4-8[1m]" not in MODELS
     assert get_model_spec("claude-opus-4-8[1m]").runtime == "claude"
 
 
 def test_backend_for_model_registered_wins():
     assert "claude-sonnet-5[1m]" in BACKENDS
     assert backend_for_model("claude-sonnet-5[1m]") == "claude"
 
@@ -134,16 +135,84 @@ def test_registry_validator_covers_every_selectable_model():
     validate_model_registry()
     assert set(MODELS) == set(BACKENDS)
     for model_id in MODELS:
         spec = get_model_spec(model_id)
         assert spec.runtime in PROVIDER_METADATA
         assert spec.provider != "unknown"
 
 
+def test_declaring_one_spec_populates_every_derived_view(isolated_model_registry):
+    """Adding a model must mean editing SELECTABLE_MODEL_SPECS and nothing else.
+
+    The five dicts below used to be hand-maintained in parallel, so forgetting one
+    made a model either invisible in the picker or fatal at spawn.
+    """
+    registry = isolated_model_registry
+    spec = ModelSpec(
+        id="claude-hypothetical-9",
+        name="Hypothetical 9",
+        runtime="claude",
+        provider="anthropic",
+        context_length=333000,
+        price_input=1.25,
+        price_output=6.5,
+    )
+
+    assert spec.id not in registry.MODELS
+
+    registry.register_model(spec)
+
+    assert registry.MODELS[spec.id] == "Hypothetical 9"
+    assert registry.CONTEXT_LIMITS[spec.id] == 333000
+    assert registry.BACKENDS[spec.id] == "claude"
+    assert registry.MODEL_PROVIDERS[spec.id] == "anthropic"
+    assert registry.TOKEN_PRICES[spec.id] == {"input": 1.25, "output": 6.5}
+    assert registry.get_model_spec(spec.id) is spec
+    registry.validate_model_registry()
+
+
+def test_derived_views_carry_exactly_the_declared_specs():
+    """No view may gain or lose an id relative to the single declaration list."""
+    import app.models as registry
+
+    declared = {spec.id for spec in registry.SELECTABLE_MODEL_SPECS}
+    assert declared == set(MODELS)
+    assert declared == set(BACKENDS)
+    assert declared == set(CONTEXT_LIMITS)
+    assert declared == set(registry.MODEL_PROVIDERS)
+    # Only priced specs reach TOKEN_PRICES; Codex/Grok price in their backends.
+    assert set(TOKEN_PRICES) == {
+        spec.id for spec in registry.SELECTABLE_MODEL_SPECS
+        if spec.price_input is not None or spec.price_output is not None
+    }
+    for spec in registry.SELECTABLE_MODEL_SPECS:
+        assert MODELS[spec.id] == spec.name
+        assert CONTEXT_LIMITS[spec.id] == spec.context_length
+        assert BACKENDS[spec.id] == spec.runtime
+        assert registry.MODEL_PROVIDERS[spec.id] == spec.provider
+
+
+def test_opus46_is_selectable_and_priced():
+    """Opus 4.6 is live on the subscription — picking it must not divert to Opus 5."""
+    spec = get_model_spec("claude-opus-4-6")
+    assert MODELS["claude-opus-4-6"] == "Opus 4.6"
+    assert spec.runtime == "claude"
+    assert spec.provider == "anthropic"
+    assert spec.context_length == 200000
+    assert get_model_spec("claude-opus-4-6[1m]").context_length == 1_000_000
+    assert TOKEN_PRICES["claude-opus-4-6"] == {"input": 5.0, "output": 25.0}
+    assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"
+    assert resolve_model("claude-opus-4-6[1m]") == "claude-opus-4-6[1m]"
+    assert backend_for_model("claude-opus-4-6") == "claude"
+    # A live model must not also linger as a retired compatibility route.
+    import app.models as registry
+    assert "claude-opus-4-6" not in registry.COMPAT_MODEL_SPECS
+
+
 def test_cache_policy_is_explicit_and_unknown_is_conservative():
     assert cache_policy_for_runtime("claude") == {
         "cache_ttl_seconds": 3600,
         "cache_ttl_approximate": False,
     }
     assert cache_policy_for_runtime("codex") == {
         "cache_ttl_seconds": 1800,
         "cache_ttl_approximate": True,


## LATER FIX dc09cc2366 (8.8 days later): Squashed commits: - #366: research + plan + 22 red tests (model catalog, two-level availability) - #366: plan review section + behavioral re
lines of origin it changed/deleted: 9
(code only, capped 400 lines)

Squashed commits:
- #366: research + plan + 22 red tests (model catalog, two-level availability)
- #366: plan review section + behavioral red reasons (no external reviewer: quota)
- #366: T1 — kv_set/kv_delete writers + two-level availability flags (overlay, read-through kv)
- #366: T2 — OpenRouter catalog fetch/normalize/kv-cache + registration re-applied inside every registry rebuild
- #366: T3 — two-level enforcement: /api/models dashboard filter, agents gate in _create_session_locked, change-model via=dashboard|mcp, bounded unknown-model error; CONTRACT CHANGE: derived views are now a superset of SELECTABLE_MODEL_SPECS (test_derived_views_carry_exactly_the_declared_specs rewritten as subset assertions)
- WIP #366: T4 catalog HTTP API written (GET/POST/PATCH /api/models/catalog*), tests not yet run; TODO: run test_catalog_api.py, mutation, T5 frontend+Playwright probe, T6
- #366: T4 — /api/models/catalog GET(union registry+cache)/refresh POST/flags PATCH; dropped counter surfaced; mutation: PATCH-echo-without-persist caught
- #366: T5 — catalog modal screen: search/free/tools/image filters, two toggles per model, refresh button; picker untouched
- #366: T5 — live Playwright probe evidence (probe-catalog.png): worktree js/css substituted on :8888, catalog modal renders 18 models / 36 toggles, search filters, clone-frozen screenshot
- #366: T6 — live-agent shoulders: resume surface intact after both flags off, new spawn rejected with actionable message, switch-away allowed; mutation: message without screen name caught
- #366: report + personal memory
- #366: изоляция тестов — снимок и восстановление реестра моделей между тестами; kv-чтение флагов/кеша fail-soft при отсутствии таблицы
- #366: route surface snapshot — +/api/models/catalog{,/refresh,/flags} (intentional new public endpoints)


diff --git a/app/db.py b/app/db.py
index cc33b0c3d..e95c951bc 100644
--- a/app/db.py
+++ b/app/db.py
@@ -508,16 +508,30 @@ def init_db() -> None:
 
 
 def kv_get(key: str, default: str = "") -> str:
     with _conn() as c:
         row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
         return row["value"] if row else default
 
 
+def kv_set(key: str, value: str) -> None:
+    with _conn() as c:
+        c.execute(
+            "INSERT INTO kv(key, value) VALUES(?, ?) "
+            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
+            (key, value),
+        )
+
+
+def kv_delete(key: str) -> None:
+    with _conn() as c:
+        c.execute("DELETE FROM kv WHERE key=?", (key,))
+
+
 def _reconstruct_costs(c) -> None:
     import re as _re
     sessions = c.execute("SELECT id FROM sessions").fetchall()
     for s in sessions:
         logs = c.execute(
             "SELECT content FROM logs WHERE session_id=? AND type='status' "
             "AND (content LIKE 'turn ended%$%' OR content LIKE 'turn done%$%') ORDER BY id ASC",
             (s["id"],),
diff --git a/app/manager.py b/app/manager.py
index 484f41656..03bed1dd2 100644
--- a/app/manager.py
+++ b/app/manager.py
@@ -33,16 +33,18 @@ from app.workspace import (
     validate_repo_root, resolve_base_branch as resolve_git_base_branch,
     repo_root,
 )
 from app.models import (
     CONTEXT_LIMITS,
     available_models_block,
     backend_for_model,
     cache_policy_for_runtime,
+    ensure_dashboard_visible,
+    ensure_spawn_allowed,
     get_model_spec,
     resolve_model,
     runtime_for_record,
 )
 from app.pipeline import (
     DEFAULT_PIPELINE,
     build_system_prompt,
     get_active_pipeline,
@@ -570,16 +572,23 @@ class SessionManager:
                              pipeline: str = "", profile: str = "",
                              docs_feature: str = "",
                              owned_dirs: list | None = None,
                              tg_topic: bool = False,
                              planned_initial_turn: bool = False) -> AgentSession:
         scope = scope.rstrip("/")
         cwd = cwd.rstrip("/")
         model = resolve_model(model)
+        # #366: agent-spawned workers are gated by the `agents` level; anything
+        # created from the dashboard (orchestrators, manual sessions) — by the
+        # `dashboard` level. Internal routes never pass through here.
+        if parent_name:
+            ensure_spawn_allowed(model)
+        else:
+            ensure_dashboard_visible(model)
         if not Path(cwd).is_dir():
             raise ValueError(f"cwd does not exist: {cwd}")
         spawn_repo_path = ""
         spawn_git_common_dir = ""
         existing = get_session_by_name(name, scope)
         if existing:
             st = existing.get("status", "?")
             ctx = existing.get("context_pct", 0) or 0
diff --git a/app/mcp_stdio.py b/app/mcp_stdio.py
index a8641f042..480e2b0ec 100644
--- a/app/mcp_stdio.py
+++ b/app/mcp_stdio.py
@@ -1511,17 +1511,17 @@ async def update_progress(percent: int, status: str) -> str:
     if isinstance(result, dict) and result.get("error"):
         return f"Progress update failed: {result['error']}"
     return f"Progress: {percent}% — {status}"
 
 
 @mcp.tool()
 async def change_worker_model(name: str, model: str) -> str:
     """Change an idle worker's model and start a fresh dialog on the target runtime."""
-    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model, "fresh": True})
+    result = await _api("POST", f"/api/sessions/{name}/change-model", json={"scope": SCOPE, "model": model, "fresh": True, "via": "mcp"})
     if isinstance(result, dict) and result.get("error"):
         return f"Model change failed: {result['error']}"
     if isinstance(result, dict) and result.get("changed"):
         return f"Model changed: {result.get('old_model')} → {result.get('model')}"
     return f"Model already {result.get('model', model)}"
 
 
 def _merge_local_result(
diff --git a/app/model_catalog.py b/app/model_catalog.py
new file mode 100644
index 000000000..2d51b4042
--- /dev/null
+++ b/app/model_catalog.py
@@ -0,0 +1,156 @@
+"""OpenRouter model catalog (#366).
+
+Fetches https://openrouter.ai/api/v1/models, normalizes it to the fields the
+dashboard filters need, caches the result in SQLite kv (`model_catalog_cache`)
+and registers EVERY cached model into the shared registry via
+`app.models.register_model` — availability is an overlay (flags), so disabled
+models stay registered and live sessions on them keep resuming.
+
+Registration-order guarantee: `apply_model_catalog()` is re-applied at the tail
+of every registry rebuild (`fetch_models_from_proxy`, `refresh_models`), so an
+enterprise-mode clear can never silently drop the catalog.
+"""
+
+import json
+import logging
+import os
+import sqlite3
+import time
+
+import httpx
+
+logger = logging.getLogger(__name__)
+
+CATALOG_KV_KEY = "model_catalog_cache"
+OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
+
+# Dropped-model counter of the last apply_model_catalog() run. Exposed through
+# refresh_catalog() so a silently-eaten catalog is visible in the API response.
+_LAST_APPLY_STATS = {"registered": 0, "dropped": 0}
+
+
+def normalize_catalog_model(raw: dict) -> dict | None:
+    """OpenRouter raw entry -> normalized dict; None for entries without an id."""
+    model_id = str(raw.get("id") or "").strip()
+    if not model_id:
+        return None
+
+    pricing = raw.get("pricing") or {}
+
+    def _per_mtok(value) -> float:
+        try:
+            return round(abs(float(value)) * 1_000_000, 6)
+        except (TypeError, ValueError):
+            return 0.0
+
+    arch = raw.get("architecture") or {}
+    params = raw.get("supported_parameters") or []
+    try:
+        context_length = int(raw.get("context_length") or 200000)
+    except (TypeError, ValueError):
+        context_length = 200000
+    return {
+        "id": model_id,
+        "name": str(raw.get("name") or model_id),
+        "context_length": max(context_length, 1),
+        "price_prompt": _per_mtok(pricing.get("prompt")),
+        "price_completion": _per_mtok(pricing.get("completion")),
+        "input_modalities": [str(m) for m in (arch.get("input_modalities") or [])],
+        "supports_tools": "tools" in params,
+    }
+
+
+def catalog_cache_payload() -> dict:
+    from app.db import kv_get
+
+    try:
+        data = json.loads(kv_get(CATALOG_KV_KEY, "{}"))
+    except json.JSONDecodeError:
+        data = {}
+    except sqlite3.OperationalError:
+        return {"fetched_at": None, "models": []}
+    if not isinstance(data, dict):
+        data = {}
+    models = data.get("models")
+    return {
+        "fetched_at": data.get("fetched_at"),
+        "models": models if isinstance(models, list) else [],
+    }
+
+
+def cached_catalog() -> list[dict]:
+    return catalog_cache_payload()["models"]
+
+
+def apply_model_catalog() -> int:
+    """Register every cached catalog model into the shared registry.
+
+    Idempotent: already-registered ids are refreshed in place. Manifest ids are
+    never clobbered. Returns the number of registrations performed this run;
+    per-model failures are counted in `_LAST_APPLY_STATS['dropped']`.
+    """
+    from app.models import MODEL_SPECS, ModelSpec, SELECTABLE_MODEL_SPECS, register_model
+
+    manifest_ids = {spec.id for spec in SELECTABLE_MODEL_SPECS}
+    registered = dropped = 0
+    for norm in cached_catalog():
+        spec = ModelSpec(
+            id=norm["id"],
+            name=norm["name"],
+            runtime="harness",
+            provider="openrouter",
+            context_length=int(norm["context_length"]),
+            price_input=float(norm["price_prompt"]),
+            price_output=float(norm["price_completion"]),
+        )
+        try:
+            register_model(spec, replace=norm["id"] not in manifest_ids)
+            registered += 1
+        except (ValueError, TypeError) as exc:
+            dropped += 1
+            logger.warning("catalog model %s dropped: %s", norm["id"], exc)
+
+    _LAST_APPLY_STATS.update(registered=registered, dropped=dropped)
+    return registered
+
+
+async def refresh_catalog() -> dict:
+    """Fetch the OpenRouter catalog, cache it, register it. Raises on fetch error."""
+    api_key = (
+        os.environ.get("OPENROUTER_API_KEY")
+        or os.environ.get("OPENROUTER_KEY")
+        or os.environ.get("ANTHROPIC_API_KEY", "")
+    )
+    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
+    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
+    try:
+        async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as client:
+            resp = await client.get(OPENROUTER_MODELS_URL, headers=headers)
+            resp.raise_for_status()
+            data = resp.json()
+    except Exception as exc:
+        logger.warning("OpenRouter catalog fetch failed: %s", exc)
+        raise ValueError(f"catalog fetch failed: {exc}") from exc
+
+    normalized: list[dict] = []
+    seen: set[str] = set()
+    for raw in data.get("data") or []:
+        entry = normalize_catalog_model(raw if isinstance(raw, dict) else {})
+        if entry is not None and entry["id"] not in seen:
+            seen.add(entry["id"])
+            normalized.append(entry)
+
+    from app.db import kv_set
+
+    kv_set(CATALOG_KV_KEY, json.dumps({"fetched_at": time.time(), "models": normalized}))
+    registered = apply_model_catalog()
+    result = {
+        "fetched": len(normalized),
+        "registered": registered,
+        "dropped": _LAST_APPLY_STATS["dropped"],
+    }
+    logger.info(
+        "OpenRouter catalog refreshed: fetched=%(fetched)s registered=%(registered)s "
+        "dropped=%(dropped)s" % result
+    )
+    return result
diff --git a/app/models.py b/app/models.py
index 02caf4386..7164d839c 100644
--- a/app/models.py
+++ b/app/models.py
@@ -1,17 +1,19 @@
 """Available models — single source of truth.
 
 Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
 fetch_models_from_proxy() replaces them with proxy-only models.
 """
 
+import json
 import logging
 import os
 import re
+import sqlite3
 from dataclasses import dataclass
 
 import httpx
 
 logger = logging.getLogger(__name__)
 
 _proxy_connected: bool = False
 
@@ -388,16 +390,85 @@ def get_model_spec(model_id: str) -> ModelSpec:
     registered = ", ".join(sorted(MODEL_SPECS)) or "(none)"
     compatibility = ", ".join(sorted(COMPAT_MODEL_SPECS))
     raise ValueError(
         f"unknown model '{model_id}'; registered models: {registered}; "
         f"persisted-session compatibility routes: {compatibility}"
     )
 
 
+# ── Availability flags (two levels, #366) ──────────────────────────────────────
+# Overlay over the registry: flags only gate entry points (dashboard list, agent
+# spawn, change-model). They NEVER unregister a model, so a live session on a
+# disabled model keeps resolving, resuming, and costing correctly.
+
+MODEL_FLAGS_KV_KEY = "model_flags"
+
+
+def _load_model_flags() -> dict:
+    from app.db import kv_get
+
+    try:
+        data = json.loads(kv_get(MODEL_FLAGS_KV_KEY, "{}"))
+    except json.JSONDecodeError:
+        return {}
+    except sqlite3.OperationalError:
+        # No kv table (e.g. a test DB created before init_db) = no stored state
+        # = pure defaults; never let availability checks hard-fail on it.
+        return {}
+    return data if isinstance(data, dict) else {}
+
+
+def get_model_flags(model_id: str) -> dict[str, bool]:
+    """Dashboard/agents visibility; manifest models default to both-true, catalog
+    models registered later default to both-false until the user enables them."""
+    default = any(spec.id == model_id for spec in SELECTABLE_MODEL_SPECS)
+    stored = _load_model_flags().get(model_id) or {}
+    return {
+        "dashboard": bool(stored.get("dashboard", default)),
+        "agents": bool(stored.get("agents", default)),
+    }
+
+
+def set_model_flags(
+    model_id: str, *, dashboard: bool | None = None, agents: bool | None = None
+) -> dict[str, bool]:
+    if model_id not in MODEL_SPECS:
+        raise ValueError(f"unknown model '{model_id}'")
+    from app.db import kv_set
+
+    flags_store = _load_model_flags()
+    entry = flags_store.get(model_id) or {}
+    if dashboard is not None:
+        entry["dashboard"] = bool(dashboard)
+    if agents is not None:
+        entry["agents"] = bool(agents)
+    flags_store[model_id] = entry
+    kv_set(MODEL_FLAGS_KV_KEY, json.dumps(flags_store))
+    return get_model_flags(model_id)
+
+
+def ensure_spawn_allowed(model_id: str) -> None:
+    """Hard gate for agent-side usage (worker spawn, MCP change-model)."""
+    if not get_model_flags(model_id)["agents"]:
+        raise ValueError(
+            f"model '{model_id}' is disabled for agents — re-enable it in the "
+            "Models catalog screen"
+        )
+
+
+def ensure_dashboard_visible(model_id: str) -> None:
+    """Hard gate for user-side actions (UI session creation, change-model from UI)."""
+    if not get_model_flags(model_id)["dashboard"]:
+        raise ValueError(
+            f"model '{model_id}' is hidden from the dashboard — re-enable it in "
+            "the Models catalog screen"
+        )
+
+
 def _seed_model_specs() -> None:
     """Populate MODEL_SPECS and every derived view from SELECTABLE_MODEL_SPECS."""
     for spec in SELECTABLE_MODEL_SPECS:
         if spec.id in MODEL_SPECS:
             raise ValueError(f"model '{spec.id}' is declared twice in SELECTABLE_MODEL_SPECS")
         if spec.id in COMPAT_MODEL_SPECS:
             raise ValueError(
                 f"model '{spec.id}' is both selectable and a compatibility route"
@@ -598,16 +669,22 @@ async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
         if spec.id not in MODEL_SPECS:
             register_model(spec)
             added += 1
         for alias in _generate_aliases(spec.id):
             if alias not in ALIASES and alias != spec.id:
                 ALIASES[alias] = spec.id