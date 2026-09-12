"""Real stdio MCP worker stand, isolated HTTP fixture, no provider or production API."""
import asyncio
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.manager import _make_mcp_config
from app.session import AgentSession
import app.mcp_stdio


class API(BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        type(self).calls += 1
        data = json.dumps({'name': 'probe-worker', 'status': 'idle'}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


async def main():
    print('imported_module=' + app.mcp_stdio.__file__)
    api = ThreadingHTTPServer(('127.0.0.1', 0), API)
    thread = Thread(target=api.serve_forever, daemon=True)
    thread.start()
    try:
        for role, disabled in [('worker', ['get_worker_info']), ('worker', []),
                               ('orchestrator', []), ('sub-orchestrator', []), ('full-cycle', [])]:
            worker = AgentSession(id='probe-' + role, name='probe-' + role, scope=str(Path.cwd()),
                                  cwd=str(Path.cwd()), model='gpt-5.6-luna', role=role,
                                  pipeline='default', disabled_tools=disabled)
            config = _make_mcp_config(worker.name, worker.scope, worker.role,
                                     pipeline=worker.pipeline, disabled_tools=worker.disabled_tools)['orchestra']
            env = dict(config['env'])
            for key in ('INTERNAL_TOKEN', 'HTTP_PROXY', 'HTTPS_PROXY', 'ORCHESTRA_MCP_PROOF'):
                env.pop(key, None)
            env.update(ORCHESTRA_URL=f'http://127.0.0.1:{api.server_port}', NO_PROXY='127.0.0.1')
            params = StdioServerParameters(command=config['command'], args=config['args'], env=env)
            before = API.calls
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as client:
                    await client.initialize()
                    names = {t.name for t in (await client.list_tools()).tools}
                    assert 'get_worker_info' in names
                    retired = 'run' + '_fan'
                    assert retired not in names
                    result = await client.call_tool('get_worker_info', {'name': worker.name})
                    assert result.isError == bool(disabled)
                    assert API.calls - before == (0 if disabled else 1)
                    if disabled:
                        assert result.structuredContent['error']['code'] == 'tool_disabled'
                    missing = await client.call_tool(retired, {})
                    assert missing.isError
                    assert API.calls - before == (0 if disabled else 1)
                    print(json.dumps({'role': role, 'disabled_tools': disabled, 'isError': result.isError,
                                      'http_calls': API.calls - before, 'catalog_count': len(names),
                                      'result': result.structuredContent}, ensure_ascii=False))
        print('LIVE PASS: fresh MCP processes, denied calls produced zero HTTP effects; allowed calls completed')
    finally:
        api.shutdown()
        api.server_close()
        thread.join()


if __name__ == '__main__':
    asyncio.run(main())
