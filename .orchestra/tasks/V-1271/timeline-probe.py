"""Run unchanged frozen test bodies offline with baseline/final source injection.

Only dashboard startup is replaced by the existing offline chat harness.
No backend, live service, private artifact, network or provider is used.
"""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace

from playwright.sync_api import Browser, Page, expect, sync_playwright

ROOT = Path.cwd()
NOTES = ROOT / '.orchestra/tasks/V-1271'
FRONTEND = ROOT / 'tests/test_frontend.py'
FINAL = (ROOT / 'app/static/js/app.js').read_text()
CHAT = (ROOT / 'app/static/js/chat.js').read_text()
TESTS = [
    'test_chat_timeline_navigates_events_and_cycles_user_messages',
    'test_chat_timeline_marker_height_tracks_message_height',
    'test_chat_timeline_navigates_final_agent_answers_only',
]


def baseline():
    patch = (NOTES / 'implementation.diff').read_text()
    section = patch.split('--- a/app/static/js/app.js\n+++ b/app/static/js/app.js\n', 1)[1].split('--- a/', 1)[0]
    lines = FINAL.splitlines(keepends=True)
    original = []
    cursor = 0
    for hunk in re.split(r'(?=^@@ )', section, flags=re.M):
        if not hunk.startswith('@@ '):
            continue
        header, body = hunk.split('\n', 1)
        pos = int(re.search(r'\+(\d+)', header).group(1)) - 1
        original.extend(lines[cursor:pos])
        cursor = pos
        for line in body.splitlines(keepends=True):
            if line.startswith(' '):
                assert lines[cursor] == line[1:]
                original.append(line[1:])
                cursor += 1
            elif line.startswith('+'):
                assert lines[cursor] == line[1:]
                cursor += 1
            elif line.startswith('-'):
                original.append(line[1:])
    original.extend(lines[cursor:])
    return ''.join(original)


def identity(source):
    data = source.encode()
    return {'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()}


def sanitized(text):
    return text.replace(str(ROOT), '<WORKSPACE>').replace(str(Path.home() / '.cache/ms-playwright'), '<BROWSER_CACHE>').replace(str(Path.home()), '<HUB_HOME>')


spec = importlib.util.spec_from_file_location('answers_tests', ROOT / 'tests/test_chat_answers_v1271.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
tree = ast.parse(FRONTEND.read_text())
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in TESTS + ['_route_frontend_sources']]
assert len(functions) == 4
original = baseline()
assert identity(original)['git_blob'] == '82c065aaada5f9758cf829987bc888b327c7ae8e'
results = {'baseline_app': identity(original), 'final_app': identity(FINAL),
           'chat': identity(CHAT), 'cases': []}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=os.environ.get('CHAT_ANSWERS_CHROME') or None)
    try:
        variants = [('baseline', original, CHAT, TESTS[-1:]), ('final', FINAL, CHAT, TESTS)]
        # Controlled diagnostic: remove only finalization publication hooks in memory.
        # This does NOT claim that root served such a source; it tests the mechanism.
        hooks = "    streamBubble.dataset.chatTimelineType = 'text';\n    if (typeof _recomputeChatTimelineFinals === 'function') _recomputeChatTimelineFinals();\n    if (typeof _syncChatTimelineControls === 'function') _syncChatTimelineControls();\n"
        assert CHAT.count(hooks) == 1
        stale = CHAT.replace(hooks, '', 1)
        variants += [('baseline_without_finalize_hooks', original, stale, TESTS[-1:]),
                     ('final_without_finalize_hooks', FINAL, stale, TESTS[-1:])]
        for variant, app_source, chat_source, names in variants:
            for name in names:
                pages = []

                def new_page(**kwargs):
                    page = browser.new_page(**kwargs)
                    pages.append(page)
                    return page

                def boot(page):
                    inject = page.add_script_tag

                    def load(**kwargs):
                        file = kwargs.get('path')
                        if file == str(ROOT / 'app/static/js/app.js'):
                            kwargs = {'content': app_source}
                        elif file == str(ROOT / 'app/static/js/chat.js'):
                            kwargs = {'content': chat_source}
                        return inject(**kwargs)

                    page.add_script_tag = load
                    try:
                        harness._boot(page)
                    finally:
                        page.add_script_tag = inject
                    page.evaluate('''() => {
                        selectedAgent = null; currentScope = null;
                        _chatFollow = true; scrollAfterLoad = true;
                        _chatSnapshotReady = false;
                    }''')

                scope = {'__file__': str(FRONTEND), 'Path': Path, 'Browser': Browser, 'Page': Page,
                         're': re, 'expect': expect, '_goto_dashboard': boot}
                exec(compile(ast.Module(body=functions, type_ignores=[]), 'tests/test_frontend.py', 'exec'), scope)
                case = {'variant': variant, 'test': name}
                try:
                    args = [SimpleNamespace(new_page=new_page)]
                    if name == TESTS[-1]:
                        args.append(SimpleNamespace(addfinalizer=lambda callback: None))
                    scope[name](*args)
                    case['result'] = 'PASS'
                except Exception as error:
                    case['result'] = 'FAIL'
                    case['error_type'] = type(error).__name__
                    case['error'] = sanitized(str(error))
                    if pages:
                        case['state'] = pages[-1].evaluate('''() => {
                            const node = document.querySelector('[data-test-label="streaming"]');
                            return {type:node?.dataset.chatTimelineType,
                                kind:node?.dataset.chatNavKind,
                                textLength:node ? _chatTimelineText(node).length : null,
                                bubble:!!streamBubble, deferred:!!_streamDeferredFinal,
                                finalMarkers:document.querySelectorAll('#chat-timeline-track .is-final').length};
                        }''')
                finally:
                    for page in pages:
                        page.close()
                results['cases'].append(case)
                print(json.dumps(case, ensure_ascii=False), flush=True)
    finally:
        browser.close()
(NOTES / 'timeline-comparison.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
