"""Exact split-model/thought selection, real fake stdio, no live account calls."""
import asyncio
from collections import Counter
from types import SimpleNamespace
import pytest
from app import antigravity_acp as acp
from app.pipeline import resolve_effort
from tests.test_antigravity_acp import stand,turn,end


@pytest.mark.parametrize('effort,expected', [({'default':'high'},'medium'),({'antigravity':'high','default':'high'},'medium'),({'antigravity/gemini-4-hydrogen-medium':'low','default':'high'},'low'),('high','high'),(None,None)])
def test_explicit_model_suffix_beats_only_general_role_defaults(effort,expected):
    assert resolve_effort(effort,'antigravity/gemini-4-hydrogen-medium','antigravity')==expected


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['split-normal','split-legacy'])
async def test_split_family_ack_then_family_specific_thought_ack_and_warm_reuse(stand,monkeypatch,mode):
    monkeypatch.setenv('AGY_MOCK_MODE',mode)
    b=stand.backend(model='gemini-4-hydrogen-medium');b.effort='medium'
    result=end(await turn(b,'family then thought'))
    assert result.metadata['ok'] and result.metadata['selected_model']=='gemini-4-hydrogen-medium'
    configs=[r['params'] for r in stand.trace() if r['method']=='session/set_config_option']
    assert [(r['configId'],r['value']) for r in configs]==[('model','gemini-4-hydrogen'),('thought_level','medium')]
    assert 'gemini-4-hydrogen-medium' in b._owner.models
    assert 'gemini-4-argon-medium' not in b._owner.models  # Argon advertises only low.
    pid=b._owner.process.pid
    assert end(await turn(b,'warm second turn')).metadata['ok']
    assert b._owner.process.pid==pid and sum(r['method']=='session/set_config_option' for r in stand.trace())==2
    assert Counter(r['method'] for r in stand.trace())['session/prompt']==2


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['split-no-level','split-no-selector','split-family-mismatch','split-thought-mismatch','split-empty-ack','split-conflict','split-new-only-conflict'])
async def test_split_unoffered_or_unconfirmed_combination_refuses_before_prompt(stand,monkeypatch,mode):
    monkeypatch.setenv('AGY_MOCK_MODE',mode)
    b=stand.backend(model='gemini-4-hydrogen-medium');b.effort='medium'
    assert not end(await turn(b,'must refuse')).metadata['ok']
    assert not any(r['method']=='session/prompt' for r in stand.trace())
    assert b.is_alive and not b._owner.failure


@pytest.mark.asyncio
@pytest.mark.parametrize('effort,ok',[('medium',True),('high',False)])
async def test_single_full_slug_without_thought_selector_has_no_effort_fallback(stand,monkeypatch,effort,ok):
    monkeypatch.setenv('AGY_MOCK_MODE','split-normal')
    b=stand.backend(model='gpt-oss-120b-medium');b.effort=effort
    assert end(await turn(b,'single fixed model')).metadata['ok'] is ok
    assert sum(r['method']=='session/prompt' for r in stand.trace())==int(ok)
    assert not any(r.get('params',{}).get('configId')=='thought_level' for r in stand.trace())


@pytest.mark.asyncio
async def test_native_config_notification_updates_state_and_readiness_variants(stand,monkeypatch):
    monkeypatch.setenv('AGY_MOCK_MODE','split-normal')
    b=stand.backend(model='gemini-4-hydrogen-medium');b.effort='medium'
    await turn(b,'one')
    b._update({'sessionUpdate':'config_option_update','configOptions':[{'id':'thought_level','category':'thought_level',
        'currentValue':'low','options':[{'value':'low'},{'value':'medium'}]}]})
    state=b._owner.model_states[b.session_id]
    assert state['current']=='gemini-4-hydrogen' and state['current_thought']=='low'
    assert 'gemini-4-hydrogen-medium' in b._owner.models and 'gemini-4-hydrogen-high' not in b._owner.models
    await turn(b,'must re-confirm requested medium')
    assert b._owner.model_states[b.session_id]['current_thought']=='medium'


def test_readiness_does_not_publish_legacy_variant_denied_by_active_thought_options():
    result={'configOptions':[{'id':'model','category':'model','currentValue':'gemini-4-hydrogen',
        'options':[{'value':'gemini-4-hydrogen'}]},{'id':'thought_level','category':'thought_level',
        'currentValue':'high','options':[{'value':'high'}]}],
        'models':{'availableModels':[{'modelId':'gemini-4-hydrogen-medium'},{'modelId':'gemini-4-hydrogen-high'}]}}
    variants=acp.AcpProfile.published_models(acp.AcpProfile.model_state(result))
    assert 'gemini-4-hydrogen-high' in variants and 'gemini-4-hydrogen-medium' not in variants
