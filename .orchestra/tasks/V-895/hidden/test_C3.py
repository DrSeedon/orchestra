from app.session import AgentSession

def _policy(backend):
    s = AgentSession.__new__(AgentSession)
    s.backend_type = backend
    return s._precompact_policy()

def test_claude_floor_30():
    p = _policy("claude")
    assert p["min_context_pct"] == 30 and p["arm_threshold"] == 30
    assert AgentSession.PRECOMPACT_MIN_CONTEXT_PCT == 30

def test_codex_floor_5_separate_constant():
    p = _policy("codex")
    assert p["min_context_pct"] == 5 and p["arm_threshold"] == 5
    assert AgentSession.CODEX_PRECOMPACT_MIN_CONTEXT_PCT == 5
