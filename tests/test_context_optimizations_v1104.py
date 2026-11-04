"""Behavioral contracts for first-delivery context optimizations (no provider calls)."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.usage_contract import AggregateUsage, TurnUsage, current_context
from app.tool_output_compactor import ToolResultStore, compact_text
from app.runtime_history import PrefixCacheShape, explain_prefix_change


@pytest.mark.parametrize("inclusive,expected", [(False, 130), (True, 100)])
def test_usage_disjoint_buckets_do_not_change_legacy_input(inclusive, expected):
    usage = AggregateUsage.normalized(input_tokens=100, output_tokens=10,
                                     cache_read_tokens=20, cache_create_tokens=10,
                                     input_includes_cache=inclusive)
    metadata = TurnUsage(usage, current_context(None, 1000)).metadata()
    normalized = metadata['normalized_usage']
    assert metadata['input_tokens'] == 100
    assert metadata['cache_read'] == 20
    assert normalized['prompt_total'] == expected
    assert normalized['fresh_input'] + normalized['cache_read'] + normalized['cache_write'] == expected
    assert normalized['cache_read_fraction'] == 20 / expected
    assert normalized['output'] == 10
    assert normalized['accuracy'] == 'reported'


def test_unknown_usage_is_not_zero_and_is_independent_of_unknown_context():
    unknown = AggregateUsage.normalized(accuracy='unknown').derived()
    assert unknown['prompt_total'] is None
    assert unknown['cache_read'] is None
    assert unknown['cache_read_fraction'] is None
    measured = TurnUsage(AggregateUsage.normalized(input_tokens=100), current_context(None, 1000))
    assert measured.metadata()['context_known'] is False
    assert measured.metadata()['normalized_usage']['prompt_total'] == 100
    assert AggregateUsage.normalized().derived()['cache_read_fraction'] is None
    assert AggregateUsage.normalized(accuracy='estimated').derived()['accuracy'] == 'estimated'


@pytest.mark.parametrize('value', [None, True, -1, float('inf'), 'n/a', 1.5])
def test_invalid_legacy_counters_remain_fail_soft_but_measurement_is_unknown(value):
    usage = AggregateUsage.normalized(input_tokens=value)
    assert usage.input_tokens >= 0
    assert usage.derived()['accuracy'] == 'unknown'


def test_normalized_measurements_are_durable_and_replay_does_not_overwrite(tmp_path, monkeypatch):
    from app import db
    from app.usage_analytics import daily_usage
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'usage.db')
    db.init_db()
    fields = dict(session_id='s', runtime='codex', model='gpt-6.1-sol', ok=True,
                  stop_reason='end_turn', cost_usd=0, input_tokens=100, output_tokens=10,
                  cache_read_tokens=80, cache_create_tokens=0)
    assert db.turn_usage_add(event_id='one', **fields)
    assert not db.turn_usage_add(event_id='one', **{**fields, 'input_tokens': 999})
    assert db.turn_usage_add(event_id='hub', **{**fields, 'runtime': 'hub', 'model': 'hub-gpt-6.1-sol',
                                              'input_tokens': 0, 'output_tokens': 0, 'cache_read_tokens': 0})
    measured = daily_usage(1)[0]['normalized_usage']
    assert measured['codex']['prompt_total'] == 100
    assert measured['codex']['cache_read_fraction'] == .8
    assert measured['hub']['accuracy'] == 'unknown'
    assert measured['hub']['prompt_total'] is None
    assert measured['hub']['estimated_cache_warmth_pct'] is None
    with db._conn() as conn:
        assert conn.execute('SELECT COUNT(*) FROM turn_usage_measurements').fetchone()[0] == 2


def test_mixed_observation_does_not_publish_partial_totals_as_complete():
    from app.usage_analytics import summarize_usage_measurements
    known = AggregateUsage.normalized(input_tokens=100, cache_read_tokens=80).derived()
    summary = summarize_usage_measurements([known], 2)
    assert summary['accuracy'] == 'unknown'
    assert summary['cache_read_fraction'] is None
    assert summary['prompt_total'] is None
    assert summary['observed_totals']['prompt_total'] == 180
    assert summary['unknown_turns'] == 1


def test_rtk_preserves_middle_errors_tracebacks_exit_and_summary():
    text = ('COMMAND START\n' + 'compile module\n' * 600
            + 'Traceback (most recent call last):\n  File "x.py", line 3\n    run()\nValueError: bad input\n'
            + 'compile next\n' * 600 + 'FAILED: summary\nexit_code=1\n')
    result = compact_text(text, 900)
    assert result == compact_text(text, 900)
    assert 'repeated' in result.preview
    for line in ('COMMAND START', 'Traceback', 'File "x.py"', 'run()', 'ValueError: bad input', 'FAILED: summary', 'exit_code=1'):
        assert line in result.preview
    assert result.total_chars == len(text)
    assert result.omitted_chars > 0
    assert len(result.preview) < 1200


@pytest.mark.parametrize('text', ['plain\n', '{"valid":"json"}', 'юникод 😀\n', ''])
def test_short_results_remain_byte_identical(text):
    store = ToolResultStore()
    assert store.present(text, owner='one') == text
    assert compact_text(text).omitted_chars == 0


def test_long_single_line_keeps_both_edges():
    result = compact_text('START' + 'ж' * 10000 + 'END', 600)
    assert result.preview.startswith('START')
    assert result.preview.endswith('END')
    assert result.omitted_chars > 9000


def test_archive_pages_reconstruct_exact_unicode_original_and_are_scoped():
    store = ToolResultStore()
    original = 'α😀ж\r\n' * 3000 + 'final summary\n'
    try:
        shown = json.loads(store.present(original, owner='one', budget=800))
        assert not shown['complete'] and shown['next_cursor'] == 0
        assert shown['total_chars'] == len(original)
        parts = []
        cursor = 0
        while cursor is not None:
            page = store.read(shown['result_id'], owner='one', cursor=cursor, limit=137)
            parts.append(page['text'])
            cursor = page['next_cursor']
        assert ''.join(parts) == original
        assert page['complete']
        with pytest.raises(ValueError, match='outside caller scope'):
            store.read(shown['result_id'], owner='other')
        for cursor in (-1, True, len(original) + 1):
            with pytest.raises(ValueError):
                store.read(shown['result_id'], owner='one', cursor=cursor)
    finally:
        store.close()


def test_archive_eviction_and_expiry_are_explicit(monkeypatch):
    import app.tool_output_compactor as module
    clock = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    store = ToolResultStore(max_results=1, ttl_seconds=10)
    first = json.loads(store.present('x\n' * 1000, owner='one', budget=300))
    second = json.loads(store.present('y\n' * 1000, owner='one', budget=300))
    with pytest.raises(ValueError, match='expired'):
        store.read(first['result_id'], owner='one')
    clock[0] += 11
    with pytest.raises(ValueError, match='expired'):
        store.read(second['result_id'], owner='one')
    store.close()


def test_archive_exact_repeats_keep_ids_and_guard_identity_stable():
    store = ToolResultStore()
    original = 'same output\n' * 2000
    try:
        first = store.present(original, owner='one')
        assert store.present(original, owner='one') == first
        assert json.loads(store.present(original, owner='two'))['result_id'] != json.loads(first)['result_id']
    finally:
        store.close()


@pytest.mark.asyncio
async def test_harness_bash_does_not_discard_raw_output_above_old_capture_cap(tmp_path):
    from app.harness import tools
    shown = json.loads(await tools.bash("awk 'BEGIN { for(i=0;i<45000;i++) print \"row\"; print \"ERROR: end\" }'", str(tmp_path)))
    assert 'ERROR: end' in shown['preview']
    assert shown['total_chars'] > tools.OUTPUT_CAP * 4
    page, changed = await tools.dispatch('read_tool_result_page', {
        'result_id': shown['result_id'], 'cursor': shown['total_chars'] - 11, 'limit': 100,
    }, str(tmp_path))
    assert json.loads(page)['text'].endswith('ERROR: end\n')
    assert not changed


@pytest.mark.asyncio
async def test_long_failed_bash_result_keeps_error_event_and_exact_repeat_guard(tmp_path):
    from app.harness.loop import AgentLoop
    from app.harness import tools
    class NoMCP:
        def has_tool(self, name):
            return False
        def display_name(self, name):
            return name
    loop = AgentLoop(object(), NoMCP(), str(tmp_path), [], tools.tool_schemas(), 100000)
    call = {'id': 'one', 'function': {'name': 'bash', 'arguments': json.dumps({
        'command': "awk 'BEGIN {for(i=0;i<5000;i++) print i}'; exit 7",
    })}}
    events = [event async for event in loop._dispatch_tool(call)]
    result = next(event for event in events if event.type == 'tool_result')
    assert result.metadata['is_error'] is True
    assert json.loads(result.content)['preview'].startswith('exit_code=7')
    assert len(loop.history) == 1 and loop.history[0]['role'] == 'tool'


@pytest.mark.asyncio
async def test_mcp_log_json_remains_parseable_and_archive_is_readable(monkeypatch):
    from unittest.mock import AsyncMock
    from app import mcp_stdio as mcp
    raw = 'build module\n' * 3000 + 'failed: end\n'
    monkeypatch.setattr(mcp, '_api', AsyncMock(return_value={'matches': [{'id': 1, 'content': raw}]}))
    result = json.loads(await mcp.search_logs('build'))
    assert result['matches'][0]['id'] == 1
    metadata = json.loads(result['matches'][0]['content'])
    assert 'failed: end' in metadata['preview']
    assert metadata['read_with'].startswith('read_log_result_page(')
    page = json.loads(await mcp.read_tool_result_page(metadata['result_id'], cursor=len(raw) - 12))
    assert page['text'] == raw[-12:]


def test_worker_memory_large_index_refreshes_fingerprint_and_short_is_unchanged(tmp_path):
    from app.prompting import load_worker_memory, refresh_worker_memory
    root = tmp_path / '.orchestra'
    (root / 'workers').mkdir(parents=True)
    (root / 'layout.json').write_text('{}')
    path = root / 'workers' / 'w.md'
    path.write_text(' short memory \n')
    assert load_worker_memory('w', 'worker', str(tmp_path)) == 'short memory'
    raw = '# Identity\n' + 'old working fact\n' * 900 + '## Active rules\nMust preserve accepted work.\n## Current\nLatest: pending QA.\n'
    path.write_text(raw)
    overview = load_worker_memory('w', 'worker', str(tmp_path))
    assert len(overview) <= 4000
    assert str(path) in overview
    assert hashlib.sha256(path.read_bytes()).hexdigest() in overview
    for section in ('# Identity', '## Active rules', '## Current', 'Must preserve accepted work.', 'Latest: pending QA.'):
        assert section in overview
    assert f'1-{len(raw.splitlines())}' in overview
    assert '902-903 ## Active rules' in overview
    prompt = refresh_worker_memory('SYSTEM', 'w', 'worker', str(tmp_path))
    assert refresh_worker_memory(prompt, 'w', 'worker', str(tmp_path)) == prompt
    path.write_text(raw.replace('pending QA', 'accepted'))
    fresh = refresh_worker_memory(prompt, 'w', 'worker', str(tmp_path))
    assert fresh != prompt and 'accepted' in fresh
    assert fresh.count('<worker-memory>') == 1
    assert not path.with_suffix('.overview.md').exists()


def test_prefix_shape_stable_serialization_and_independent_memory_reason():
    before = PrefixCacheShape.from_components(system_prompt='SYSTEM\n\n<worker-memory>A</worker-memory>',
                                              tool_schemas={'a': 1, 'b': 2}, history_prefix=['one'])
    reordered = PrefixCacheShape.from_components(system_prompt='SYSTEM\n\n<worker-memory>A</worker-memory>',
                                                 tool_schemas={'b': 2, 'a': 1}, history_prefix=['one'])
    assert explain_prefix_change(before, reordered) == ['prefix_stable']
    after = PrefixCacheShape.from_components(system_prompt='SYSTEM\n\n<worker-memory>B</worker-memory>',
                                             tool_schemas={'a': 1, 'b': 2}, history_prefix=['one'])
    assert explain_prefix_change(before, after) == ['worker_memory_changed']
    assert all(len(value) == 64 for value in after.as_dict().values())


@pytest.mark.parametrize(('field', 'reason'), [
    ('system_prompt_hash', 'system_prompt_changed'), ('tool_schemas_hash', 'tool_schemas_changed'),
    ('skills_index_hash', 'skills_index_changed'), ('worker_memory_hash', 'worker_memory_changed'),
    ('history_prefix_hash', 'history_compacted_or_rewritten'),
])
def test_prefix_reasons_identify_each_changed_component(field, reason):
    before = PrefixCacheShape.from_components()
    assert explain_prefix_change(before, replace(before, **{field: 'new'})) == [reason]


def test_prefix_tracker_ignores_appends_but_reports_rewrites():
    from app.runtime_history import PrefixCacheTracker
    tracker = PrefixCacheTracker()
    assert tracker.observe(system_prompt='SYS', tool_schemas=[], history=['one']) == ['prefix_stable']
    assert tracker.observe(system_prompt='SYS', tool_schemas=[], history=['one', 'two']) == ['prefix_stable']
    assert tracker.observe(system_prompt='SYS', tool_schemas=[], history=['summary']) == ['history_compacted_or_rewritten']


@pytest.mark.asyncio
async def test_mcp_and_harness_pagination_tools_do_not_collide():
    from app import mcp_stdio
    from app.harness import prompts, tools
    mcp_schemas = [
        {'type': 'function', 'function': {'name': tool.name, 'parameters': tool.inputSchema}}
        for tool in await mcp_stdio.mcp.list_tools()
    ]
    merged = prompts.merge_tool_schemas(tools.tool_schemas(), mcp_schemas)
    names = {schema['function']['name'] for schema in merged}
    assert {'read_tool_result_page', 'read_log_result_page'} <= names


def test_route_recommendation_is_advisory_and_rejects_disabled_candidates(monkeypatch):
    from app import models
    monkeypatch.setattr(models, 'ensure_spawn_allowed', lambda *args, **kwargs: None)
    result = models.recommend_task_route('Sort these paths alphabetically', 'worker', 'hubsol')
    assert result['recommended_model'] == models.resolve_model('hubluna')
    assert result['selected_model'] == 'hubsol' and result['advisory_only']
    assert result['quota_check_required']
    assert models.recommend_task_route('Count paths', 'worker', 'hubluna')['recommended_model'] == 'hubluna'
    for task in ('Fix bug in Python', 'List architecture risks', 'Отладь код', 'Format SQL code'):
        assert models.recommend_task_route(task, 'worker', 'hubsol')['recommended_model'] == 'hubsol'
    def refuse(*args, **kwargs):
        raise ValueError('disabled route')
    monkeypatch.setattr(models, 'ensure_spawn_allowed', refuse)
    assert models.recommend_task_route('Count paths', 'worker', 'hubsol')['recommended_model'] == 'hubsol'
    assert models.recommend_task_route('Count paths', 'orchestrator', 'hubsol')['recommended_model'] == 'hubsol'


def test_role_profiles_preserve_unknown_roles_and_result_pagination():
    from app.tool_scoping import role_tool_names
    names = {'read', 'write', 'spawn_worker', 'search_logs', 'read_tool_result_page'}
    assert role_tool_names(names, 'orchestrator') == names
    assert role_tool_names(names, 'custom') == names
    assert role_tool_names(names, 'worker') == names - {'spawn_worker'}
    assert role_tool_names(names, 'reviewer') == names - {'write', 'spawn_worker'}


