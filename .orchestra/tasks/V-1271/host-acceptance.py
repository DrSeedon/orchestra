"""V-1271 host diagnostic; product and frozen tests are read-only.

RC 0: both normal cases PASS, HTTP/runtime provenance verified, canary fails
at the original stream-final wait. RC 1: verified normal test failure.
RC 2: setup, provenance, canary, capture or isolation failure. Never skips.
--startup-only does not execute acceptance. The opt-in chat-only profile excludes
application startup services; its result must not be called full-lifecycle green.
"""
import argparse
import ast
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import importlib.util
import ipaddress
import json
import logging
import os
from pathlib import Path
import re
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
NOTES = ROOT / '.orchestra/tasks/V-1271'
FROZEN = 'test_chat_timeline_navigates_final_agent_answers_only'
BODY_SHA = '25806023526988271f17539d0ca98ebb885ce082c7b35c12920d684b65c0a1ff'
BASE_BLOB = '82c065aaada5f9758cf829987bc888b327c7ae8e'
FINAL_SHA = 'f3d468b28188f934fcd3edb6171455620031f5ae74322ba8b28076c43bb1cfa3'
CHAT_SHA = '6fed637f43c20cc3b0ed2679536cac6f580d34d9bf1320af6b8672c40af739f3'
PRODUCT = ['app/static/js/app.js', 'app/static/js/chat.js', 'app/static/js/i18n.js',
           'app/static/css/style.css', 'CHANGELOG.md', 'tests/test_chat_answers_v1271.py',
           'tests/test_frontend.py']
STATIC_REQUEST = ContextVar('v1271_static_request', default=None)
JSON_WRITE_LOCK = threading.RLock()


class InvalidDiagnostic(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(path):
    try:
        path = Path(path)
        return str((path if path.is_absolute() else ROOT / path).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        name = Path(path).name
        return '<external>/' + name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,80}\.py', name) else '<external>'


def denial_frames():
    # Do not use extract_stack/linecache: that would read source inside an audit hook.
    result = []
    frame = sys._getframe(1)
    for _ in range(20):
        if frame is None:
            break
        result.append({'file': relative(frame.f_code.co_filename), 'line': frame.f_lineno,
                       'function': frame.f_code.co_name})
        frame = frame.f_back
    return result


def safe_formatted_trace(text):
    if not isinstance(text, str):
        return None
    frames = [{'file': relative(path), 'line': int(line), 'function': function}
              for path, line, function in re.findall(r'File "([^"\n]+)", line (\d+), in ([A-Za-z0-9_<>.]+)', text)][:20]
    types = re.findall(r'^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Exit))(?::|$)', text, re.M)
    if not frames:
        return None
    return {'type': types[-1] if types else 'FormattedTraceback', 'frames': frames,
            'channel': 'formatted_traceback', 'message_omitted': True}


class ObserveLifespan:
    def __init__(self, app, diagnostics, phase, persist=None):
        self.app, self.diagnostics, self.phase = app, diagnostics, phase
        self.persist = persist or (lambda: None)

    def http_diagnostic(self, item):
        if len(self.diagnostics) < 40:
            self.diagnostics.append(item)
        elif item['path'] == '/static/js/chat.js':
            self.diagnostics[-1] = item
        self.persist()

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            path = scope.get('path', '')
            static = '/static/js/chat.js' if path == '/static/js/chat.js' else '/static/<other>' if path.startswith('/static/') else None
            token = STATIC_REQUEST.set(static)
            status = None
            async def observed_http_send(message):
                nonlocal status
                if message['type'] == 'http.response.start':
                    status = message['status']
                await send(message)
            error_seen = False
            try:
                return await self.app(scope, receive, observed_http_send)
            except BaseException as error:
                error_seen = True
                if static:
                    self.http_diagnostic({'channel': 'http_static_exception', 'path': static,
                                          'status': status, 'error': exception_info(error)})
                raise
            finally:
                if static and status is not None and status >= 500 and not error_seen:
                    self.http_diagnostic({'channel': 'http_static_500_without_exception', 'path': static, 'status': status})
                STATIC_REQUEST.reset(token)
        if scope['type'] != 'lifespan':
            return await self.app(scope, receive, send)
        self.phase['name'] = 'lifespan'
        async def observed_send(message):
            if message.get('type') in {'lifespan.startup.failed', 'lifespan.shutdown.failed'}:
                parsed = safe_formatted_trace(message.get('message'))
                if len(self.diagnostics) < 20:
                    self.diagnostics.append(parsed or {'type': 'LifespanFailure', 'channel': message['type'],
                                                       'message_omitted': True})
                    self.persist()
            await send(message)
        try:
            return await self.app(scope, receive, observed_send)
        except BaseException as error:
            if len(self.diagnostics) < 20:
                self.diagnostics.append(exception_info(error))
                self.persist()
            raise
        finally:
            self.persist()


@asynccontextmanager
async def synthetic_chat_lifespan(app):
    # DB is already initialized by the canonical seed. No actors/cron/bridge/migration.
    yield


def configure_fixture_app(application, profile):
    if profile == 'full':
        return []
    if profile != 'chat-only':
        raise InvalidDiagnostic('invalid_startup_profile')
    application.router.lifespan_context = synthetic_chat_lifespan
    return ['synthetic_cwd', 'synthetic_seed_db_only_lifespan']


def source_asset(name):
    static = (ROOT / 'app/static').resolve()
    path = (static / name).resolve()
    if static not in path.parents or path.suffix not in {'.js', '.css', '.svg', '.png', '.ico', '.woff', '.woff2'} or not path.is_file():
        return None
    return path.read_bytes()


def source_application():
    """Small HTTP source fixture: real template/assets, no app imports or API."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, Response
    from starlette.routing import Route
    env = Environment(loader=FileSystemLoader(ROOT / 'app/templates'), autoescape=select_autoescape())
    html = env.get_template('dashboard.html').render(is_auth_enabled=False, is_owner_mode=False,
                                                    hide_thinking=False, client_name='', currency_symbol='$')
    scripts = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"[^>]*>\s*</script>', html)
    if not scripts or any(not src.startswith('/static/') for src in scripts):
        raise InvalidDiagnostic('unexpected_source_fixture_script')
    html = re.sub(r'<script\b[^>]*>.*?</script>', '', html, flags=re.S)
    # Match the prior offline source harness, but load real bytes over HTTP.
    # App-wide DOMContentLoaded polling/services are intentionally not started.
    boot = '''<script>
document.addEventListener('DOMContentLoaded', async () => {
    try {
        for (const src of SCRIPT_LIST) {
            await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = src; script.onload = resolve; script.onerror = () => reject(new Error('source fixture asset failed'));
                document.head.appendChild(script);
            });
        }
        initChatTimeline();
        window.__V1271_SOURCE_READY = true;
    } catch (error) { window.__V1271_SOURCE_ERROR = error.name; throw error; }
}, {once: true});
</script>'''.replace('SCRIPT_LIST', json.dumps(scripts))
    html = html.replace('</body>', boot + '</body>')
    async def dashboard(request):
        return HTMLResponse(html, headers={'cache-control': 'no-store'})
    async def static(request):
        name = request.path_params['name']
        data = source_asset(name)
        if data is None:
            return Response(status_code=404)
        suffix = Path(name).suffix
        media = {'.js': 'application/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
                 '.png': 'image/png', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2'}[suffix]
        return Response(data, media_type=media, headers={'cache-control': 'no-store'})
    return Starlette(routes=[Route('/', dashboard), Route('/static/{name:path}', static)])


def exception_info(error, depth=0):
    # Never serialize exception messages, locals, DOM prose or response bodies.
    result = {'type': type(error).__name__, 'frames': [
        {'file': relative(frame.f_code.co_filename), 'line': line, 'function': frame.f_code.co_name}
        for frame, line in list(traceback.walk_tb(error.__traceback__))[-20:]
    ]}
    if depth < 2:
        nested = list(error.exceptions)[:3] if isinstance(error, BaseExceptionGroup) else [error.__cause__ or error.__context__]
        result['causes'] = [exception_info(item, depth + 1) for item in nested if item is not None and item is not error]
    if isinstance(error, ModuleNotFoundError) and re.fullmatch(r'[A-Za-z0-9_.]+', error.name or ''):
        result['missing_module'] = error.name
    for pattern, category in [('Executable doesn\'t exist', 'browser_executable_missing'),
                              ('Socket path too long', 'browser_tmp_socket_path_too_long')]:
        if pattern in str(error):
            result['category'] = category
    return result


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def write_json_atomic(path, data):
    with JSON_WRITE_LOCK:
        temporary = path.with_name('.' + path.name + '.tmp')
        write_json(temporary, data)
        temporary.replace(path)


def publish_startup(sandbox, ready_fd, data):
    write_json(sandbox / 'server-startup.json', data)
    # Do not send detailed traces through the readiness pipe (which can fill).
    notice = {'event': data['event'], 'detail': 'server-startup.json'}
    os.write(ready_fd, json.dumps(notice).encode() + b'\n')


def initialize_fixture_mimetypes():
    """Process-local builtins only: init(files=[]) alone still reads knownfiles."""
    import mimetypes
    mimetypes.knownfiles = []
    mimetypes.MimeTypes.read_windows_registry = lambda *args, **kwargs: None
    mimetypes._db = None
    mimetypes.init(files=[])
    if not mimetypes.inited or mimetypes._db is None:
        raise InvalidDiagnostic('fixture_mimetypes_not_initialized')
    return {'source': 'python-stdlib-builtins-only', 'knownfiles_count': len(mimetypes.knownfiles),
            'registry_reader_disabled': True,
            'javascript': mimetypes.guess_type('chat.js')[0],
            'css': mimetypes.guess_type('style.css')[0],
            'svg': mimetypes.guess_type('icon.svg')[0]}


def fingerprints():
    return {name: sha((ROOT / name).read_bytes()) for name in PRODUCT}


def sources():
    final = (ROOT / PRODUCT[0]).read_bytes()
    chat = (ROOT / PRODUCT[1]).read_bytes()
    source = (ROOT / 'tests/test_frontend.py').read_text()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == FROZEN)
    if sha(final) != FINAL_SHA or sha(chat) != CHAT_SHA:
        raise InvalidDiagnostic('source_pin_mismatch')
    if sha(ast.get_source_segment(source, function).encode()) != BODY_SHA:
        raise InvalidDiagnostic('frozen_body_changed')
    waits = [n for n in ast.walk(function) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == 'wait_for_function'
             and n.args and isinstance(n.args[0], ast.Constant)
             and 'streaming' in str(n.args[0].value)]
    if len(waits) != 1:
        raise InvalidDiagnostic('ambiguous_frozen_wait')
    # Reconstruct precisely the pre-feature app.js without Git or checkout writes.
    patch = (NOTES / 'implementation.diff').read_text()
    section = patch.split('--- a/app/static/js/app.js\n+++ b/app/static/js/app.js\n', 1)[1].split('--- a/', 1)[0]
    lines = final.decode().splitlines(keepends=True)
    baseline = []
    cursor = 0
    for hunk in re.split(r'(?=^@@ )', section, flags=re.M):
        if not hunk.startswith('@@ '):
            continue
        header, body = hunk.split('\n', 1)
        pos = int(re.search(r'\+(\d+)', header).group(1)) - 1
        baseline.extend(lines[cursor:pos])
        cursor = pos
        for line in body.splitlines(keepends=True):
            if line.startswith((' ', '+')):
                if lines[cursor] != line[1:]:
                    raise InvalidDiagnostic('reverse_patch_mismatch')
                cursor += 1
            if line.startswith((' ', '-')):
                baseline.append(line[1:])
    baseline.extend(lines[cursor:])
    baseline = ''.join(baseline).encode()
    blob = hashlib.sha1(f'blob {len(baseline)}\0'.encode() + baseline).hexdigest()
    if blob != BASE_BLOB:
        raise InvalidDiagnostic('baseline_blob_mismatch')
    start = chat.index(b'function _finalizeStreamBubble(')
    end = chat.index(b'\n}', start) + 2
    return baseline, final, {'baseline_blob': blob, 'baseline_sha256': sha(baseline),
                            'final_sha256': sha(final), 'chat_disk_sha256': sha(chat),
                            'runtime_finalizer_sha256': sha(chat[start:end]),
                            'frozen_body_sha256': BODY_SHA, 'frozen_wait_line': waits[0].lineno}


def install_server_policy(sandbox, port, denied, details=None, phase=None, persist=None):
    """Python-side boundary before importing any application module."""
    sandbox = sandbox.resolve()
    protected = [(ROOT / name).resolve() for name in ['data', '.orchestra/private', '.orchestra/workers', '.git']]
    read_roots = [ROOT.resolve(), sandbox, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                  Path('/proc'), Path('/sys')]
    runtime_files = {Path(p).resolve() for p in ['/dev/urandom', '/dev/null', '/etc/localtime',
                                               '/etc/hosts', '/etc/resolv.conf', '/etc/nsswitch.conf']}
    details = details if details is not None else []
    phase = phase if phase is not None else {'name': 'policy-check'}

    def target_shape(value):
        if isinstance(value, int) or value is None:
            return {'scope': 'descriptor'}
        path = Path(os.fsdecode(value)).resolve()
        if path.name == '.env' or path.name.startswith('.env.'):
            return {'scope': 'protected-dotenv'}
        if any(path == p or p in path.parents for p in protected):
            return {'scope': 'protected-source-state'}
        base = sandbox if path == sandbox or sandbox in path.parents else ROOT
        if path != base and base not in path.parents:
            return {'scope': 'external'}
        known = {'data', 'logs', 'cache', '.cache', '.orchestra', '.git', 'worktrees', 'state',
                 'home', 'tmp', 'tasks', 'app', 'static', 'templates', 'projects.yaml', 'orchestra.db'}
        return {'scope': 'sandbox' if base == sandbox else 'workspace',
                'shape': '/'.join(p if p in known else '<component>' for p in path.relative_to(base).parts)}

    def block(reason, event, target=None, process=None):
        denied[reason] = denied.get(reason, 0) + 1
        request = STATIC_REQUEST.get()
        if len(details) < 40 or request == '/static/js/chat.js':
            record = {'reason': reason, 'event': event, 'phase': phase['name'], 'frames': denial_frames()}
            if request:
                record['http_static_path'] = request
            if target is not None:
                record['target'] = target_shape(target)
            if process is not None:
                known = {'git', 'python', 'python3', 'python3.12', 'node', 'sh', 'bash', 'claude', 'codex', 'systemctl'}
                program = Path(os.fsdecode(process[0])).name if isinstance(process[0], (str, bytes)) else ''
                record['process'] = {'program': program if program in known else '<other>'}
                argv = process[1] if len(process) > 1 else None
                if isinstance(argv, (list, tuple)):
                    verbs = {'rev-parse', 'status', 'show', 'log', 'worktree', 'config', 'diff', 'ls-files', '--version'}
                    record['process']['verb'] = argv[1] if len(argv) > 1 and argv[1] in verbs else '<redacted>'
                    record['process']['argc'] = len(argv)
            if len(details) < 40:
                details.append(record)
            else:
                details[-1] = record
        if persist is not None:
            persist()
        raise PermissionError(reason)

    def path_of(value):
        if isinstance(value, int) or value is None:
            return None
        return Path(os.fsdecode(value)).resolve()

    def read(value, event):
        if not isinstance(value, int) and value is not None:
            lexical = Path(os.fsdecode(value))
            if lexical.name == '.env' or lexical.name.startswith('.env.'):
                block('dotenv_read_denied', event, value)
        path = path_of(value)
        if path is None:
            return
        if path.name == '.env' or path.name.startswith('.env.'):
            block('dotenv_read_denied', event, value)
        if any(path == p or p in path.parents for p in protected):
            block('private_data_read_denied', event, value)
        if Path('/proc') in path.parents and path.name in {'environ', 'cmdline', 'mem'}:
            block('process_environment_read_denied', event)
        if path not in runtime_files and not any(path == p or p in path.parents for p in read_roots):
            block('read_outside_fixture_roots_denied', event, value)

    def write(value, event):
        path = path_of(value)
        if path is not None and path != sandbox and sandbox not in path.parents:
            block('write_outside_sandbox_denied', event, value)

    def address(value, event):
        if not isinstance(value, tuple) or len(value) < 2:
            block('non_fixture_socket_denied', event)
        try:
            loopback = ipaddress.ip_address(value[0]).is_loopback
        except ValueError:
            loopback = False
        if not loopback or value[1] != port:
            block('non_fixture_socket_denied', event)

    def audit(event, args):
        if event == 'open':
            path, mode, flags = args
            read(path, event)
            if (mode and any(c in mode for c in 'wax+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                write(path, event)
        elif event in {'os.listdir', 'os.scandir'}:
            read(args[0], event)
        elif event == 'sqlite3.connect':
            db = os.fsdecode(args[0])
            if db != ':memory:':
                if db.startswith('file:'):
                    block('sqlite_uri_denied', event)
                write(db, event)
        elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.chmod', 'os.utime'}:
            write(args[0], event)
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            write(args[0], event); write(args[1], event)
        elif event in {'subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.fork'}:
            block('native_process_denied', event, process=args if event == 'subprocess.Popen' else None)
        elif event in {'socket.connect', 'socket.bind'}:
            address(args[1], event)
        elif event == 'socket.getaddrinfo':
            address((args[0], args[1]), event)
    sys.addaudithook(audit)


def serve(sandbox, socket_fd, ready_fd):
    sandbox = sandbox.resolve()
    if NOTES not in sandbox.parents or not sandbox.parent.name.startswith('host-run-'):
        return 2
    denied = {}
    details = []
    diagnostics = []
    phase = {'name': 'bootstrap'}
    fixture_mime = {}
    profile = os.environ.get('V1271_STARTUP_PROFILE', 'full')
    def persist():
        write_json_atomic(sandbox / 'server-policy.json', {'capture_enabled': True,
            'denied': dict(denied), 'denial_details': list(details),
            'diagnostics': list(diagnostics), 'phase': phase['name'], 'fixture_mime': dict(fixture_mime)})
    sent = False
    def signal(data):
        nonlocal sent
        data.update(denied=dict(denied), denial_details=list(details), diagnostics=list(diagnostics),
                    startup_profile=profile, phase=phase['name'], fixture_mime=dict(fixture_mime))
        # Keep readiness IPC below PIPE_BUF; detailed metadata belongs in a file.
        if not sent:
            publish_startup(sandbox, ready_fd, data)
            sent = True
        else:
            write_json(sandbox / 'server-startup.json', data)
    try:
        if profile not in {'full', 'chat-only', 'source-only'}:
            raise InvalidDiagnostic('invalid_startup_profile')
        port = int(os.environ['V1271_PORT'])
        install_server_policy(sandbox, port, denied, details, phase, persist)
        persist()
        phase['name'] = 'fixture-mime'
        fixture_mime.update(initialize_fixture_mimetypes())
        persist()
        import dotenv
        dotenv.load_dotenv = lambda *args, **kwargs: False
        dotenv.dotenv_values = lambda *args, **kwargs: {}
        sys.path.insert(0, str(ROOT))
        if profile != 'source-only':
            phase['name'] = 'seed'
            # Same canonical seed body; do not import pytest into the server process.
            source = (ROOT / 'tests/test_frontend.py').read_text()
            seed = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_seed_dashboard_db')
            scope = {'Path': Path, 'datetime': datetime, 'timezone': timezone}
            exec(compile(ast.Module(body=[seed], type_ignores=[]), 'tests/test_frontend.py', 'exec'), scope)
            scope['_seed_dashboard_db'](sandbox / 'orchestra.db')
        import uvicorn
        class SafeLog(logging.Handler):
            def emit(self, record):
                if record.exc_info and record.exc_info[1] and len(diagnostics) < 20:
                    diagnostics.append(exception_info(record.exc_info[1]))
                    persist()
                elif len(diagnostics) < 20:
                    values = [record.msg] + (list(record.args) if isinstance(record.args, tuple) else [])
                    for value in values:
                        parsed = safe_formatted_trace(value)
                        if parsed is not None:
                            diagnostics.append(parsed)
                            persist()
                            break
        logging.getLogger('uvicorn.error').addHandler(SafeLog())
        logging.getLogger().addHandler(SafeLog())
        injections = ['stdlib_mimetypes_builtins_only']
        def application_factory():
            # Preserve Uvicorn's app-import timing inside its running event loop.
            phase['name'] = 'app-import'
            if profile == 'source-only':
                application = source_application()
                additions = ['no_app_import', 'real_template_raw_checkout_assets', 'chat_init_after_dom_ready', 'no_api']
            else:
                application = importlib.import_module('app.main').app
                additions = configure_fixture_app(application, profile)
            injections[:] = ['stdlib_mimetypes_builtins_only'] + additions
            return ObserveLifespan(application, diagnostics, phase, persist)
        class FixtureServer(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                phase['name'] = 'serving' if self.started else 'startup_failed'
                signal({'event': 'ready' if self.started else 'startup_failed', 'injections': injections})
        phase['name'] = 'uvicorn-config'
        server = FixtureServer(uvicorn.Config(application_factory, factory=True, host='127.0.0.1', port=port,
                                             log_level='warning', access_log=False, log_config=None))
        server.run(sockets=[socket.socket(fileno=socket_fd)])
    except BaseException as error:
        signal({'event': 'setup_error', 'error': exception_info(error), 'denied': denied})
        return 2
    finally:
        persist()
        os.close(ready_fd)
    return 0


def start_server(sandbox, profile='full'):
    # A new DB, catalog, HOME and empty environment for EVERY comparison case.
    for name in ['home', 'state', 'cache', 'tmp', 'scopes', 'tasks']:
        (sandbox / name).mkdir()
    (sandbox / 'projects.yaml').write_text('version: 1\nprojects: []\n')
    if profile in {'chat-only', 'source-only'}:
        # Relative runtime writes go to the sandbox; resolved writes through this
        # source symlink are STILL rejected by the unchanged write policy.
        (sandbox / 'app').symlink_to(ROOT / 'app', target_is_directory=True)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    read_fd, write_fd = os.pipe()
    env = {'PATH': os.defpath, 'HOME': str(sandbox / 'home'), 'LANG': 'C.UTF-8',
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT),
           'PYTHON_DOTENV_DISABLED': '1', 'TMPDIR': str(sandbox / 'tmp'),
           'STATE_DIRECTORY': str(sandbox / 'state'), 'XDG_STATE_HOME': str(sandbox / 'state'),
           'XDG_CACHE_HOME': str(sandbox / 'cache'),
           'ORCHESTRA_DB_PATH': str(sandbox / 'orchestra.db'),
           'ORCHESTRA_TASK_REPOSITORY': str(sandbox / 'tasks'),
           'ORCHESTRA_PROJECT_CATALOG': str(sandbox / 'projects.yaml'),
           'ORCHESTRA_PROJECT_CATALOG_ROOT': str(sandbox / 'scopes'),
           'DASHBOARD_USER': '', 'DASHBOARD_PASSWORD': '', 'OWNER_MODE': '', 'SSH_TUNNELS': '',
           'AGENTIC_COMPACT_ENABLED': '0', 'V1271_PORT': str(port),
           'V1271_STARTUP_PROFILE': profile}
    proc = None
    try:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve',
                                 str(sandbox), str(listener.fileno()), str(write_fd)],
                                cwd=sandbox if profile in {'chat-only', 'source-only'} else ROOT, env=env,
                                pass_fds=(listener.fileno(), write_fd),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(write_fd); write_fd = None
        listener.close()
        if not select.select([read_fd], [], [], 60)[0]:
            raise InvalidDiagnostic('fixture_startup_timeout_60s')
        notice = json.loads(os.read(read_fd, 4096))
        if notice.get('detail') != 'server-startup.json':
            raise InvalidDiagnostic('invalid_fixture_readiness_notice')
        packet = json.loads((sandbox / 'server-startup.json').read_text())
        if packet.get('event') != notice.get('event') or packet.get('startup_profile') != profile:
            raise InvalidDiagnostic('fixture_readiness_provenance_mismatch')
        if packet.get('event') != 'ready':
            stop_server(proc)
            return None, None, packet
        return proc, f'http://127.0.0.1:{port}', packet
    except BaseException:
        if proc is not None:
            stop_server(proc)
        raise
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        listener.close()


def stop_server(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait(timeout=3)


STATE = '''() => {
    const node = document.querySelector('[data-test-label="streaming"]');
    const selection = getSelection();
    return {
        node: node ? {type:node.dataset.chatTimelineType, kind:node.dataset.chatNavKind,
            answer:node.dataset.chatAnswer || null, service:!!node.dataset.chatTimelineService,
            connected:node.isConnected, textLength:_chatTimelineText(node).length} : null,
        streamBubble:!!streamBubble, streamConnected:!!streamBubble?.isConnected,
        streamContentLength:streamContent.length, streamPendingLength:streamPending.length,
        deferred:!!_streamDeferredFinal, selectionCollapsed:selection?.isCollapsed,
        selectionRanges:selection?.rangeCount, selectionTouchesStream:_selectionTouchesStream(),
        finalMarkers:document.querySelectorAll('#chat-timeline-track .is-final').length,
        generation:_chatLoadGeneration, loading:_chatLoading, snapshotReady:_chatSnapshotReady,
        agentSelected:!!selectedAgent, scopeSelected:!!currentScope,
        guardCalls:window.__v1271GuardCalls || 0
    };
}'''
GUARD = '''() => {
    window.__v1271GuardCalls = 0;
    const original = _finalizeStreamBubble;
    _finalizeStreamBubble = function(...args) {
        window.__v1271GuardCalls++;
        const recompute = _recomputeChatTimelineFinals;
        _recomputeChatTimelineFinals = () => {};
        try { return original(...args); }
        finally { _recomputeChatTimelineFinals = recompute; }
    };
}'''


def run_case(browser, sandbox, name, app_source, meta):
    record = {'variant': name, 'result': 'ERROR', 'executions': 0, 'responses': [],
              'capture_errors': [], 'page_errors': 0, 'blocked_browser_requests': 0,
              'expected_app_sha256': sha(app_source), 'startup_profile': meta.get('startup_profile', 'full')}
    proc = context = None
    try:
        proc, origin, ready = start_server(sandbox, record['startup_profile'])
        record['server'] = ready
        if proc is None:
            return record
        # Load the original module, including its original navigation/helper code.
        spec = importlib.util.spec_from_file_location('v1271_frontend_host', ROOT / 'tests/test_frontend.py')
        frontend = importlib.util.module_from_spec(spec)
        # Compile actual source, bypassing any stale .pyc without changing the file.
        exec(compile((ROOT / 'tests/test_frontend.py').read_bytes(), str(ROOT / 'tests/test_frontend.py'), 'exec'), frontend.__dict__)
        frontend._DASHBOARD_ORIGIN = origin
        original_route = frontend._route_frontend_sources
        original_goto = frontend._goto_dashboard
        def route_sources(page, source_path=None):
            original_route(page, source_path)
            # Same interception in both cases. chat.js is NEVER intercepted.
            page.route('**/static/js/app.js*', lambda route: route.fulfill(
                status=200, content_type='application/javascript', body=app_source))
        def goto(page, language='en'):
            response = original_goto(page, language)
            if record['startup_profile'] == 'source-only':
                page.wait_for_function('window.__V1271_SOURCE_READY === true', timeout=8000)
            text = page.evaluate('String(_finalizeStreamBubble)')
            record['runtime_finalizer_sha256'] = sha(text.encode())
            if name == 'guard':
                page.evaluate(GUARD)
            return response
        frontend._route_frontend_sources = route_sources
        frontend._goto_dashboard = goto
        pages = []
        def new_page(**kwargs):
            nonlocal context
            if context is not None:
                raise InvalidDiagnostic('unexpected_extra_browser_context')
            context = browser.new_context(**kwargs, service_workers='block')
            def only_fixture(route):
                if urlsplit(route.request.url).netloc == urlsplit(origin).netloc and urlsplit(route.request.url).scheme == 'http':
                    route.continue_()
                else:
                    record['blocked_browser_requests'] += 1
                    route.abort()
            context.route('**/*', only_fixture)
            if hasattr(context, 'route_web_socket'):
                context.route_web_socket('**/*', lambda ws: ws.close())
            def response_seen(response):
                path = urlsplit(response.url).path
                if path not in {'/static/js/app.js', '/static/js/chat.js'}:
                    return
                try:
                    body = response.body()
                    record['responses'].append({'path': path, 'status': response.status,
                                                'sha256': sha(body), 'bytes': len(body)})
                except Exception as error:
                    record['capture_errors'].append(type(error).__name__)
            context.on('response', response_seen)
            page = context.new_page()
            page.on('pageerror', lambda error: record.update(page_errors=record['page_errors'] + 1))
            pages.append(page)
            return page
        finalizers = []
        record['executions'] += 1
        try:
            getattr(frontend, FROZEN)(SimpleNamespace(new_page=new_page), SimpleNamespace(addfinalizer=finalizers.append))
            record['result'] = 'PASS'
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as error:
            record['result'] = 'FAIL' if isinstance(error, AssertionError) or type(error).__name__ == 'TimeoutError' else 'ERROR'
            record['error'] = exception_info(error)
        if pages:
            try:
                record['state'] = pages[-1].evaluate(STATE)
            except Exception as error:
                record['capture_errors'].append(type(error).__name__)
        for callback in reversed(finalizers):
            callback()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as error:
        record['error'] = exception_info(error)
        record['result'] = 'ERROR'
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as error:
                record.setdefault('cleanup_errors', []).append(exception_info(error))
        if proc is not None:
            try:
                stop_server(proc)
            except Exception as error:
                record.setdefault('cleanup_errors', []).append(exception_info(error))
                record['fixture_pid'] = proc.pid
        policy = sandbox / 'server-policy.json'
        startup = sandbox / 'server-startup.json'
        if 'server' not in record and startup.exists():
            record['server'] = json.loads(startup.read_text())
        if policy.exists():
            record['server_policy'] = json.loads(policy.read_text())
            record['server_policy_denials'] = record['server_policy']['denied']
        if proc is None or proc.poll() is not None:
            shutil.rmtree(sandbox)
    return record


def verdict(cases, meta, unchanged):
    issues = []
    if [c.get('variant') for c in cases] != ['baseline', 'final', 'guard'] or not unchanged:
        issues.append('case_inventory_or_source_drift')
    for case in cases:
        if case.get('startup_profile', 'full') != meta.get('startup_profile', 'full'):
            issues.append(case['variant'] + ':mixed_startup_profiles')
        if case.get('executions') != 1 or case.get('result') == 'ERROR' or case.get('capture_errors') or case.get('page_errors') or case.get('cleanup_errors'):
            issues.append(case['variant'] + ':execution_or_capture_error')
        for path, expected in [('/static/js/app.js', case.get('expected_app_sha256')),
                               ('/static/js/chat.js', meta['chat_disk_sha256'])]:
            rows = [r for r in case.get('responses', []) if r['path'] == path]
            if len(rows) != 1 or rows[0]['status'] != 200 or rows[0]['sha256'] != expected:
                issues.append(case['variant'] + ':http_provenance:' + path)
        if case.get('runtime_finalizer_sha256') != meta['runtime_finalizer_sha256']:
            issues.append(case['variant'] + ':runtime_finalizer_mismatch')
        if not case.get('server_policy', {}).get('capture_enabled'):
            issues.append(case['variant'] + ':missing_durable_server_diagnostics')
    guard = next((c for c in cases if c.get('variant') == 'guard'), {})
    state = guard.get('state', {})
    frames = guard.get('error', {}).get('frames', [])
    intended_wait = any(f['file'] == 'tests/test_frontend.py' and f['function'] == FROZEN
                        and f['line'] == meta['frozen_wait_line'] for f in frames)
    node = state.get('node') or {}
    if not (guard.get('result') == 'FAIL' and guard.get('error', {}).get('type') == 'TimeoutError'
            and intended_wait and state.get('guardCalls') == 1 and node.get('kind') == 'agent'
            and node.get('textLength', 0) >= 200 and not state.get('streamBubble') and not state.get('deferred')):
        issues.append('false_positive_guard_failed')
    if issues:
        return 2, issues
    return (1 if any(c['result'] != 'PASS' for c in cases[:2]) else 0), []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--startup-only', action='store_true')
    parser.add_argument('--startup-profile', choices=['full', 'chat-only', 'source-only'], default='full')
    parser.add_argument('--policy-child', type=Path)
    parser.add_argument('--serve', nargs=3, metavar=('SANDBOX', 'SOCKET_FD', 'READY_FD'))
    args = parser.parse_args()
    if args.serve:
        return serve(Path(args.serve[0]), int(args.serve[1]), int(args.serve[2]))
    if args.policy_child:
        return policy_self_check(args.policy_child)
    if sum([args.run, args.preflight, args.self_check, args.startup_only]) != 1:
        parser.error('choose exactly one of --run, --preflight, --self-check or --startup-only')
    try:
        baseline, final, meta = sources()
        meta['startup_profile'] = args.startup_profile
        if args.self_check:
            return self_check(meta)
        required = [] if args.startup_profile == 'source-only' else ['app/main.py', 'app/db.py', 'app/routes/sessions.py']
        missing = [name for name in required if not (ROOT / name).is_file()]
        if missing:
            result = {'status': 'BLOCKED', 'rc': 2, 'missing_full_checkout_files': missing, 'sources': meta}
            write_json(NOTES / 'host-preflight.json', result)
            print(json.dumps(result))
            return 2
        if args.preflight:
            write_json(NOTES / 'host-preflight.json', {'status': 'PASS', 'sources': meta})
            print('Source/full-checkout preflight PASS; server/browser have NOT run.')
            return 0
        before = fingerprints()
        run = Path(tempfile.mkdtemp(prefix='host-run-', dir=NOTES))
        (run / 'tmp').mkdir()
        os.environ['TMPDIR'] = str(run / 'tmp')
        tempfile.tempdir = None
        if args.startup_only:
            sandbox = run / 'startup'
            sandbox.mkdir()
            proc = None
            try:
                proc, origin, packet = start_server(sandbox, args.startup_profile)
            finally:
                if proc is not None:
                    stop_server(proc)
            policy = sandbox / 'server-policy.json'
            record = {'scope': 'startup-only; NO frozen test or browser acceptance',
                      'executions': 0, 'server': packet, 'sources': meta,
                      'source_hashes_before': before, 'source_hashes_after': fingerprints()}
            if policy.exists():
                record['server_policy'] = json.loads(policy.read_text())
            rc = 0 if proc is not None and before == fingerprints() else 2
            record['rc'] = rc
            write_json(run / 'startup-result.json', record)
            shutil.rmtree(sandbox)
            shutil.rmtree(run / 'tmp')
            print(json.dumps({'rc': rc, 'scope': 'startup-only; acceptance NOT run',
                              'artifact': relative(run / 'startup-result.json')}))
            return rc
        from playwright.sync_api import sync_playwright
        cases = []
        with sync_playwright() as p:
            browser_env = {k: v for k, v in os.environ.items() if k in {
                'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'TZ', 'FONTCONFIG_PATH', 'XDG_CACHE_HOME'}}
            browser = p.chromium.launch(executable_path=os.environ.get('CHAT_ANSWERS_CHROME') or None,
                                        args=['--no-proxy-server'], env=browser_env)
            try:
                for name, app in [('baseline', baseline), ('final', final), ('guard', final)]:
                    sandbox = run / name
                    sandbox.mkdir()
                    case = run_case(browser, sandbox, name, app, meta)
                    cases.append(case)
                    write_json(run / (name + '.json'), case)
            finally:
                browser.close()
        shutil.rmtree(run / 'tmp')
        rc, issues = verdict(cases, meta, before == fingerprints())
        scope = {'full': 'full-startup HTTP/frozen-body diagnostic',
                 'chat-only': 'chat-only HTTP/frozen-body diagnostic; startup services excluded',
                 'source-only': 'isolated source HTTP/frozen-body comparison; NO backend/middleware/startup/API acceptance'}[args.startup_profile]
        write_json(run / 'result.json', {'rc': rc, 'issues': issues, 'sources': meta, 'scope': scope,
                                        'startup_profile': args.startup_profile,
                                        'source_hashes_before': before, 'source_hashes_after': fingerprints(),
                                        'cases': cases, 'sanitized_publication_copy': True})
        print(json.dumps({'rc': rc, 'artifact': relative(run / 'result.json'), 'scope': scope,
                          'startup_profile': args.startup_profile,
                          'cases': [{'variant': c['variant'], 'result': c['result']} for c in cases], 'issues': issues}))
        return rc
    except BaseException as error:
        result = {'rc': 2, 'error': exception_info(error), 'reason': str(error) if isinstance(error, InvalidDiagnostic) else 'setup_error'}
        write_json(NOTES / 'host-runner-error.json', result)
        print(json.dumps(result))
        return 2


def self_check(meta):
    """Policy verdict checks: an empty/stubbed/cached/wrong-source run cannot pass."""
    def valid_case(name):
        return {'variant': name, 'executions': 1, 'result': 'PASS', 'server_policy': {'capture_enabled': True},
                'startup_profile': meta.get('startup_profile', 'full'), 'responses': [
            {'path': '/static/js/app.js', 'status': 200, 'sha256': 'app'},
            {'path': '/static/js/chat.js', 'status': 200, 'sha256': meta['chat_disk_sha256']}],
            'expected_app_sha256': 'app', 'runtime_finalizer_sha256': meta['runtime_finalizer_sha256']}
    cases = [valid_case(n) for n in ['baseline', 'final', 'guard']]
    cases[2].update(result='FAIL', error={'type': 'TimeoutError', 'frames': [
        {'file': 'tests/test_frontend.py', 'function': FROZEN, 'line': meta['frozen_wait_line']}]},
        state={'guardCalls': 1, 'node': {'kind': 'agent', 'textLength': 255}, 'streamBubble': False, 'deferred': False})
    import copy
    assert verdict(cases, meta, True) == (0, [])
    checks = ['valid_control_bundle']
    for name, mutate in [
        ('no_test_execution', lambda c: c[0].update(executions=0)),
        ('missing_http_chat', lambda c: c[0]['responses'].pop()),
        ('wrong_http_chat', lambda c: c[0]['responses'][1].update(sha256='wrong')),
        ('wrong_runtime', lambda c: c[1].update(runtime_finalizer_sha256='wrong')),
        ('guard_unexpected_pass', lambda c: c[2].update(result='PASS')),
        ('guard_wrong_failure_line', lambda c: c[2]['error']['frames'][0].update(line=1)),
        ('mixed_startup_profiles', lambda c: c[0].update(startup_profile='inconsistent')),
        ('missing_durable_diagnostics', lambda c: c[1].pop('server_policy')),
    ]:
        broken = copy.deepcopy(cases)
        mutate(broken)
        assert verdict(broken, meta, True)[0] == 2, name
        checks.append(name)
    failed = copy.deepcopy(cases); failed[1]['result'] = 'FAIL'
    assert verdict(failed, meta, True) == (1, [])
    assert verdict(cases, meta, False)[0] == 2
    policy_dir = Path(tempfile.mkdtemp(prefix='host-policy-', dir=NOTES))
    env = {'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'C.UTF-8'}
    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--policy-child', str(policy_dir)],
                           env=env, capture_output=True, text=True, timeout=15)
    if child.returncode != 0:
        raise InvalidDiagnostic('policy_self_check_failed')
    policy = json.loads(child.stdout)
    shutil.rmtree(policy_dir)
    write_json(NOTES / 'host-runner-self-check.json', {'result': 'PASS', 'checks': checks + ['normal_failure_rc1', 'source_drift_rc2'],
                                                     'policy': policy, 'scope': 'Verdict/provenance and synthetic boundary checks only; no host/browser acceptance claimed.'})
    print('PASS: 11 verdict/provenance controls + synthetic boundary checks; host/browser acceptance NOT run.')
    return 0


def policy_self_check(base):
    # Every target is synthetic and task-local, including the protected test files.
    global ROOT
    base = base.resolve()
    if NOTES not in base.parents or not base.name.startswith('host-policy-'):
        return 2
    ROOT = base / 'synthetic-project'
    private = ROOT / '.orchestra/private'
    private.mkdir(parents=True)
    (private / 'sentinel').write_text('synthetic')
    sandbox = ROOT / 'sandbox'
    sandbox.mkdir()
    (sandbox / '.env').write_text('synthetic')
    (base / 'outside-sentinel').write_text('synthetic')
    synthetic_mime = base / 'synthetic-host.mime'
    synthetic_mime.write_text('application/x-synthetic never_use\n')
    import mimetypes
    mimetypes.knownfiles = [str(synthetic_mime)]
    mimetypes.MimeTypes.read_windows_registry = lambda *args, **kwargs: None
    mimetypes._db = None
    mimetypes.inited = False
    outside = ROOT / 'synthetic-source'
    outside.mkdir()
    (sandbox / 'source-link').symlink_to(outside, target_is_directory=True)
    import sqlite3
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    denied = {}
    details = []
    install_server_policy(sandbox, port, denied, details, {'name': 'self-check'})
    (sandbox / 'allowed.txt').write_text('ok')
    with sqlite3.connect(sandbox / 'allowed.db') as db:
        db.execute('create table synthetic(value integer)')
    # Negative control: on first init, files=[] still opens knownfiles.
    try:
        mimetypes.init(files=[])
    except PermissionError:
        pass
    else:
        raise InvalidDiagnostic('empty_mime_init_did_not_exercise_knownfiles')
    mime = initialize_fixture_mimetypes()
    mime_asset = sandbox / 'mime-fixture.js'
    mime_asset.write_bytes(b'// synthetic MIME fixture\n')
    from starlette.responses import FileResponse
    import asyncio
    messages = []
    async def receive():
        return {'type': 'http.request', 'body': b''}
    async def send(message):
        messages.append(message)
    asyncio.run(FileResponse(mime_asset)({'type': 'http', 'method': 'GET', 'headers': []}, receive, send))
    if messages[0]['status'] != 200 or b''.join(m.get('body', b'') for m in messages) != mime_asset.read_bytes():
        raise InvalidDiagnostic('fixture_mime_file_response_failed')
    def connect_nonfixture():
        with socket.socket() as connection:
            connection.connect(('127.0.0.1', 0))
    tests = [
        lambda: (private / 'sentinel').read_text(),
        lambda: (sandbox / '.env').read_text(),
        lambda: (ROOT / 'outside.txt').write_text('blocked'),
        lambda: sqlite3.connect(ROOT / 'outside.db'),
        lambda: subprocess.run([sys.executable, '-c', 'pass # SYNTHETIC_PRIVATE_ARGV_MARKER'],
                               env={'SYNTHETIC_ENV': 'SYNTHETIC_PRIVATE_ENV_MARKER'}, check=True),
        lambda: socket.create_connection(('127.0.0.1', 0), timeout=1),
        connect_nonfixture,
        lambda: (base / 'outside-sentinel').read_text(),
        lambda: (sandbox / 'source-link/blocked.txt').write_text('blocked'),
    ]
    for operation in tests:
        try:
            operation()
        except PermissionError:
            continue
        raise InvalidDiagnostic('policy_did_not_block_synthetic_operation')
    listener.close()
    # Same relative-write isolation used by chat-only startup profile.
    os.chdir(sandbox)
    Path('runtime-cache').mkdir()
    Path('runtime-cache/synthetic.txt').write_text('ok')
    assert all(record['event'] and record['frames'] and record['phase'] == 'self-check' for record in details)
    assert 'SYNTHETIC_PRIVATE_ARGV_MARKER' not in json.dumps(details)
    assert 'SYNTHETIC_PRIVATE_ENV_MARKER' not in json.dumps(details)
    print(json.dumps({'result': 'PASS', 'rejected_operations': len(tests) + 1, 'denials': denied,
                      'denial_details': details,
                      'mime': {'negative_empty_init': 'DENIED', 'initialized': mime, 'file_response_status': 200},
                      'allowed': ['sandbox_file_write', 'sandbox_sqlite', 'sandbox_cwd_relative_write', 'builtin_mime_file_response']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
