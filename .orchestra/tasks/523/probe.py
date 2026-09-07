"""Bounded research probe with isolated SQLite and no production code edits."""
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import app.backend_codex as bc


def state(home):
    result = {}
    for name in ('state_5.sqlite', 'state_5.sqlite-wal'):
        p = home / name
        result[name] = p.stat().st_size if p.exists() else 0
    p = home / 'state_5.sqlite'
    if p.exists():
        try:
            with sqlite3.connect(f'file:{p}?mode=ro', uri=True, timeout=.1) as con:
                result['threads'] = con.execute('select count(*) from threads').fetchone()[0]
                result['backfill'] = con.execute('select * from backfill_state').fetchall()
        except sqlite3.Error as exc:
            result['read_error'] = str(exc)
    return result


async def main():
    mode = sys.argv[1]
    bc._CODEX_HOME_ROOT = ROOT / 'data/523/homes'
    bc._managed_codex_state_needs_seed = lambda *args: False
    os.environ['CODEX_HOME'] = str(Path.home() / '.codex')
    sid = f'{mode}-{time.time_ns()}'
    home = bc._CODEX_HOME_ROOT / sid
    cwd = ROOT / 'data/523/work'
    cwd.mkdir(parents=True, exist_ok=True)
    if mode == 'private':
        (home / 'sessions').mkdir(parents=True)
        (home / 'sessions/.keep').write_text('isolated research rollouts\n')
    be = bc.CodexBackend(
        model='gpt-5.6-luna', cwd=str(cwd), reasoning_effort='low',
        system_prompt='This is an isolated probe. Follow the requested command, use no other tools.',
        mcp_servers={'orchestra': {
            'command': sys.executable, 'args': [str(Path(__file__).with_name('probe_mcp.py'))],
            'enabled_tools': ['audit_ping'], 'env': {'ORCHESTRA_SESSION_ID': sid},
        }},
    )
    print(json.dumps({'module': bc.__file__, 'home': str(home), 'mode': mode,
                      'initial': state(home)}, ensure_ascii=False), flush=True)
    start = time.monotonic()
    async def run():
        await be.connect()
        print(json.dumps({'connected_seconds': time.monotonic()-start,
                          'thread_id': be._thread_id, 'state': state(home)}), flush=True)
        await be.send('Call audit_ping once; run `echo HOME523_SHELL_OK` once; then reply with both outputs. Remember nonce HOME523_MEMORY_731.')
        async for ev in be.events():
            if ev.type in ('text', 'tool_use', 'tool_result', 'turn_end', 'error'):
                print(json.dumps({'event': ev.type, 'content': str(ev.content)[:1500]}), flush=True)
        tid = be._thread_id
        await be.disconnect()
        print(json.dumps({'after_turn': state(home)}), flush=True)
        await be.connect()
        print(json.dumps({'resumed_same_thread': tid == be._thread_id, 'state': state(home)}), flush=True)
        await be.send('Reply with the nonce from my previous message only. Do not call tools.')
        async for ev in be.events():
            if ev.type in ('text', 'turn_end', 'error'):
                print(json.dumps({'resume_event': ev.type, 'content': str(ev.content)[:1500]}), flush=True)
    try:
        await asyncio.wait_for(run(), 43)
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__, 'detail': str(exc)}), flush=True)
    finally:
        await be.disconnect()
        print(json.dumps({'elapsed': time.monotonic()-start, 'final': state(home)}), flush=True)


asyncio.run(main())
