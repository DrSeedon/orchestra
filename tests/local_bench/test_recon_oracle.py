import asyncio
import json
from pathlib import Path

import pytest

from scripts.local_bench import recon_oracle, runner
from scripts.local_bench.config import read

SOURCE = "def a():\n    return b()\n\n\ndef b():\n    return 1\n\n\ndef unused():\n    pass\n"
GOLDEN = {
    'task_id': 'synthetic',
    'checks': [
        {'id': 'chain', 'path': 'answer.chain', 'kind': 'ordered', 'expected': ['m.py::a', 'm.py::b']},
        {'id': 'callers', 'path': 'answer.callers', 'kind': 'set', 'expected': ['m.py::a']},
        {'id': 'found', 'path': 'answer.found', 'kind': 'equals', 'expected': True},
    ],
    'anchors': [{'id': 'b-def', 'path': 'm.py', 'pattern': r'def b\('}],
}
GOOD = {'answer': {'chain': ['m.py::a', 'm.py::b'], 'callers': ['m.py::a'], 'found': True},
        'evidence': [{'path': 'm.py', 'start': 5, 'end': 6}]}


@pytest.fixture
def root(tmp_path):
    (tmp_path / 'm.py').write_text(SOURCE)
    return tmp_path


def run(golden, answer, root, wrap=lambda s: s):
    text = answer if isinstance(answer, str) else wrap(json.dumps(answer))
    return recon_oracle.score(golden, text, root)


def mutate(**changes):
    value = json.loads(json.dumps(GOOD))
    for dotted, new in changes.items():
        target = value
        *parents, last = dotted.split('.')
        for part in parents:
            target = target[part]
        target[last] = new
    return value


def test_exact_answer_passes_even_when_wrapped_in_prose_and_fence(root):
    wrapped = run(GOLDEN, GOOD, root, lambda s: f"Done. Here it is:\n```json\n{s}\n```\nHope this helps")
    assert wrapped['pass'] is True and wrapped['checks_exact'] == 3 and wrapped['anchors_covered'] == 1


@pytest.mark.parametrize('answer, failing', [
    (mutate(**{'answer.chain': ['m.py::b', 'm.py::a']}), 'chain'),
    (mutate(**{'answer.chain': ['m.py::a']}), 'chain'),
    (mutate(**{'answer.callers': ['m.py::a', 'm.py::unused']}), 'callers'),
    (mutate(**{'answer.found': False}), 'found'),
])
def test_wrong_answer_fails_only_the_wrong_check(root, answer, failing):
    result = run(GOLDEN, answer, root)
    assert result['pass'] is False
    assert [k for k, v in result['check_scores'].items() if v < 1.0] == [failing]


def test_partial_ordered_and_set_credit_is_graded_not_binary(root):
    result = run(GOLDEN, mutate(**{'answer.chain': ['m.py::a']}), root)
    assert 0 < result['check_scores']['chain'] < 1
    assert 0 < result['check_score'] < 1


@pytest.mark.parametrize('evidence', [
    [{'path': 'ghost.py', 'start': 1, 'end': 2}],
    [{'path': 'm.py', 'start': 5, 'end': 99}],
    [{'path': '../outside.py', 'start': 1, 'end': 1}],
    [{'path': 'm.py', 'start': 1, 'end': 500}],
    [{'path': 'm.py', 'start': 'x', 'end': 2}],
])
def test_fabricated_or_out_of_range_citation_fails_a_correct_answer(root, evidence):
    result = run({**GOLDEN, 'max_span': 20}, mutate(evidence=evidence + GOOD['evidence']), root)
    assert result['checks_exact'] == 3
    assert result['invalid_citations'] == 1 and result['pass'] is False


def test_real_lines_that_do_not_cover_the_required_anchor_fail(root):
    result = run(GOLDEN, mutate(evidence=[{'path': 'm.py', 'start': 1, 'end': 2}]), root)
    assert result['invalid_citations'] == 0 and result['anchors_covered'] == 0 and result['pass'] is False


def test_prose_without_json_is_a_false_completion_not_a_crash(root):
    result = run(GOLDEN, 'I have completed the analysis; everything is in order.', root)
    assert result['parsed'] is False and result['false_completion'] is True and result['pass'] is False
    assert run(GOLDEN, '', root)['false_completion'] is False


def test_dict_items_compare_by_selected_keys_case_insensitively(root):
    golden = {'task_id': 't', 'checks': [{'id': 'r', 'path': 'answer.routes', 'kind': 'set', 'item_keys': ['method', 'path'],
                                         'expected': [{'method': 'GET', 'path': '/x'}]}]}
    ok = {'answer': {'routes': [{'method': 'get', 'path': '/x', 'note': 'ignored'}]}}
    bad = {'answer': {'routes': [{'method': 'post', 'path': '/x'}]}}
    assert run(golden, ok, root)['pass'] is True
    assert run(golden, bad, root)['pass'] is False


def test_transcript_tool_calls_are_counted(tmp_path, root):
    transcript = tmp_path / 't.jsonl'
    rows = [{'type': 'item.completed', 'item': {'type': 'command_execution'}}, {'type': 'item.completed', 'item': {'type': 'agent_message'}},
            {'type': 'item.started', 'item': {'type': 'command_execution'}}]
    transcript.write_text('\n'.join(json.dumps(r) for r in rows))
    assert recon_oracle.score(GOLDEN, json.dumps(GOOD), root, transcript)['tool_calls'] == 1


def bench(tmp_path, arm_answer):
    base = tmp_path / 'case'
    (base / 'source').mkdir(parents=True)
    (base / 'source/m.py').write_text(SOURCE)
    (base / 'golden.json').write_text(json.dumps(GOLDEN))
    (base / 'prompt.txt').write_text('Trace the call chain and answer in JSON.')
    (base / 'good.txt').write_text(json.dumps(GOOD))
    (base / 'bad.txt').write_text(json.dumps(mutate(**{'answer.found': False})))
    (base / 'fabricated.txt').write_text(json.dumps(mutate(evidence=[{'path': 'ghost.py', 'start': 1, 'end': 1}])))
    (base / 'actor.py').write_text(
        "import json, sys\nsys.stdin.read()\n"
        f"print(json.dumps({{'type': 'bench.result', 'cost_usd': 0.0, 'usage': {{'input_tokens': 1}}, 'response': open(sys.argv[1]).read()}}))\n")
    config = {
        'version': 1, 'name': 'recon synthetic', 'source': {'directory': 'source', 'include': ['m.py']}, 'prompt': 'prompt.txt',
        'oracle': {'command': ['{python}', 'recon_oracle.py', 'golden.json', '{response}', '{transcript}'],
                   'files': {'recon_oracle.py': str(Path(recon_oracle.__file__)), 'golden.json': 'golden.json'}},
        'controls': {'expect_baseline_failure': True, 'reference_response': 'good.txt',
                     'negative_responses': {'wrong-answer': 'bad.txt', 'fabricated': 'fabricated.txt'}},
        'writable_paths': [], 'timeout_seconds': 10, 'grace_seconds': 1,
        'arms': [{'name': 'pass', 'runtime': 'fixture', 'command': ['{python}', '{config_dir}/actor.py', '{config_dir}/good.txt']},
                 {'name': 'fail', 'runtime': 'fixture', 'command': ['{python}', '{config_dir}/actor.py', '{config_dir}/bad.txt']}],
    }
    (base / 'bench.json').write_text(json.dumps(config))
    return base


def test_runner_proves_oracle_red_and_green_before_any_arm_and_scores_arms(tmp_path):
    base = bench(tmp_path, None)
    report = asyncio.run(runner.run(read(base / 'bench.json'), tmp_path / 'out'))
    controls = json.loads((tmp_path / 'out/controls.json').read_text())
    assert controls['baseline']['passed'] is False and controls['reference_response']['passed'] is True
    assert controls['negative:wrong-answer']['passed'] is False and controls['negative:fabricated']['passed'] is False
    assert [r['oracle_pass'] for r in report['results']] == [True, False]
    assert all(r['out_of_scope'] == [] for r in report['results'])


def test_a_negative_control_that_passes_the_oracle_stops_the_run_before_any_arm(tmp_path):
    base = bench(tmp_path, None)
    config = json.loads((base / 'bench.json').read_text())
    config['controls']['negative_responses'] = {'actually-good': 'good.txt'}
    (base / 'bench.json').write_text(json.dumps(config))
    with pytest.raises(ValueError, match='unexpectedly passes the oracle'):
        asyncio.run(runner.run(read(base / 'bench.json'), tmp_path / 'out'))
    assert not (tmp_path / 'out/arms').exists()


def test_a_reference_response_that_fails_the_oracle_stops_the_run(tmp_path):
    base = bench(tmp_path, None)
    config = json.loads((base / 'bench.json').read_text())
    config['controls']['reference_response'] = 'bad.txt'
    (base / 'bench.json').write_text(json.dumps(config))
    with pytest.raises(ValueError, match='reference response fails the oracle'):
        asyncio.run(runner.run(read(base / 'bench.json'), tmp_path / 'out'))
