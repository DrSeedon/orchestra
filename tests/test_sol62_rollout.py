"""Owner-approved local 6.2 defaults and confined project-doc links."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app import db,models,pipeline
from app.backend_codex import CodexBackend
from app.session import AgentSession

@pytest.mark.parametrize("alias,expected",[
    ("sol","gpt-6.2-sol"),("codex","gpt-6.2-sol"),("astra","gpt-6.2-astra"),
    ("sol61","gpt-6.1-sol"),("gpt61sol","gpt-6.1-sol"),
    ("astra6","gpt-6-astra"),("gpt6astra","gpt-6-astra")])
def test_canonical_and_legacy_aliases_are_explicit(alias,expected):
    assert models.resolve_model(alias)==expected


@pytest.mark.parametrize("role,expected",[
    ("orchestrator","high"),("sub-orchestrator","high"),("reviewer","high"),
    ("implementer","medium"),("worker","medium"),("full-cycle","medium"),("specialist","medium")])
def test_exact_role_effort_and_manifest_default(role,expected):
    rr=pipeline.get_role("default",role)
    assert pipeline.resolve_effort(rr.effort,"gpt-6.2-sol","codex")==expected
    assert pipeline.resolve_effort(rr.effort,"gpt-6.2-astra","codex")=="high"
    assert pipeline.default_codex_effort("gpt-6.2-sol",role=role)==expected
    if role in {"orchestrator","sub-orchestrator","reviewer"}:
        assert models.resolve_model(rr.model)=="gpt-6.2-sol"


@pytest.mark.parametrize("explicit",["low","high"])
def test_explicit_coding_effort_remains_available(explicit):
    assert pipeline.resolve_effort(explicit,"gpt-6.2-sol","codex")==explicit
    assert pipeline.resolve_effort({"gpt-6.2-sol":explicit},"gpt-6.2-sol","codex")==explicit


@pytest.mark.parametrize("role,model,expected",[
    ("worker","gpt-6.2-sol","medium"),("orchestrator","gpt-6.2-sol","high"),
    ("reviewer","gpt-6.2-sol","high"),("worker","gpt-6.2-astra","high")])
def test_real_factory_uses_role_default_and_never_requests_fast(tmp_path,role,model,expected):
    s=AgentSession(id="factory",name="factory",scope=str(tmp_path),cwd=str(tmp_path),
        model=model,backend_type="codex",role=role,effort=None,pipeline="default",
        is_orchestrator=role=="orchestrator",mcp_servers={})
    b=s._make_backend(force_fresh=True)
    assert b.reasoning_effort==expected
    cmd=b._codex_command()
    assert f'model_reasoning_effort="{expected}"' in cmd
    assert not any("service_tier" in value or "fast"==value for value in cmd)
    assert "features.multi_agent=false" in cmd
    assert "features.sleep_tool=false" in cmd


def test_shared_prompt_reports_required_missing_resources_and_no_defensive_mutex():
    for role in ("orchestrator","reviewer","implementer","worker","full-cycle","specialist"):
        text=pipeline.build_system_prompt("default",role)
        assert "BLOCKED / MISSING RESOURCE" in text and "exact path/name" in text
        assert "threading.Lock()" in text and "single-threaded asyncio" in text


def configure_budget(tmp_path,budget=4):
    p=tmp_path/"codex";p.mkdir()
    (p/"config.toml").write_text(f"project_doc_max_bytes={budget}\n")
    return str(p)


@pytest.mark.parametrize("chain",[False,True])
def test_internal_project_doc_link_preserves_budget_measurement(tmp_path,chain):
    from app.prompting import codex_project_doc_preflight
    root=tmp_path/"project";root.mkdir()
    content="α\nβ\nγ\n".encode()
    target=root/"CLAUDE.md";target.write_bytes(content)
    if chain:
        (root/"intermediate").symlink_to("CLAUDE.md")
    (root/"AGENTS.md").symlink_to("intermediate" if chain else "CLAUDE.md")
    result=codex_project_doc_preflight(str(root),codex_home=configure_budget(tmp_path))
    assert result.actual_bytes==len(content) and result.first_truncated_line==2
    assert "unsafe symlink" not in result.diagnostic
    assert "exceeds configured" in result.diagnostic
    assert target.read_bytes()==content and (root/"AGENTS.md").is_symlink()


@pytest.mark.parametrize("kind",["outside","prefix-sibling","broken","cycle","directory","parent-chain"])
def test_unsafe_project_doc_links_never_read_external_content(tmp_path,monkeypatch,kind):
    from app.prompting import codex_project_doc_preflight
    root=tmp_path/"project";root.mkdir()
    outside=tmp_path/"project-other";outside.mkdir()
    source=outside/"secret.md";source.write_text("synthetic-external-do-not-read")
    doc=root/"AGENTS.md"
    if kind in {"outside","prefix-sibling"}:doc.symlink_to(source)
    elif kind=="broken":doc.symlink_to(root/"missing.md")
    elif kind=="cycle":doc.symlink_to("AGENTS.md")
    elif kind=="directory":doc.symlink_to(outside)
    else:
        (root/"escape").symlink_to(outside,target_is_directory=True)
        doc.symlink_to("escape/secret.md")
    original=Path.read_bytes
    def read(p,*a,**kw):
        assert p!=source,"external document was read"
        return original(p,*a,**kw)
    monkeypatch.setattr(Path,"read_bytes",read)
    result=codex_project_doc_preflight(str(root),codex_home=configure_budget(tmp_path))
    assert "unsafe symlink" in result.diagnostic and result.actual_bytes is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role,target,effort",[
    ("orchestrator","gpt-6.2-sol","high"),("reviewer","gpt-6.2-sol","high"),
    ("worker","gpt-6.2-sol","medium"),("worker","gpt-6.2-astra","high")])
async def test_real_model_switch_persists_effort_and_native_history(tmp_path,role,target,effort):
    db.init_db()
    s=AgentSession(id="switch",name="switch",scope=str(tmp_path),cwd=str(tmp_path),
        model="gpt-6.1-sol",backend_type="codex",role=role,is_orchestrator=role=="orchestrator",
        effort="medium",pipeline="default",session_id="retained-native-id",mcp_servers={})
    s._backend=CodexBackend("gpt-6.1-sol",str(tmp_path),resume_thread_id=s.session_id,reasoning_effort="medium")
    s._persist();await s._drain_persist()
    history=list(s.session_id_history)
    result=await s._change_model_in_place_locked(target,s.model,"codex")
    await s._await_log_futures()
    assert result["ok"] and result["history_transfer"]["mode"]=="native_in_place"
    assert s.model==target and s.effort==s._backend.reasoning_effort==effort
    assert s.session_id==s._backend.session_id=="retained-native-id" and s.session_id_history==history
    row=db.get_session(s.id)
    assert row["model"]==target and row["effort"]==effort and row["session_id"]=="retained-native-id"
    await s.abort_unpublished()


@pytest.mark.asyncio
async def test_failed_model_persistence_rolls_back_model_effort_and_native_id(tmp_path,monkeypatch):
    import app.session as module
    db.init_db()
    s=AgentSession(id="rollback",name="rollback",scope=str(tmp_path),cwd=str(tmp_path),
        model="gpt-6.1-sol",backend_type="codex",role="orchestrator",is_orchestrator=True,
        effort="medium",pipeline="default",session_id="retained",mcp_servers={})
    s._backend=CodexBackend(s.model,str(tmp_path),resume_thread_id=s.session_id,reasoning_effort="medium")
    s._persist();await s._drain_persist()
    def fail(*args,**kwargs):raise RuntimeError("synthetic persistence error")
    monkeypatch.setattr(module,"save_session",fail)
    result=await s._change_model_in_place_locked("gpt-6.2-sol",s.model,"codex")
    assert not result["ok"] and not s._handoff_recovery_required
    assert s.model==s._backend.model=="gpt-6.1-sol"
    assert s.effort==s._backend.reasoning_effort=="medium" and s.session_id=="retained"
    assert db.get_session(s.id)["model"]=="gpt-6.1-sol"
    await s.abort_unpublished()


def test_new_alias_does_not_bypass_manual_or_disabled_guards(monkeypatch):
    assert {"gpt-6.2-sol","gpt-6.2-astra"}<=models.NATIVE_CODEX_AGENT_MODELS
    for mid in ("sol","astra"):
        models.ensure_spawn_allowed(models.resolve_model(mid))
    with pytest.raises(ValueError):models.ensure_spawn_allowed(models.resolve_model("terra"))
    monkeypatch.setattr(models,"is_provider_disabled",lambda name:True)
    with pytest.raises(ValueError):models.ensure_dashboard_visible("gpt-6.2-sol")


@pytest.mark.asyncio
async def test_model_switch_refuses_context_that_cannot_fit_without_reset(tmp_path):
    s=AgentSession(id="large-context",name="large-context",scope=str(tmp_path),cwd=str(tmp_path),
        model="gpt-6.1-sol",backend_type="codex",role="orchestrator",is_orchestrator=True,
        effort="high",pipeline="default",session_id="keep-native",mcp_servers={})
    s._last_context={"total_tokens":500001,"max_tokens":828400,"percentage":61}
    result=await s._change_model_in_place_locked("gpt-6.2-sol",s.model,"codex")
    assert not result["ok"] and result["error_code"]=="handoff_context_overflow"
    assert s.model=="gpt-6.1-sol" and s.session_id=="keep-native" and s._backend is None
