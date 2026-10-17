# Context for item-47

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/model_catalog.py b/app/model_catalog.py
index cb2320cf0..1f9b55e49 100644
--- a/app/model_catalog.py
+++ b/app/model_catalog.py
@@ -116,44 +116,48 @@ def harness_capable(model: dict) -> bool:
     migration; optional request parameters stay disabled until a fresh catalog arrives.
     """
     if "harness_eligible" in model:
         return model.get("harness_eligible") is True
     return (
         str(model.get("id") or "").endswith(":free")
         and model.get("supports_tools") is True
         and "text" in (model.get("input_modalities") or [])
     )
 
 
 def apply_model_catalog() -> int:
     """Register every cached catalog model into the shared registry.
 
     Idempotent: already-registered ids are refreshed in place, including live
     capabilities/context for manifest fallbacks. Returns registrations this run;
     per-model failures are counted in `_LAST_APPLY_STATS['dropped']`.
     """
     from app.models import MODEL_SPECS, ModelSpec, SELECTABLE_MODEL_SPECS, register_model
 
+    from app.models import BLOCKED_HARNESS_ROUTES
+
     manifest = {spec.id: spec for spec in SELECTABLE_MODEL_SPECS}
+    # Отказавший в пробе маршрут не доходит и до выбора: иначе его видно в списке моделей,
+    # и отказ наступает только на спавне, уже потратив ход.
     eligible = {
         norm["id"]: norm for norm in cached_catalog()
-        if harness_capable(norm)
+        if harness_capable(norm) and norm.get("id") not in BLOCKED_HARNESS_ROUTES
     }
     registered = dropped = 0
     for norm in eligible.values():
         declared = manifest.get(norm["id"])
         spec = ModelSpec(
             id=norm["id"],
             name=norm["name"],
             runtime="harness",
             provider="openrouter",
             context_length=int(norm["context_length"]),
             price_input=float(norm["price_prompt"]),
             price_output=float(norm["price_completion"]),
             supported_parameters=tuple(
                 norm.get("supported_parameters")
                 or (declared.supported_parameters if declared else ("tools",))
             ),
             default_dashboard=(declared.default_dashboard if declared else False),
             default_agents=(declared.default_agents if declared else False),
             available=bool(norm.get("available", True)),
         )
diff --git a/app/models.py b/app/models.py
index 001805e88..b82e7604d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -327,52 +327,72 @@ def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
     if not spec.provider or spec.provider == "unknown":
         raise ValueError(f"model '{spec.id}' must declare an explicit provider")
     from app.runtime_registry import get_runtime
     get_runtime(spec.runtime)
     if spec.runtime not in PROVIDER_METADATA:
         raise ValueError(
             f"model '{spec.id}' uses runtime '{spec.runtime}' without provider metadata"
         )
     if spec.provider not in PROVIDER_METADATA[spec.runtime].model_providers:
         allowed = ", ".join(PROVIDER_METADATA[spec.runtime].model_providers) or "(none)"
         raise ValueError(
             f"model '{spec.id}' provider '{spec.provider}' is not registered for "
             f"runtime '{spec.runtime}'; registered providers: {allowed}"
         )
     if spec.id in MODEL_SPECS and not replace:
         raise ValueError(f"model '{spec.id}' is already registered")
     MODEL_SPECS[spec.id] = spec
     _apply_derived_views(spec)
 
 
+# Маршруты, отказавшие в НАШЕЙ пробе (#V-581, повторный прогон 17.09.2026): каталог
+# провайдера продолжает обещать инструменты, но воркер на них не работает. Каждая строка —
+# наблюдение, а не мнение; появится противоположный замер — снимать по одной, не списком.
+BLOCKED_HARNESS_ROUTES: dict[str, str] = {
+    "thinkingmachines/inkling:free": "HTTP 403: маршрут открыт только в харнесах провайдера",
+    "thinkingmachines/inkling-small:free": "HTTP 403: маршрут открыт только в харнесах провайдера",
+    "poolside/laguna-s-2.1:free": "HTTP 429 в обоих прогонах пробы",
+    "poolside/laguna-xs-2.1:free": "HTTP 429 в обоих прогонах пробы",
+    "google/gemma-4-31b-it:free": "HTTP 429 в обоих прогонах пробы",
+    "nex-agi/nex-n2.5-mini:free": "таймаут чтения 90 с в обоих прогонах",
+    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "инструмент не вызывается вовсе",
+    "inclusionai/ling-3.0-flash-vl:free": "вызывает инструмент и игнорирует его результат",
+}
+
+
 def validate_harness_model_spec(spec: ModelSpec) -> None:
     """Production admission for Orchestra's OpenRouter runtime.
 
     Decided on the provider's own catalog record, never on our copy of it: a route that
     lost tool support or vanished upstream must be refused even while our spec still
     claims otherwise, or the staleness is only discovered by a burnt worker turn (#V-581).
     Zero token prices are not proof of a free route: request/song/image prices can live
     outside those fields. The `:free` suffix is the provider's explicit routing contract.
     Tool support is mandatory because Harness is an agent runtime, not a chat wrapper.
     """
     if spec.runtime != "harness":
         raise ValueError(f"model '{spec.id}' is not a harness model")
+    if spec.id in BLOCKED_HARNESS_ROUTES:
+        raise ValueError(
+            f"harness model '{spec.id}' заблокирован по результатам нашей пробы: "
+            f"{BLOCKED_HARNESS_ROUTES[spec.id]}"
+        )
     if not spec.id.endswith(":free"):
         raise ValueError(
             f"harness model '{spec.id}' is not an exact :free route; "
             "unsuffixed previews and paid routes are blocked"
         )
     from app.model_catalog import harness_capable, live_catalog_entry
 
     live = live_catalog_entry(spec.id)
     if live is None:
         raise ValueError(
             f"harness model '{spec.id}' is not in the OpenRouter catalog we fetched; "
             "refresh the Models catalog screen"
         )
     if not harness_capable(live):
         raise ValueError(
             f"harness model '{spec.id}' does not advertise tool support "
             "in OpenRouter's own catalog"
         )
     if not live.get("available", True):
         raise ValueError(f"harness model '{spec.id}' is no longer available on OpenRouter")
diff --git a/tests/test_model_catalog.py b/tests/test_model_catalog.py
index 9235a2f22..f2226a791 100644
--- a/tests/test_model_catalog.py
+++ b/tests/test_model_catalog.py
@@ -271,20 +271,43 @@ def test_t2_admission_refuses_route_the_live_catalog_no_longer_backs():
         **NORMALIZED,
         "supports_tools": False,
         "supported_parameters": ["temperature"],
         "harness_eligible": False,
     }]}))
     with pytest.raises(ValueError, match="tool support"):
         registry.validate_harness_model_spec(stale_spec)
 
     db.kv_set(CATALOG_KV_KEY, json.dumps({"fetched_at": 1726500000.0, "models": []}))
     with pytest.raises(ValueError, match="not in the OpenRouter catalog"):
         registry.validate_harness_model_spec(stale_spec)
 
 
 def test_t2_admission_passes_route_the_live_catalog_still_backs():
     import app.models as registry
 
     _seed_cache()
     assert _catalog_module().apply_model_catalog() == 1
 
     registry.validate_harness_model_spec(registry.MODEL_SPECS["vendor/model-x:free"])
+
+
+def test_blocked_route_is_refused_and_never_registered():
+    """#V-593: маршрут, отказавший в нашей пробе, каталог провайдера по-прежнему
+    рекламирует как рабочий. Он не должен ни попадать в выбор, ни проходить спавн."""
+    import app.models as registry
+    from app.model_catalog import apply_model_catalog
+
+    blocked_id = next(iter(registry.BLOCKED_HARNESS_ROUTES))
+    blocked_row = {**NORMALIZED, "id": blocked_id, "name": "Blocked Route"}
+    db.kv_set(CATALOG_KV_KEY, json.dumps(
+        {"fetched_at": 1726500000.0, "models": [blocked_row, NORMALIZED]}))
+
+    apply_model_catalog()
+    assert blocked_id not in registry.MODEL_SPECS, "заблокированный маршрут попал в выбор"
+    assert NORMALIZED["id"] in registry.MODEL_SPECS, "здоровый маршрут потерян вместе с ним"
+
+    spec = registry.ModelSpec(
+        id=blocked_id, name="Blocked Route", runtime="harness", provider="openrouter",
+        context_length=128000, price_input=0.0, price_output=0.0,
+        supported_parameters=("tool_choice", "tools"))
+    with pytest.raises(ValueError, match="заблокирован"):
+        registry.validate_harness_model_spec(spec)


## Later history of the touched files on main (after this commit)

11 later commits touch these paths; the first 40 (oldest first):
bbfd3641c 2026-09-22 V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели
f20796d3e 2026-09-23 Каталог моделей: Opus 5.5, GPT-6 Luna и Sol; opus → 5.5
628ac2058 2026-09-23 Маршрут по умолчанию: luna → GPT-6 Luna, sol → GPT-6 Sol (Sol закрыт для агентов)
d1bcb0596 2026-09-25 V-636: GigaChat-3-Ultra в харнесе, запросы GigaChat на единый адрес api.giga.chat
35ad7cbb6 2026-09-25 V-636: все чат-модели GigaChat из API в харнесе; свежая установка стартует на GigaChat-3-Ultra
c4d36776d 2026-09-29 V-658: WIP #V-658: switch default Sonnet to 5.5 pending full tests
bd958c8b4 2026-10-01 Платный маршрут OpenRouter DeepSeek V4.1 Flash по белому списку; песочница openrouter-lab в каталоге проектов
662ee6356 2026-10-01 OpenRouter: открыть GLM-5.3 и GLM-5.3 Flash для экспериментов
25eb55af9 2026-10-06 V-739: #V-739: curate model catalog and preserve session compatibility
b02e52f23 2026-10-08 V-757: #V-757: add Claude Haiku 5.5
e53ba344f 2026-10-08 V-760: #V-760: correct Claude cached cost pricing

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### bbfd3641c V-585: WIP V-585: GigaChat харнес-маршрут, незавершённая работа до смены модели

diff --git a/app/models.py b/app/models.py
index b82e7604d..bdedec5f0 100644
--- a/app/models.py
+++ b/app/models.py
@@ -119,10 +119,20 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
     ),
     ModelSpec(
         id="grok-4.5", name="Grok 4.5",
         runtime="grok", provider="x-ai", context_length=500000,
     ),
+    ModelSpec(
+        id="GigaChat-2", name="GigaChat 2",
+        runtime="harness", provider="gigachat", context_length=128000,
+        supported_parameters=("functions", "function_call"),
+    ),
+    ModelSpec(
+        id="GigaChat-2-Max", name="GigaChat 2 Max",
+        runtime="harness", provider="gigachat", context_length=128000,
+        supported_parameters=("functions", "function_call"),
+    ),
     # Harness (OpenRouter) routes are NOT declared here: they come from the live
     # provider catalog via app.model_catalog. A hardcoded copy of someone else's
     # catalog goes stale silently — both entries kept here until 17.09.2026 were
     # dead (#V-581), and our record still claimed tools and a 256k window.
 )
@@ -173,10 +183,16 @@ ALIASES = {
     "grok": "grok-4.5",
     "grok4.6": "grok-4.6",
     "grok4.5": "grok-4.5",
     "grok-build": "grok-4.5",
 }
+_GIGACHAT_ALIASES = {
+    "gigachat": "GigaChat-2",
+    "gigachat-2": "GigaChat-2",
+    "gigachat-2-max": "GigaChat-2-Max",
+}
+ALIASES.update(_GIGACHAT_ALIASES)
 
 BACKENDS: dict[str, str] = {}
 
 MODEL_PROVIDERS: dict[str, str] = {}
 
@@ -211,15 +227,15 @@ PROVIDER_METADATA: dict[str, ProviderMetadata] = {
         legacy_model_prefixes=("grok-",),
         model_providers=("x-ai",),
     ),
     "harness": ProviderMetadata(
         id="harness",
-        title="OpenRouter",
+        title="Harness",
         ui_provider="openrouter",
         cache_ttl_seconds=0,
         cache_ttl_approximate=True,
-        model_providers=("openrouter",),
+        model_providers=("openrouter", "gigachat"),
     ),
     "unknown": ProviderMetadata(
         id="unknown",
         title="Unknown",
         ui_provider="unknown",
@@ -369,10 +385,14 @@ def validate_harness_model_spec(spec: ModelSpec) -> None:
     outside those fields. The `:free` suffix is the provider's explicit routing contract.
     Tool support is mandatory because Harness is an agent runtime, not a chat wrapper.
     """
     if spec.runtime != "harness":
         raise ValueError(f"model '{spec.id}' is not a harness model")
+    if spec.provider == "gigachat":
+        if spec.id not in {"GigaChat-2", "GigaChat-2-Max"}:
+            raise ValueError(f"unsupported GigaChat model '{spec.id}'")
+        return
     if spec.id in BLOCKED_HARNESS_ROUTES:
         raise ValueError(
             f"harness model '{spec.id}' заблокирован по результатам нашей пробы: "
             f"{BLOCKED_HARNESS_ROUTES[spec.id]}"
         )
@@ -589,10 +609,17 @@ def _clear_selectable_models() -> None:
     TOKEN_PRICES.clear()
     BACKENDS.clear()
     MODEL_PROVIDERS.clear()
     MODEL_SPECS.clear()
     ALIASES.clear()
+    # Direct providers are independent of the enterprise proxy catalog. Keep the
+    # Russian GigaChat routes available when proxy-backed models are reloaded.
+    for spec in SELECTABLE_MODEL_SPECS:
+        if spec.provider == "gigachat":
+            MODEL_SPECS[spec.id] = spec
+            _apply_derived_views(spec)
+    ALIASES.update(_GIGACHAT_ALIASES)
 
 
 def _proxy_model_spec(raw: dict) -> ModelSpec | None:
     model_id = str(raw.get("id") or "").strip()
     if not model_id:
### f20796d3e Каталог моделей: Opus 5.5, GPT-6 Luna и Sol; opus → 5.5

diff --git a/app/models.py b/app/models.py
index bdedec5f0..82df25725 100644
--- a/app/models.py
+++ b/app/models.py
@@ -55,10 +55,15 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
     ModelSpec(
         id="claude-fable-5-1[1m]", name="Fable 5.1 (1M)",
         runtime="claude", provider="anthropic",
         context_length=1000000, price_input=10.0, price_output=50.0,
     ),
+    ModelSpec(
+        id="claude-opus-5-5[1m]", name="Opus 5.5 (1M)",
+        runtime="claude", provider="anthropic",
+        context_length=1000000, price_input=4.0, price_output=20.0,
+    ),
     ModelSpec(
         id="claude-opus-5[1m]", name="Opus 5 (1M)",
         runtime="claude", provider="anthropic",
         context_length=1000000, price_input=5.0, price_output=25.0,
     ),
@@ -101,10 +106,21 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
     ),
     ModelSpec(
         id="gpt-5.6-terra", name="GPT-5.6 Terra",
         runtime="codex", provider="openai", context_length=258400,
     ),
+    ModelSpec(
+        id="gpt-6-luna", name="GPT-6 Luna",
+        runtime="codex", provider="openai", context_length=258400,
+    ),
+    # GPT-6 Sol зарегистрирован, но агентам недоступен: запрет владельца на Sol
+    # (20.09.2026) снимает только он сам, новая версия сама по себе его не снимает.
+    ModelSpec(
+        id="gpt-6-sol", name="GPT-6 Sol",
+        runtime="codex", provider="openai", context_length=258400,
+        default_agents=False,
+    ),
     ModelSpec(
         id="gpt-5.6-luna", name="GPT-5.6 Luna",
         runtime="codex", provider="openai", context_length=258400,
     ),
     ModelSpec(
@@ -150,11 +166,13 @@ ALIASES = {
     "fable5": "claude-fable-5-1[1m]",
     "fable5.1": "claude-fable-5-1[1m]",
     "claude-fable-5-1": "claude-fable-5-1[1m]",
     "claude-fable-5-1-1m": "claude-fable-5-1[1m]",
     "mythos": "claude-fable-5-1[1m]",
-    "opus": "claude-opus-5[1m]",
+    "opus": "claude-opus-5-5[1m]",
+    "opus5.5": "claude-opus-5-5[1m]",
+    "claude-opus-5-5": "claude-opus-5-5[1m]",
     "opus5": "claude-opus-5[1m]",
     "claude-opus-5": "claude-opus-5[1m]",
     "claude-opus-4-8[1m]": "claude-opus-5[1m]",
     "claude-opus-4-8": "claude-opus-5[1m]",
     # 4.6 is selectable again, so its ids must resolve to itself, not upgrade away.
@@ -173,11 +191,15 @@ ALIASES = {
     "gpt5.6": "gpt-5.6-sol",
     "gpt5.6sol": "gpt-5.6-sol",
     "sol": "gpt-5.6-sol",
     "astra": "gpt-6-astra",
     "gpt6astra": "gpt-6-astra",
+    # Маршрут по умолчанию остаётся на 5.6 до живой проверки GPT-6 на воркере.
     "luna": "gpt-5.6-luna",
+    "luna6": "gpt-6-luna",
+    "gpt6luna": "gpt-6-luna",
+    "gpt6sol": "gpt-6-sol",
     "gpt5.6terra": "gpt-5.6-terra",
     "gpt5.6luna": "gpt-5.6-luna",
     "codex": "gpt-5.6-sol",
     "gpt5.5": "gpt-5.5",
     "grok": "grok-4.5",
### 628ac2058 Маршрут по умолчанию: luna → GPT-6 Luna, sol → GPT-6 Sol (Sol закрыт для агентов)

diff --git a/app/models.py b/app/models.py
index 82df25725..77635a404 100644
--- a/app/models.py
+++ b/app/models.py
@@ -188,16 +188,17 @@ ALIASES = {
     "spark": "gpt-5.3-codex-spark",
     "codexspark": "gpt-5.3-codex-spark",
     "gpt5.3spark": "gpt-5.3-codex-spark",
     "gpt5.6": "gpt-5.6-sol",
     "gpt5.6sol": "gpt-5.6-sol",
-    "sol": "gpt-5.6-sol",
+    "sol": "gpt-6-sol",
+    "sol5.6": "gpt-5.6-sol",
     "astra": "gpt-6-astra",
     "gpt6astra": "gpt-6-astra",
-    # Маршрут по умолчанию остаётся на 5.6 до живой проверки GPT-6 на воркере.
-    "luna": "gpt-5.6-luna",
-    "luna6": "gpt-6-luna",
+    # 23.09.2026 владелец перевёл рабочую лошадку на GPT-6 после замера V-616…V-620.
+    "luna": "gpt-6-luna",
+    "luna5.6": "gpt-5.6-luna",
     "gpt6luna": "gpt-6-luna",
     "gpt6sol": "gpt-6-sol",
     "gpt5.6terra": "gpt-5.6-terra",
     "gpt5.6luna": "gpt-5.6-luna",
     "codex": "gpt-5.6-sol",
### d1bcb0596 V-636: GigaChat-3-Ultra в харнесе, запросы GigaChat на единый адрес api.giga.chat

diff --git a/app/models.py b/app/models.py
index 77635a404..52d2a9690 100644
--- a/app/models.py
+++ b/app/models.py
@@ -145,10 +145,15 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
     ModelSpec(
         id="GigaChat-2-Max", name="GigaChat 2 Max",
         runtime="harness", provider="gigachat", context_length=128000,
         supported_parameters=("functions", "function_call"),
     ),
+    ModelSpec(
+        id="GigaChat-3-Ultra", name="GigaChat 3 Ultra",
+        runtime="harness", provider="gigachat", context_length=128000,
+        supported_parameters=("functions", "function_call"),
+    ),
     # Harness (OpenRouter) routes are NOT declared here: they come from the live
     # provider catalog via app.model_catalog. A hardcoded copy of someone else's
     # catalog goes stale silently — both entries kept here until 17.09.2026 were
     # dead (#V-581), and our record still claimed tools and a 256k window.
 )
@@ -210,10 +215,11 @@ ALIASES = {
 }
 _GIGACHAT_ALIASES = {
     "gigachat": "GigaChat-2",
     "gigachat-2": "GigaChat-2",
     "gigachat-2-max": "GigaChat-2-Max",
+    "gigachat-3-ultra": "GigaChat-3-Ultra",
 }
 ALIASES.update(_GIGACHAT_ALIASES)
 
 BACKENDS: dict[str, str] = {}
 
@@ -409,11 +415,11 @@ def validate_harness_model_spec(spec: ModelSpec) -> None:
     Tool support is mandatory because Harness is an agent runtime, not a chat wrapper.
     """
     if spec.runtime != "harness":
         raise ValueError(f"model '{spec.id}' is not a harness model")
     if spec.provider == "gigachat":
-        if spec.id not in {"GigaChat-2", "GigaChat-2-Max"}:
+        if spec.id not in {"GigaChat-2", "GigaChat-2-Max", "GigaChat-3-Ultra"}:
             raise ValueError(f"unsupported GigaChat model '{spec.id}'")
         return
     if spec.id in BLOCKED_HARNESS_ROUTES:
         raise ValueError(
             f"harness model '{spec.id}' заблокирован по результатам нашей пробы: "
### 35ad7cbb6 V-636: все чат-модели GigaChat из API в харнесе; свежая установка стартует на GigaChat-3-Ultra

diff --git a/app/models.py b/app/models.py
index 52d2a9690..f7d446cce 100644
--- a/app/models.py
+++ b/app/models.py
@@ -150,10 +150,25 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
     ModelSpec(
         id="GigaChat-3-Ultra", name="GigaChat 3 Ultra",
         runtime="harness", provider="gigachat", context_length=128000,
         supported_parameters=("functions", "function_call"),
     ),
+    ModelSpec(
+        id="GigaChat-2-Pro", name="GigaChat 2 Pro",
+        runtime="harness", provider="gigachat", context_length=128000,
+        supported_parameters=("functions", "function_call"),
+    ),
+    ModelSpec(
+        id="GigaChat-3-Lightning", name="GigaChat 3 Lightning",
+        runtime="harness", provider="gigachat", context_length=128000,
+        supported_parameters=("functions", "function_call"),
+    ),
+    ModelSpec(
+        id="GigaChat-3-Pro", name="GigaChat 3 Pro",
+        runtime="harness", provider="gigachat", context_length=128000,
+        supported_parameters=("functions", "function_call"),
+    ),
     # Harness (OpenRouter) routes are NOT declared here: they come from the live
     # provider catalog via app.model_catalog. A hardcoded copy of someone else's
     # catalog goes stale silently — both entries kept here until 17.09.2026 were
     # dead (#V-581), and our record still claimed tools and a 256k window.
 )
@@ -215,10 +230,13 @@ ALIASES = {
 }
 _GIGACHAT_ALIASES = {
     "gigachat": "GigaChat-2",
     "gigachat-2": "GigaChat-2",
     "gigachat-2-max": "GigaChat-2-Max",
+    "gigachat-2-pro": "GigaChat-2-Pro",
+    "gigachat-3-lightning": "GigaChat-3-Lightning",
+    "gigachat-3-pro": "GigaChat-3-Pro",
     "gigachat-3-ultra": "GigaChat-3-Ultra",
 }
 ALIASES.update(_GIGACHAT_ALIASES)
 
 BACKENDS: dict[str, str] = {}
@@ -415,11 +433,11 @@ def validate_harness_model_spec(spec: ModelSpec) -> None:
     Tool support is mandatory because Harness is an agent runtime, not a chat wrapper.
     """
     if spec.runtime != "harness":
         raise ValueError(f"model '{spec.id}' is not a harness model")
     if spec.provider == "gigachat":
-        if spec.id not in {"GigaChat-2", "GigaChat-2-Max", "GigaChat-3-Ultra"}:
+        if spec.id not in {"GigaChat-2", "GigaChat-2-Pro", "GigaChat-2-Max", "GigaChat-3-Lightning", "GigaChat-3-Pro", "GigaChat-3-Ultra"}:
             raise ValueError(f"unsupported GigaChat model '{spec.id}'")
         return
     if spec.id in BLOCKED_HARNESS_ROUTES:
         raise ValueError(
             f"harness model '{spec.id}' заблокирован по результатам нашей пробы: "
### c4d36776d V-658: WIP #V-658: switch default Sonnet to 5.5 pending full tests

diff --git a/app/models.py b/app/models.py
index f7d446cce..53e8d035d 100644
--- a/app/models.py
+++ b/app/models.py
@@ -66,11 +66,11 @@ SELECTABLE_MODEL_SPECS: tuple[ModelSpec, ...] = (
         id="claude-opus-5[1m]", name="Opus 5 (1M)",
         runtime="claude", provider="anthropic",
         context_length=1000000, price_input=5.0, price_output=25.0,
     ),
     ModelSpec(
-        id="claude-sonnet-5[1m]", name="Sonnet 5 (1M)",
+        id="claude-sonnet-5-5[1m]", name="Sonnet 5.5 (1M)",
         runtime="claude", provider="anthropic",
         context_length=1000000, price_input=2.0, price_output=10.0,
     ),
     ModelSpec(
         id="claude-haiku-4-5", name="Haiku 4.5",
@@ -197,15 +197,18 @@ ALIASES = {
     "claude-opus-4-8": "claude-opus-5[1m]",
     # 4.6 is selectable again, so its ids must resolve to itself, not upgrade away.
     "claude-opus-4-6[1m]": "claude-opus-4-6[1m]",
     "claude-opus-4-6": "claude-opus-4-6",
     "opus4.6": "claude-opus-4-6",
-    "sonnet": "claude-sonnet-5[1m]",
-    "sonnet5": "claude-sonnet-5[1m]",
-    "claude-sonnet-5-1m": "claude-sonnet-5[1m]",
-    "claude-sonnet-4-6": "claude-sonnet-5[1m]",
-    "claude-sonnet-4-5": "claude-sonnet-5[1m]",
+    "sonnet": "claude-sonnet-5-5[1m]",
+    "sonnet5.5": "claude-sonnet-5-5[1m]",
+    "claude-sonnet-5-5": "claude-sonnet-5-5[1m]",
+    "claude-sonnet-5[1m]": "claude-sonnet-5-5[1m]",
+    "claude-sonnet-5-1m": "claude-sonnet-5-5[1m]",
+    "sonnet5": "claude-sonnet-5-5[1m]",
+    "claude-sonnet-4-6": "claude-sonnet-5-5[1m]",
+    "claude-sonnet-4-5": "claude-sonnet-5-5[1m]",
     "haiku": "claude-haiku-4-5",
     "spark": "gpt-5.3-codex-spark",
     "codexspark": "gpt-5.3-codex-spark",
     "gpt5.3spark": "gpt-5.3-codex-spark",
     "gpt5.6": "gpt-5.6-sol",
@@ -305,11 +308,11 @@ def cache_policy_for_runtime(runtime: str) -> dict[str, int | bool]:
 # TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
 # Codex and Grok models intentionally absent — a spec without prices stays out of
 # this view, and their prices live in backend_codex.py / backend_grok.py.
 TOKEN_PRICES: dict[str, dict[str, float]] = {}
 
-DEFAULT_MODEL = "claude-sonnet-5[1m]"
+DEFAULT_MODEL = "claude-sonnet-5-5[1m]"
 MODEL_SPECS: dict[str, ModelSpec] = {}
 
 # These exact ids occur in persisted sessions but are no longer selectable.
 # Keeping them outside MODELS prevents retired models from returning to the UI
 # while making resume deterministic without any prefix inference.
### bd958c8b4 Платный маршрут OpenRouter DeepSeek V4.1 Flash по белому списку; песочница openrouter-lab в каталоге проектов

diff --git a/app/model_catalog.py b/app/model_catalog.py
index 1f9b55e49..28e570642 100644
--- a/app/model_catalog.py
+++ b/app/model_catalog.py
@@ -48,14 +48,16 @@ def normalize_catalog_model(raw: dict) -> dict | None:
 
     arch = raw.get("architecture") or {}
     params = sorted({str(p) for p in (raw.get("supported_parameters") or []) if p})
     input_modalities = [str(m) for m in (arch.get("input_modalities") or [])]
     output_modalities = [str(m) for m in (arch.get("output_modalities") or [])]
+    from app.models import harness_route_allowed
+
     is_free = model_id.endswith(":free")
     supports_tools = "tools" in params
     harness_eligible = (
-        is_free
+        harness_route_allowed(model_id)
         and supports_tools
         and "text" in input_modalities
         and "text" in output_modalities
     )
     try:
diff --git a/app/models.py b/app/models.py
index 53e8d035d..bc467b1d8 100644
--- a/app/models.py
+++ b/app/models.py
@@ -423,10 +423,20 @@ BLOCKED_HARNESS_ROUTES: dict[str, str] = {
     "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "инструмент не вызывается вовсе",
     "inclusionai/ling-3.0-flash-vl:free": "вызывает инструмент и игнорирует его результат",
 }
 
 
+# Платные маршруты OpenRouter, открытые владельцем поимённо: деньги за них списываются с
+# баланса OpenRouter, а не с подписки. Каждый новый маршрут — только по его слову
+# («да эту модель отпусти», 01.10.2026: DeepSeek V4.1 Flash для экспериментов с оркестраторами).
+PAID_HARNESS_ROUTES: frozenset[str] = frozenset({"deepseek/deepseek-v4.1-flash"})
+
+
+def harness_route_allowed(model_id: str) -> bool:
+    return model_id.endswith(":free") or model_id in PAID_HARNESS_ROUTES
+
+
 def validate_harness_model_spec(spec: ModelSpec) -> None:
     """Production admission for Orchestra's OpenRouter runtime.
 
     Decided on the provider's own catalog record, never on our copy of it: a route that
     lost tool support or vanished upstream must be refused even while our spec still
@@ -444,14 +454,15 @@ def validate_harness_model_spec(spec: ModelSpec) -> None:
     if spec.id in BLOCKED_HARNESS_ROUTES:
         raise ValueError(
             f"harness model '{spec.id}' заблокирован по результатам нашей пробы: "
             f"{BLOCKED_HARNESS_ROUTES[spec.id]}"
         )
-    if not spec.id.endswith(":free"):
+    if not harness_route_allowed(spec.id):
         raise ValueError(
             f"harness model '{spec.id}' is not an exact :free route; "
-            "unsuffixed previews and paid routes are blocked"
+            "unsuffixed previews and paid routes are blocked unless the owner listed them "
+            "in PAID_HARNESS_ROUTES"
         )
     from app.model_catalog import harness_capable, live_catalog_entry
 
     live = live_catalog_entry(spec.id)
     if live is None:
### 662ee6356 OpenRouter: открыть GLM-5.3 и GLM-5.3 Flash для экспериментов

diff --git a/app/models.py b/app/models.py
index bc467b1d8..4d83fa11b 100644
--- a/app/models.py
+++ b/app/models.py
@@ -426,11 +426,15 @@ BLOCKED_HARNESS_ROUTES: dict[str, str] = {
 
 
 # Платные маршруты OpenRouter, открытые владельцем поимённо: деньги за них списываются с
 # баланса OpenRouter, а не с подписки. Каждый новый маршрут — только по его слову
 # («да эту модель отпусти», 01.10.2026: DeepSeek V4.1 Flash для экспериментов с оркестраторами).
-PAID_HARNESS_ROUTES: frozenset[str] = frozenset({"deepseek/deepseek-v4.1-flash"})
+PAID_HARNESS_ROUTES: frozenset[str] = frozenset({
+    "deepseek/deepseek-v4.1-flash",
+    "z-ai/glm-5.3",
+    "z-ai/glm-5.3-flash",
+})
 
 
 def harness_route_allowed(model_id: str) -> bool:
     return model_id.endswith(":free") or model_id in PAID_HARNESS_ROUTES
 