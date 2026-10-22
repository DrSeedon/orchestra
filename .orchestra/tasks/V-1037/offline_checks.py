"""Offline checks of the real storage code; only db/prompting imports and git are faked.

Full pytest coverage lives in tests/test_temp_rules_v927.py and tests/test_mcp_stdio.py.
Run from the repository root. All scratch files stay beneath this task directory.
"""
import ast
import asyncio
import contextlib
import io
import sys
import tempfile
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path.cwd()
TASK = Path('.orchestra/tasks/V-1037')
SOURCE = Path('app/temp_rules.py').read_text()


def load(source):
    import app
    db = types.ModuleType('app.db')
    db._REPO_ROOT = str(ROOT)
    prompting = types.ModuleType('app.prompting')
    prompting.is_orchestrator_role = lambda role: role == 'orchestrator'
    module = types.ModuleType('app.temp_rules_offline')
    with patch.dict(sys.modules, {'app.db': db, 'app.prompting': prompting}), patch.object(app, 'db', db, create=True):
        exec(compile(source, 'app/temp_rules.py', 'exec'), module.__dict__)
    module._migrated = True
    return module


class StorageChecks(unittest.TestCase):
    source = SOURCE

    def setUp(self):
        self.m = load(self.source)
        self.tmp = tempfile.TemporaryDirectory(dir=TASK)
        self.addCleanup(self.tmp.cleanup)
        self.scopes = [str(Path(self.tmp.name) / name) for name in ('own', 'other', 'root')]
        for scope in self.scopes:
            layout = Path(scope) / '.orchestra/layout.json'
            layout.parent.mkdir(parents=True)
            layout.write_text('{}')
        self.own, self.other, self.root = [
            {'scope': scope, 'name': name, 'is_orchestrator': True}
            for scope, name in zip(self.scopes, ('orch', 'other', 'Orchestra-orchestrator'))]
        self.m.ORCHESTRA_SCOPE = self.scopes[2]
        self.m._git_blocker = lambda scope: ''
        self.m._is_repo = lambda scope: True
        self.calls = []
        self.fail_commit = False

        def git(scope, *args):
            self.calls.append((scope, args))
            return types.SimpleNamespace(returncode=int(self.fail_commit and args[0] == 'commit'), stdout='', stderr='failed' if self.fail_commit else '')

        self.m._git = git
        self.rule = self.m.add_rule(self.own, 'BEFORE', 'because', ['all'], 'review', self.date())

    def date(self, hours=1):
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()

    def update(self, **fields):
        return self.m.update_rule(self.own, self.rule['id'], **fields)

    def block(self, name='w1', scope=None):
        return self.m.with_block('BASE', role='worker', is_orch=False, scope=scope or self.own['scope'], name=name)

    def test_identity_prompt_and_storage(self):
        before = self.block()
        updated = self.update(text=' AFTER ')
        self.assertEqual(updated, {**self.rule, 'text': 'AFTER'})
        self.assertNotIn('BEFORE', self.block())
        self.assertIn('AFTER', self.block())
        self.assertNotEqual(self.m.block_fingerprint(before), self.m.block_fingerprint(self.block()))
        self.assertEqual([r['id'] for r in self.m.list_rules(self.own)], [self.rule['id']])
        self.assertIn('AFTER', self.m._path(self.own['scope']).read_text())

    def test_validation_no_write(self):
        invalid = [dict(reason=''), dict(reason='  '), dict(text=''), dict(text='<temporary-rules>'),
                   dict(text='</temporary-rules>'), dict(targets=[]), dict(targets=[' ']),
                   dict(mode='unknown'), dict(mode=''), dict(mode='permanent', expires_at=self.date()),
                   dict(keep=True, expires_at=self.date()), dict(keep=True, mode='review'),
                   dict(expires_at=self.date(-1)), dict(expires_at='bad'), dict(expires_at='2099-01-01T00:00:00'), {}]
        before = self.m._path(self.own['scope']).read_bytes()
        count = len(self.calls)
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(self.m.RuleError) as caught:
                self.update(**fields)
            self.assertEqual(caught.exception.status_code, 422)
            self.assertEqual(self.m._path(self.own['scope']).read_bytes(), before)
            self.assertEqual(len(self.calls), count)

    def test_targets_reason_modes_and_legacy(self):
        changed = self.update(reason=' revised ', targets=[' agent:w2 '])
        self.assertEqual(changed['targets'], ['agent:w2'])
        self.assertEqual(changed['reason'], 'revised')
        self.assertNotIn('BEFORE', self.block())
        self.assertIn('BEFORE', self.block(name='w2'))
        self.assertEqual(self.update(mode='expires')['expires_at'], self.rule['expires_at'])
        self.assertEqual(self.update(mode='review')['mode'], 'review')
        self.assertIsNone(self.update(mode='permanent')['expires_at'])
        for mode in ('expires', 'review'):
            with self.assertRaises(self.m.RuleError):
                self.update(mode=mode)
        with self.assertRaises(self.m.RuleError):
            self.update(expires_at=self.date())
        self.assertEqual(self.update(mode='review', expires_at=self.date())['mode'], 'review')
        self.assertEqual(self.update(expires_at=self.date(2))['mode'], 'review')
        self.assertIsNone(self.update(keep=True)['expires_at'])

    def test_overdue_review_edit_and_expired_revival(self):
        self.m._now = lambda: datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertIn('AFTER', self.update(text='AFTER')['text'])
        self.assertIn('AFTER', self.block())
        self.update(mode='expires', expires_at=self.date(3))
        self.m._now = lambda: datetime.now(timezone.utc) + timedelta(hours=4)
        self.update(text='EXPIRED')
        self.assertNotIn('EXPIRED', self.block())
        self.update(expires_at=self.date(5))
        self.assertIn('EXPIRED', self.block())

    def test_authority(self):
        for actor in (self.other, self.root, {**self.own, 'is_orchestrator': False}):
            with self.assertRaises(self.m.RuleError) as caught:
                self.m.update_rule(actor, self.rule['id'], text='BAD')
            self.assertIn(caught.exception.status_code, (403, 404))
        global_rule = self.m.add_rule(self.root, 'GLOBAL', 'because', ['all'], 'permanent', project='*')
        for actor in (self.own, self.other, {**self.root, 'name': 'impostor'}):
            with self.assertRaises(self.m.RuleError) as caught:
                self.m.update_rule(actor, global_rule['id'], text='BAD')
            self.assertEqual(caught.exception.status_code, 403)
        changed = self.m.update_rule(self.root, global_rule['id'], text='GLOBAL-AFTER')
        self.assertEqual(changed['id'], global_rule['id'])
        self.assertIn('GLOBAL-AFTER', self.block(scope=self.other['scope']))

    def test_commit_and_rollback(self):
        self.calls.clear()
        self.update(text='COMMITTED')
        commits = [args for _, args in self.calls if args[0] == 'commit']
        self.assertEqual(len(commits), 1)
        self.assertTrue(commits[0][2].startswith('V-1037:'))
        self.assertEqual(commits[0][3:], ('--only', '--', '.orchestra/temp-rules.yaml'))
        self.assertEqual(self.calls[0][1], ('add', '--', '.orchestra/temp-rules.yaml'))
        original = self.m._path(self.own['scope']).read_bytes()
        self.fail_commit = True
        with self.assertRaises(self.m.RuleError) as caught:
            self.update(text='FAILED')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.m._path(self.own['scope']).read_bytes(), original)
        self.assertEqual(self.calls[-1][1], ('reset', '-q', '--', '.orchestra/temp-rules.yaml'))

    def test_concurrent_partial_updates(self):
        errors = []
        def change(fields):
            try:
                self.update(**fields)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=change, args=(fields,)) for fields in ({'text': 'PARALLEL'}, {'reason': 'parallel reason'})]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        [stored] = self.m.list_rules(self.own)
        self.assertEqual((stored['text'], stored['reason']), ('PARALLEL', 'parallel reason'))


class WiringChecks(unittest.TestCase):
    def test_real_mcp_function_body_and_signature(self):
        tree = ast.parse(Path('app/mcp_stdio.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'temp_rule_update')
        node.decorator_list = []
        calls = []
        async def api(method, path, **kwargs):
            calls.append((method, path, kwargs['json']))
            return {'id': 'rule-stable', 'expires_at': None}
        namespace = {'_api': api}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app/mcp_stdio.py', 'exec'), namespace)
        edit = namespace['temp_rule_update']
        fields = dict(text='new', reason='why', targets=['workers'], mode='permanent')
        asyncio.run(edit('rule-stable', **fields))
        self.assertEqual(calls.pop(), ('PUT', '/api/temp-rules/rule-stable', {'expires_at': '', 'keep': False, **fields}))
        asyncio.run(edit('rule-stable', keep=True))
        self.assertEqual(calls.pop()[2], {'expires_at': '', 'keep': True})
        asyncio.run(edit('rule-stable', reason='', targets=[]))
        self.assertEqual(calls.pop()[2], {'expires_at': '', 'keep': False, 'reason': '', 'targets': []})

    def test_http_handler_forwards_all_model_fields(self):
        tree = ast.parse(Path('app/routes/temp_rules.py').read_text())
        model = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RuleUpdate')
        self.assertEqual({n.target.id for n in model.body if isinstance(n, ast.AnnAssign)},
                         {'expires_at', 'keep', 'text', 'reason', 'targets', 'mode'})
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'update_rule')
        node.decorator_list = []
        calls = []
        fields = dict(text='new', reason='why', targets=['workers'], mode='review', expires_at='date', keep=False)
        namespace = {'RuleUpdate': object, 'Request': object, '_actor': lambda request: 'actor',
                     '_run': lambda call: call(), 'temp_rules': types.SimpleNamespace(update_rule=lambda *args, **kwargs: calls.append((args, kwargs)))}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'app/routes/temp_rules.py', 'exec'), namespace)
        namespace['update_rule']('rule-stable', types.SimpleNamespace(model_dump=lambda: fields), object())
        self.assertEqual(calls, [(('actor', 'rule-stable'), fields)])


def run(source=SOURCE, wiring=False):
    StorageChecks.source = source
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(StorageChecks)
    if wiring:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(WiringChecks))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return result, stream.getvalue()


if __name__ == '__main__':
    print('Imported app:', __import__('app').__file__)
    result, output = run(wiring=True)
    print(output)
    if not result.wasSuccessful():
        raise SystemExit(1)
    mutations = {
        'identity_changed': ('e.update(updated)', 'e.update(updated)\n                e["id"] = "rule-replaced"'),
        'empty_reason_allowed': ('if not reason:\n', 'if False:\n'),
        'global_authority_removed': ('if entry_project == GLOBAL:\n', 'if True:\n        return\n    if entry_project == GLOBAL:\n'),
        'date_requirement_removed': ('if not expires_at:\n', 'if not expires_at:\n            return None\n        if not expires_at:\n'),
        'permanent_date_allowed': ('if expires_at:\n            raise RuleError', 'if False:\n            raise RuleError'),
        'targets_ignored': ('"targets": _check_targets(e["targets"] if targets is None else targets)', '"targets": e["targets"]'),
        'persistence_skipped': ('_write_and_commit(scope, entries, message_of(touched))', 'pass'),
        'commit_path_broadened': ('"--only", "--", str(RULES_FILE)', '"--only", "--", "."'),
    }
    killed = []
    for name, (old, new) in mutations.items():
        assert SOURCE.count(old) == 1, (name, SOURCE.count(old))
        with contextlib.redirect_stderr(io.StringIO()):
            mutated, _ = run(SOURCE.replace(old, new))
        if mutated.wasSuccessful():
            raise AssertionError('SURVIVED: ' + name)
        killed.append(name)
        print('KILLED', name, f'({len(mutated.failures)} assertion failures, {len(mutated.errors)} errors)')
    print(f'{len(killed)}/{len(mutations)} mutations killed')
