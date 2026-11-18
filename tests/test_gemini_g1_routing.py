"""Exact g1-pro worker admission, without provider or network activity."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app import db,models
from app.events import MessageProvenance
from tests.test_antigravity_acp import stand

RAW={
 "gemini-4-hydrogen-xhigh","gemini-4-hydrogen-high","gemini-4-hydrogen-medium","gemini-4-hydrogen-low",
 "gemini-4-argon-high","gemini-4-argon-medium","gemini-4-argon-low","gemini-pro-orchestrator-g1-pro",
 "gemini-3.8-flash-high","gemini-3.8-flash-medium","gemini-3.8-flash-low"}
ALLOWED={"antigravity/"+raw for raw in RAW}
ALIASES={
 "agy-hydrogen":"gemini-4-hydrogen-high","agy-hydrogen-xhigh":"gemini-4-hydrogen-xhigh",
 "agy-hydrogen-med":"gemini-4-hydrogen-medium","agy-argon":"gemini-4-argon-medium",
 "agy-argon-high":"gemini-4-argon-high","agy-flash":"gemini-3.8-flash-medium","agy-flash-high":"gemini-3.8-flash-high"}

@pytest.fixture
def catalog(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DB_PATH",tmp_path/"catalog.db");db.init_db()
    monkeypatch.setattr(models,"is_provider_disabled",lambda _:False)

def test_default_agent_exception_is_exactly_the_owner_list(catalog):
    assert models.ANTIGRAVITY_G1_GEMINI_AGENT_MODELS==ALLOWED
    for mid in ("antigravity/"+raw for raw in models.ANTIGRAVITY_RAW_MODELS):
        assert models.get_model_spec(mid).default_agents is (mid in ALLOWED)

@pytest.mark.parametrize("mid",sorted(ALLOWED))
def test_all_eleven_pass_the_real_subscription_and_flags_gates(catalog,mid):
    assert models.get_model_flags(mid)["agents"]
    assert models.get_model_spec(mid).context_length==1000000
    models.ensure_spawn_allowed(mid,role="worker",pipeline="default",scope="/private/project")

@pytest.mark.parametrize("alias,raw",list(ALIASES.items()))
def test_all_requested_aliases_are_stable_and_admitted(catalog,alias,raw):
    mid=models.resolve_model(alias)
    assert mid=="antigravity/"+raw
    models.ensure_spawn_allowed(mid,role="full-cycle",pipeline="default",scope="/private/project")

@pytest.mark.parametrize("raw",sorted(set(models.ANTIGRAVITY_RAW_MODELS)-RAW))
def test_other_local_models_remain_blocked_even_with_stored_true(catalog,raw):
    mid="antigravity/"+raw
    models.set_model_flags(mid,agents=True)
    assert models.get_model_spec(mid).default_agents is False
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(mid,scope="/private/multicode",role="worker")

@pytest.mark.parametrize("mid",sorted(ALLOWED))
def test_stale_false_is_respected_then_canonical_owner_update_unblocks_only_target(catalog,mid):
    db.kv_set(models.MODEL_FLAGS_KV_KEY,json.dumps({
        mid:{"agents":False,"dashboard":False},"antigravity/gemini-4-carbon-medium":{"agents":False},
        "gpt-6.2-sol":{"agents":False,"dashboard":True}}))
    with pytest.raises(ValueError,match="disabled for agents"):models.ensure_spawn_allowed(mid,scope="/private/project")
    before=models._load_model_flags()
    flags=models.set_model_flags(mid,agents=True)
    assert flags=={"agents":True,"dashboard":False}
    after=models._load_model_flags()
    assert all(after[key]==value for key,value in before.items() if key!=mid)
    models.ensure_spawn_allowed(mid,scope="/private/project")

@pytest.mark.parametrize("provider",["antigravity","google-antigravity"])
def test_provider_disabled_remains_stronger_than_owner_flags(catalog,monkeypatch,provider):
    mid=models.resolve_model("agy-hydrogen");models.set_model_flags(mid,agents=True)
    monkeypatch.setattr(models,"is_provider_disabled",lambda key:key==provider)
    assert not models.get_model_flags(mid)["agents"]
    with pytest.raises(ValueError,match="disabled"):models.ensure_spawn_allowed(mid,scope="/private/project")

@pytest.mark.parametrize("raw",[r for r in models.ANTIGRAVITY_RAW_MODELS if r.startswith(("claude-opus-5-5","claude-sonnet-5-5"))])
def test_local_claude_55_still_cannot_enter_non_multicast_projects(catalog,raw):
    mid="antigravity/"+raw
    with pytest.raises(ValueError,match="claude_multicast_only"):
        models.ensure_project_model_allowed(mid,"/private/seedon")
    with pytest.raises(ValueError,match="claude_multicast_only"):
        models.ensure_spawn_allowed(mid,scope="/private/seedon")
    models.ensure_project_model_allowed(mid,"/private/multicode")

@pytest.mark.parametrize("subtype",["cron","cron_command","timer","dreaming","scheduler","rate_limit_retry","server_error_retry"])
def test_new_agent_flag_does_not_admit_scheduled_wakes(catalog,subtype):
    from app.antigravity_acp import ensure_interactive_input
    mid=models.resolve_model("agy-hydrogen")
    models.ensure_spawn_allowed(mid,scope="/private/project")
    with pytest.raises(ValueError,match="interactive_only"):
        ensure_interactive_input(mid,MessageProvenance("platform",("Orchestra",),subtype))

@pytest.mark.asyncio
@pytest.mark.parametrize("alias",["agy-hydrogen","agy-argon","agy-flash"])
async def test_actual_mcp_spawn_reaches_canonical_server_admission_before_mock_delivery(catalog,monkeypatch,tmp_path,alias):
    from app import mcp_stdio as m
    from app.routes.sessions import CreateSessionRequest
    monkeypatch.setattr(m,"SCOPE",str(tmp_path));monkeypatch.setattr(m,"WORKER_NAME","owner")
    captured=[]
    async def fake_api(method,path,**kwargs):
        body=kwargs.get("json",{})
        if path=="/api/sessions":
            req=CreateSessionRequest(**body)
            assert req.parent_name=="owner" and req.use_worktree
            models.ensure_spawn_allowed(req.model,scope=req.scope,role=req.role,pipeline="default")
            captured.append(req.model)
            return {"worktree_path":"/synthetic/wt/child","branch":"task-1/child",
                    "repo_path":"/synthetic","git_common_dir":"/synthetic/.git"}
        delivery_id=body["delivery_id"]
        return {"ok":True,"delivery_state":"QUEUED","delivery_id":delivery_id,
                "payload_hash":"synthetic-hash","status_url":"/api/initial-deliveries/"+delivery_id}
    monkeypatch.setattr(m,"_api",fake_api)
    result=await m.spawn_worker(name="child",task="synthetic task",repo_path=str(tmp_path),model=alias)
    assert captured==[models.resolve_model(alias)] and isinstance(result,str)

def test_passport_lists_all_routes_and_actual_transport_limits():
    root=Path(__file__).resolve().parents[1]
    text=(root/".orchestra/pipelines/default/prompts/modules/model-routing.md").read_text()
    kb=(root/".orchestra/kb/models-and-quotas.md").read_text()
    for name in (*ALIASES,"gemini-pro-orchestrator-g1-pro","hubcarbon","hubhydrogen","hubargon"):
        assert name in text
    assert "1,000,000" in text and "1 MiB" in text and "Semaphore(3)" in text
    assert "1–2" in text and "hub-projects.json" in text and "Carbon" in text
    assert "Google" in text and "Google" in kb


@pytest.mark.asyncio
async def test_fixed_g1_route_does_not_invent_high_variant_from_role_fallback(stand,monkeypatch):
    from app.pipeline import get_role,resolve_effort
    from tests.test_antigravity_acp import turn,end
    monkeypatch.setenv("AGY_MOCK_MODE","g1-fixed")
    mid="antigravity/gemini-pro-orchestrator-g1-pro"
    rr=get_role("default","worker")
    b=stand.backend(model=mid.removeprefix("antigravity/"))
    b.effort=resolve_effort(rr.effort,mid,"antigravity")
    events=await turn(b,"fixed route")
    assert end(events).metadata["ok"],"Generic role high must not invent a nonexistent -high model ID"
    assert end(events).metadata["selected_model"]=="gemini-pro-orchestrator-g1-pro"
    assert sum(r["method"]=="session/prompt" for r in stand.trace())==1

def test_fixed_g1_explicit_effort_is_not_silently_discarded():
    from app.pipeline import resolve_effort
    mid="antigravity/gemini-pro-orchestrator-g1-pro"
    assert resolve_effort("high",mid,"antigravity")=="high"
    assert resolve_effort({mid:"high","default":"medium"},mid,"antigravity")=="high"
