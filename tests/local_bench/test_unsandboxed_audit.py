import json

from scripts.local_bench.runner import audit_transcript


def transcript(tmp_path, commands):
    path = tmp_path / 'stdout.jsonl'
    path.write_text('\n'.join(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': c}}) for c in commands))
    return path


def test_audit_accepts_work_copy_and_system_paths(tmp_path):
    work = '/tmp/local-bench-x/work'
    path = transcript(tmp_path, ["rg -n '@router.post(\"/api/sessions/{name}/send\")' app", f"bash -lc 'rg -n def {work}/app'", "bash -lc 'cat app/x.py | /usr/bin/head'", 'sed -n 1,40p app/y.py'])
    assert audit_transcript(path, work) == {'commands': 4, 'violations': []}


def test_audit_flags_reads_outside_the_copy(tmp_path):
    work = '/tmp/local-bench-x/work'
    commands = ['cat /home/kesha/orchestra/data/orchestra.db', 'ls ..', 'cat ~/.ssh/id_rsa', 'cat /tmp/local-bench-y/work/a', 'python3 -c "open(\'/etc/passwd\')"']
    audit = audit_transcript(transcript(tmp_path, commands), work)
    assert len(audit['violations']) == 5
