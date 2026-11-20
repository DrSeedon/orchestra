"""Exact g1-pro worker admission, without provider or network activity."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from app import db,models
from app.events import MessageProvenance
from tests.test_antigravity_acp import stand
from tests.test_antigravity_acp_r2 import real_session
from tests.test_antigravity_acp_submission import http_stand

RAW={
 "gemini-4-neon-high","gemini-4-neon-medium","gemini-4-neon-low","gemini-pro-orchestrator-neon",
 "gemini-4-carbon-high","gemini-4-carbon-medium","gemini-4-carbon-low","gemini-pro-orchestrator",
 "gemini-4-hydrogen-high","gemini-4-hydrogen-medium","gemini-4-hydrogen-low",
 "gemini-4-argon-high","gemini-4-argon-medium","gemini-4-argon-low","gemini-pro-orchestrator-g1-pro","gemini-pro-orchestrator-argon",
 "gemini-3.8-flash-high","gemini-3.8-flash-medium","gemini-3.8-flash-low"}
GEMINI_ALLOWED={"antigravity/"+raw for raw in RAW}
CLAUDE_RAW={"claude-"+family+"-5-5-"+level for family in ("opus","sonnet") for level in ("low","medium","high")}
CLAUDE_ALLOWED={"antigravity/"+raw for raw in CLAUDE_RAW}
ALLOWED=GEMINI_ALLOWED|CLAUDE_ALLOWED|{"antigravity/gpt-oss-120b-medium"}
WORKER_ALLOWED=ALLOWED
ALIASES={
 "agy-neon":"gemini-4-neon-medium","agy-neon-high":"gemini-4-neon-high",
 "agy-neon-medium":"gemini-4-neon-medium","agy-neon-low":"gemini-4-neon-low","agy-neon-orch":"gemini-pro-orchestrator-neon",
 "agy-hydrogen":"gemini-4-hydrogen-high",
 "agy-hydrogen-med":"gemini-4-hydrogen-medium","agy-argon":"gemini-4-argon-medium",
 "agy-argon-high":"gemini-4-argon-high","agy-flash":"gemini-3.8-flash-medium","agy-flash-high":"gemini-3.8-flash-high",
 "agy-opus":"claude-opus-5-5-medium","agy-opus-high":"claude-opus-5-5-high",
 "agy-sonnet":"claude-sonnet-5-5-medium","agy-sonnet-high":"claude-sonnet-5-5-high"}

@pytest.fixture
def catalog(tmp_path,monkeypatch):
    monkeypatch.setattr(db,"DB_PATH",tmp_path/"catalog.db");db.init_db()
    monkeypatch.setattr(models,"is_provider_disabled",lambda _:False)

def test_default_agent_exception_is_exactly_the_owner_list(catalog):
    assert models.ANTIGRAVITY_G1_GEMINI_AGENT_MODELS==GEMINI_ALLOWED
    assert models.ANTIGRAVITY_G1_CLAUDE_AGENT_MODELS==CLAUDE_ALLOWED
    assert models.ANTIGRAVITY_G1_AGENT_MODELS==ALLOWED and len(ALLOWED)==26
    for mid in ("antigravity/"+raw for raw in models.ANTIGRAVITY_RAW_MODELS):
        assert models.get_model_spec(mid).default_agents is (mid in ALLOWED)

@pytest.mark.parametrize("mid",sorted(WORKER_ALLOWED))
def test_all_eleven_pass_the_real_subscription_and_flags_gates(catalog,mid):
    assert models.get_model_flags(mid)["agents"]
    assert models.get_model_spec(mid).context_length==(128000 if mid=="antigravity/gpt-oss-120b-medium" else 1000000)
    models.ensure_spawn_allowed(mid,role="worker",pipeline="default",scope="/private/project")

@pytest.mark.parametrize("mid",sorted(models.ANTIGRAVITY_NEON_MODEL_IDS))
def test_neon_is_orchestrator_only(catalog,mid):
    models.ensure_spawn_allowed(mid,role="orchestrator",pipeline="default",scope="/private/project")
    models.ensure_spawn_allowed(mid,role="worker",pipeline="default",scope="/private/project")

@pytest.mark.parametrize("alias,raw",list(ALIASES.items()))
def test_all_requested_aliases_are_stable_and_admitted(catalog,alias,raw):
    mid=models.resolve_model(alias)
    assert mid=="antigravity/"+raw
    role="orchestrator" if mid in models.ANTIGRAVITY_NEON_MODEL_IDS else "full-cycle"
    models.ensure_spawn_allowed(mid,role=role,pipeline="default",scope="/private/project")

@pytest.mark.parametrize("raw",sorted(set(models.ANTIGRAVITY_RAW_MODELS)-RAW-CLAUDE_RAW-{"gpt-oss-120b-medium"}))
def test_other_local_models_remain_blocked_even_with_stored_true(catalog,raw):
    mid="antigravity/"+raw
    models.set_model_flags(mid,agents=True)
    assert models.get_model_spec(mid).default_agents is False
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(mid,scope="/private/multicode",role="worker")

@pytest.mark.parametrize("mid",sorted(WORKER_ALLOWED))
def test_stale_false_is_respected_then_canonical_owner_update_unblocks_only_target(catalog,mid):
    db.kv_set(models.MODEL_FLAGS_KV_KEY,json.dumps({
        mid:{"agents":False,"dashboard":False},"antigravity/claude-sonnet-4-6":{"agents":False},
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

@pytest.mark.parametrize("mid",sorted(CLAUDE_ALLOWED))
def test_our_local_claude_55_is_admitted_outside_multicast(catalog,mid):
    models.ensure_project_model_allowed(mid,"/home/kesha/projects/seedon")
    models.ensure_spawn_allowed(mid,scope="/home/kesha/projects/seedon",role="worker")
    assert models.get_model_flags(mid)["agents"]

@pytest.mark.parametrize("model",["hubopus","hubsonnet","hub-claude-opus-5-5","hub-claude-sonnet-5-5",
    "claude-opus-5-5[1m]","claude-sonnet-5-5[1m]","antigravity/claude-opus-4-6-thinking",
    "antigravity/claude-sonnet-4-6","antigravity/claude-opus-5-5-unreviewed"])
def test_other_claude_routes_remain_multicast_only(catalog,model):
    models.ensure_project_model_allowed(model,"/home/kesha/projects/seedon")
    models.ensure_project_model_allowed(model,"/home/kesha/projects/multicode")

@pytest.mark.parametrize("subtype",["cron","cron_command","timer","dreaming","scheduler","rate_limit_retry","server_error_retry"])
def test_new_agent_flag_does_not_admit_scheduled_wakes(catalog,subtype):
    from app.antigravity_acp import ensure_interactive_input
    mid=models.resolve_model("agy-hydrogen")
    models.ensure_spawn_allowed(mid,scope="/private/project")
    with pytest.raises(ValueError,match="interactive_only"):
        ensure_interactive_input(mid,MessageProvenance("platform",("Orchestra",),subtype))

@pytest.mark.asyncio
@pytest.mark.parametrize("alias",["agy-hydrogen","agy-argon","agy-flash","agy-opus","agy-sonnet"])
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


@pytest.mark.asyncio
async def test_real_worker_initial_delivery_accepts_verified_parent_once(stand,http_stand,monkeypatch):
    import asyncio,uuid
    from unittest.mock import Mock
    from app.mcp_proof import issue_mcp_proof
    from tests.test_message_delivery_receipts_380 import _session_record
    s,client,manager=http_stand
    parent=_session_record(session_id="gemini-parent",name="gemini-parent",scope=s.scope)
    parent.update(is_orchestrator=True,role="orchestrator");db.save_session(parent)
    s.model="antigravity/gemini-4-argon-medium";s.is_orchestrator=False
    s.parent_id=parent["id"];s.parent_name=parent["name"]
    # The shared fixture starts as an orchestrator; that durable identity flag
    # is intentionally immutable in save_session(). Create the worker fixture state.
    with db._conn() as connection:connection.execute("UPDATE sessions SET is_orchestrator=0 WHERE id=?",(s.id,))
    s._persist();await s._drain_persist()
    # Suppress external parent notification only; actual SessionManager, listener,
    # receipt owner, turn handling and fake-stdio submission remain real.
    monkeypatch.setattr(s._turns,"fire_auto_report",Mock())
    did=str(uuid.uuid4())
    body={"delivery_id":did,"scope":s.scope,"sender":parent["name"],"message":"one assigned task"}
    headers={"x-orchestra-session-id":parent["id"],"x-orchestra-mcp-proof":issue_mcp_proof(parent["id"])}
    response=await client.post("/api/sessions/"+s.name+"/initial-deliveries",json=body,headers=headers)
    assert response.status_code==202,response.text
    async with asyncio.timeout(5):
        while True:
            resource=(await client.get("/api/initial-deliveries/"+did,params={"scope":s.scope})).json()
            if resource["delivery_state"] in {"SUBMITTED","FAILED_BEFORE_SUBMIT","DELIVERY_UNKNOWN"}:break
            await asyncio.sleep(.01)
        if s._listen_task:await s._listen_task
    assert resource["delivery_state"]=="SUBMITTED",resource
    assert s._last_turn_ok
    again=await client.post("/api/sessions/"+s.name+"/initial-deliveries",json=body,headers=headers)
    assert again.status_code==202
    assert sum(r["method"]=="session/prompt" for r in stand.trace())==1


@pytest.mark.asyncio
@pytest.mark.parametrize("case",["missing-proof","wrong-proof","foreign-parent","wrong-scope","sender-spoof"])
async def test_native_initial_ingress_rejects_foreign_or_unproved_assignment_before_rpc(stand,http_stand,case):
    import uuid
    from app.mcp_proof import issue_mcp_proof
    from tests.test_message_delivery_receipts_380 import _session_record
    s,client,_=http_stand
    parent=_session_record(session_id="initial-parent",name="initial-parent",scope=s.scope+"/foreign" if case=="wrong-scope" else s.scope)
    parent.update(is_orchestrator=True,role="orchestrator");db.save_session(parent)
    s.model="antigravity/gemini-4-argon-medium";s.is_orchestrator=False
    s.parent_id=parent["id"];s.parent_name=parent["name"]
    with db._conn() as connection:connection.execute("UPDATE sessions SET is_orchestrator=0 WHERE id=?",(s.id,))
    s._persist();await s._drain_persist()
    source=parent
    if case=="foreign-parent":
        source=_session_record(session_id="foreign",name="foreign",scope=s.scope)
        source.update(is_orchestrator=True,role="orchestrator");db.save_session(source)
    headers={"x-orchestra-session-id":source["id"],"x-orchestra-mcp-proof":issue_mcp_proof(source["id"])}
    if case=="missing-proof":headers={}
    if case=="wrong-proof":headers["x-orchestra-mcp-proof"]="invalid-synthetic-proof"
    body={"delivery_id":str(uuid.uuid4()),"scope":s.scope,"sender":"spoof" if case=="sender-spoof" else parent["name"],"message":"must deny"}
    response=await client.post("/api/sessions/"+s.name+"/initial-deliveries",json=body,headers=headers)
    assert response.status_code==403 and not stand.trace()


def test_worker_parent_event_is_bound_and_scheduled_or_compact_input_stays_closed(catalog,tmp_path):
    from app.antigravity_acp import ensure_interactive_input
    from tests.test_message_delivery_receipts_380 import _session_record
    parent=_session_record(session_id="p",name="p",scope=str(tmp_path))
    parent.update(is_orchestrator=True,role="orchestrator");db.save_session(parent)
    row=_session_record(session_id="w",name="w",scope=str(tmp_path))
    row.update(parent_id="p",parent_name="p",model="antigravity/gemini-4-argon-medium");db.save_session(row)
    provenance=MessageProvenance("agent",("p",),"http_send")
    ensure_interactive_input(row["model"],provenance,target_session=row)
    with pytest.raises(ValueError):ensure_interactive_input(row["model"],provenance,target_session=row,allow_child_agent=False)
    for subtype in ("cron","cron_command","timer","scheduler","dreaming","limit_wake","rate_limit_retry","server_error_retry"):
        with pytest.raises(ValueError):
            ensure_interactive_input(row["model"],MessageProvenance("agent",("p",),subtype),target_session=row)
    row["parent_id"]="foreign";db.save_session(row)
    with pytest.raises(ValueError):ensure_interactive_input(row["model"],provenance,target_session=row)
