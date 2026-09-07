"""No model calls: inspect CLI config routing and authentication on empty homes."""
import asyncio
import json
import os
import sys
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[3]


async def probe(case):
    base = ROOT / 'data/523/config' / f'{case}-{time.time_ns()}'
    home = base / 'home'
    home.mkdir(parents=True)
    env = dict(os.environ)
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_SQLITE_HOME'):
        env.pop(key, None)
    env['CODEX_HOME'] = str(home)
    args = ['codex', '--strict-config']
    if case in ('config', 'env'):
        args += ['-c', f'sqlite_home="{base / "configured-db"}"',
                 '-c', 'history.persistence="none"', '-c', 'history.max_bytes=1024']
    if case in ('env', 'env-only'):
        env['CODEX_SQLITE_HOME'] = str(base / 'env-db')
    if case == 'shared-index':
        private_home = next((ROOT / 'data/523/homes').glob('private-*'))
        args += ['-c', f'sqlite_home="{private_home}"']
    args += ['app-server', '--stdio']
    with (base / 'stderr.log').open('wb') as err:
        p = await asyncio.create_subprocess_exec(*args, cwd=base, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=err)
        async def request(num, method, params):
            p.stdin.write((json.dumps({'id': num, 'method': method, 'params': params})+'\n').encode())
            await p.stdin.drain()
            while True:
                line = await asyncio.wait_for(p.stdout.readline(), 6)
                if not line:
                    raise RuntimeError('EOF')
                msg = json.loads(line)
                if msg.get('id') == num:
                    return msg
        try:
            await request(1, 'initialize', {'clientInfo': {'name': 'home523', 'version': '1'},
                                          'capabilities': {'experimentalApi': True}})
            config = await request(2, 'config/read', {'includeLayers': False})
            value = config.get('result', {}).get('config', {})
            account = await request(3, 'account/read', {'refreshToken': False})
            if case in ('foreign-private', 'shared-index'):
                rows = [json.loads(line) for line in Path(__file__).with_name('private.log').read_text().splitlines()
                        if line.startswith('{')]
                tid = next(row['thread_id'] for row in rows if 'thread_id' in row)
                thread = await request(4, 'thread/resume', {'threadId': tid, 'excludeTurns': True})
            else:
                thread = await request(4, 'thread/start', {'model': 'gpt-5.6-luna', 'cwd': str(base)})
            print(json.dumps({'case': case, 'home': str(home),
                'config': {k:value.get(k) for k in ('sqlite_home','history')},
                'config_error': config.get('error'), 'account': account.get('result'),
                'thread_started': bool(thread.get('result',{}).get('thread',{}).get('id')),
                'thread_error': thread.get('error'),
                'db_locations': [str(x.relative_to(base)) for x in base.rglob('state_5.sqlite')]},
                ensure_ascii=False), flush=True)
        finally:
            p.terminate()
            await asyncio.wait_for(p.wait(), 4)


async def main():
    for case in (sys.argv[1:] or ('empty', 'config', 'env')):
        await probe(case)


asyncio.run(main())
