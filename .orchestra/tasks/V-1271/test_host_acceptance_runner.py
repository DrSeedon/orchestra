"""Runner controls only. These tests do not claim host acceptance."""
import importlib.util
import asyncio
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


def load_runner():
    path = Path(__file__).with_name('host-acceptance.py')
    spec = importlib.util.spec_from_file_location('host_acceptance_control', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exact_baseline_and_frozen_body_are_pinned():
    runner = load_runner()
    baseline, final, meta = runner.sources()
    assert baseline != final
    assert meta['baseline_blob'] == '82c065aaada5f9758cf829987bc888b327c7ae8e'
    assert meta['frozen_wait_line'] == 5127
    assert meta['frozen_body_sha256'] == runner.BODY_SHA


def test_false_positive_rejection_and_real_synthetic_boundaries():
    runner = load_runner()
    _, _, meta = runner.sources()
    assert runner.self_check(meta) == 0


def test_formatted_startup_failure_without_exc_info_is_captured_safely():
    runner = load_runner()
    marker = 'SYNTHETIC_PRIVATE_VALUE_MUST_NOT_APPEAR'
    text = f'Traceback (most recent call last):\n  File "{runner.ROOT / "app/main.py"}", line 123, in lifespan\nPermissionError: {marker}\n'
    parsed = runner.safe_formatted_trace(text)
    assert parsed['type'] == 'PermissionError'
    assert parsed['frames'] == [{'file': 'app/main.py', 'line': 123, 'function': 'lifespan'}]
    assert marker not in json.dumps(parsed)
    assert str(runner.ROOT) not in json.dumps(parsed)


def test_observer_records_failed_lifespan_even_when_logger_has_no_exc_info():
    runner = load_runner()
    diagnostics, phase, messages = [], {'name': 'before'}, []
    marker = 'SYNTHETIC_PRIVATE_EXCEPTION_MESSAGE'
    async def application(scope, receive, send):
        await send({'type': 'lifespan.startup.failed', 'message':
                    f'  File "{runner.ROOT / "app/main.py"}", line 321, in lifespan\nRuntimeError: {marker}'})
        raise RuntimeError(marker)
    async def receive():
        return {'type': 'lifespan.startup'}
    async def send(message):
        messages.append(message['type'])
    with pytest.raises(RuntimeError):
        asyncio.run(runner.ObserveLifespan(application, diagnostics, phase)(
            {'type': 'lifespan'}, receive, send))
    assert phase['name'] == 'lifespan'
    assert messages == ['lifespan.startup.failed']
    assert any(d.get('channel') == 'formatted_traceback' for d in diagnostics)
    assert any(d['type'] == 'RuntimeError' for d in diagnostics)
    assert marker not in json.dumps(diagnostics)
    assert str(runner.ROOT) not in json.dumps(diagnostics)


def test_chat_fixture_lifespan_does_not_run_actor_services():
    runner = load_runner()
    calls = []
    @asynccontextmanager
    async def original_startup(app):
        calls.append('actor-service')
        if calls:
            raise PermissionError('synthetic startup service denied')
        yield
    app = SimpleNamespace(router=SimpleNamespace(lifespan_context=original_startup))
    async def check():
        assert runner.configure_fixture_app(app, 'full') == []
        with pytest.raises(PermissionError):
            async with app.router.lifespan_context(app):
                pass
        assert len(calls) == 1
        assert runner.configure_fixture_app(app, 'chat-only') == ['synthetic_cwd', 'synthetic_seed_db_only_lifespan']
        async with app.router.lifespan_context(app):
            assert len(calls) == 1
    asyncio.run(check())


def test_large_startup_diagnostics_do_not_fill_readiness_pipe(tmp_path):
    runner = load_runner()
    data = {'event': 'startup_failed', 'diagnostics': [
        {'type': 'PermissionError', 'frames': [{'file': 'app/main.py', 'line': 123, 'function': 'lifespan'}]}
    ] * 1000}
    assert len(json.dumps(data)) > 65536
    read_fd, write_fd = os.pipe()
    try:
        runner.publish_startup(tmp_path, write_fd, data)
        packet = os.read(read_fd, 4096)
        assert len(packet) < 512
        assert json.loads(packet) == {'event': 'startup_failed', 'detail': 'server-startup.json'}
        assert json.loads((tmp_path / 'server-startup.json').read_text()) == data
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_static_http_exception_group_is_captured_without_body_or_query():
    runner = load_runner()
    diagnostics, phase = [{}] * 40, {'name': 'serving'}
    marker = 'SYNTHETIC_PRIVATE_BODY_AND_EXCEPTION'
    async def application(scope, receive, send):
        assert runner.STATIC_REQUEST.get() == '/static/js/chat.js'
        await send({'type': 'http.response.start', 'status': 500, 'headers': []})
        await send({'type': 'http.response.body', 'body': marker.encode()})
        raise ExceptionGroup(marker, [PermissionError(marker)])
    async def receive():
        return {'type': 'http.request', 'body': b''}
    async def send(message):
        pass
    with pytest.raises(ExceptionGroup):
        asyncio.run(runner.ObserveLifespan(application, diagnostics, phase)(
            {'type': 'http', 'path': '/static/js/chat.js', 'query_string': marker.encode()}, receive, send))
    record = diagnostics[-1]
    assert record['channel'] == 'http_static_exception' and record['status'] == 500
    assert record['error']['causes'][0]['type'] == 'PermissionError'
    assert marker not in json.dumps(diagnostics)
    assert str(runner.ROOT) not in json.dumps(diagnostics)
    assert runner.STATIC_REQUEST.get() is None


def test_static_500_without_raised_exception_still_gets_a_diagnostic():
    runner = load_runner()
    diagnostics = []
    async def application(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 500, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})
    async def receive():
        return {'type': 'http.request', 'body': b''}
    async def send(message):
        pass
    asyncio.run(runner.ObserveLifespan(application, diagnostics, {})(
        {'type': 'http', 'path': '/static/js/chat.js'}, receive, send))
    assert diagnostics == [{'channel': 'http_static_500_without_exception', 'path': '/static/js/chat.js', 'status': 500}]


def test_source_fixture_returns_exact_checkout_chat_and_has_no_api():
    runner = load_runner()
    from starlette.testclient import TestClient
    with TestClient(runner.source_application()) as client:
        response = client.get('/static/js/chat.js')
        assert response.status_code == 200
        assert runner.sha(response.content) == runner.CHAT_SHA
        assert client.get('/api/models').status_code == 404
        html = client.get('/').text
        assert '__V1271_SOURCE_READY' in html
        assert 'initChatTimeline()' in html
    assert runner.source_asset('../../../uv.lock') is None


def test_http_exception_is_persisted_before_server_shutdown(tmp_path):
    runner = load_runner()
    diagnostics, target = [], tmp_path / 'capture.json'
    async def application(scope, receive, send):
        raise PermissionError('synthetic state write denied')
    async def receive():
        return {'type': 'http.request', 'body': b''}
    async def send(message):
        pass
    def persist():
        runner.write_json_atomic(target, {'diagnostics': list(diagnostics)})
    with pytest.raises(PermissionError):
        asyncio.run(runner.ObserveLifespan(application, diagnostics, {}, persist)(
            {'type': 'http', 'path': '/static/js/chat.js'}, receive, send))
    assert json.loads(target.read_text())['diagnostics'][0]['error']['type'] == 'PermissionError'


def test_atomic_capture_handles_parallel_static_failures(tmp_path):
    runner = load_runner()
    from concurrent.futures import ThreadPoolExecutor
    target = tmp_path / 'capture.json'
    def write(index):
        runner.write_json_atomic(target, {'event': index, 'frames': ['safe'] * 100})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, range(12)))
    data = json.loads(target.read_text())
    assert data['event'] in range(12) and data['frames'] == ['safe'] * 100
    assert not target.with_name('.capture.json.tmp').exists()


def test_mime_initialization_uses_only_builtins_even_on_first_init(monkeypatch, tmp_path):
    runner = load_runner()
    import mimetypes
    # Track globals so the fixture-local change cannot leak into other tests.
    for key in ['knownfiles', 'inited', '_db', 'suffix_map', 'types_map', 'encodings_map', 'common_types']:
        monkeypatch.setattr(mimetypes, key, getattr(mimetypes, key))
    monkeypatch.setattr(mimetypes.MimeTypes, 'read_windows_registry', mimetypes.MimeTypes.read_windows_registry)
    synthetic = tmp_path / 'host.mime'
    synthetic.write_text('application/x-synthetic never_use\n')
    mimetypes.knownfiles = [str(synthetic)]
    mimetypes._db, mimetypes.inited = None, False
    def forbidden_read(*args, **kwargs):
        raise AssertionError('MIME file read attempted')
    monkeypatch.setattr(mimetypes.MimeTypes, 'read', forbidden_read)
    meta = runner.initialize_fixture_mimetypes()
    assert meta['knownfiles_count'] == 0 and meta['registry_reader_disabled']
    assert meta['javascript'] in {'text/javascript', 'application/javascript'}
    assert meta['css'] == 'text/css' and meta['svg'] == 'image/svg+xml'
    # A later reset also remains isolated for the life of this server process.
    mimetypes.init()
    assert mimetypes.guess_type('chat.js')[0] == meta['javascript']
