"""Real backend acceptance; isolate paths and MCP only, never home preparation."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import app.backend_codex as module


def size(home):
    by_top = {}
    disk = 0
    for directory, _, files in os.walk(home, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            info = path.stat()
            top = path.relative_to(home).parts[0]
            by_top[top] = by_top.get(top, 0) + info.st_size
            disk += info.st_blocks * 512
    return {"bytes": sum(by_top.values()), "allocated_bytes": disk, "by_top": by_top}


async def main():
    os.environ['CODEX_HOME'] = str(Path.home() / '.codex')
    module._CODEX_HOME_ROOT = ROOT / 'data/523/implementation-homes'
    sid = 'private-' + str(time.time_ns())
    home = module._CODEX_HOME_ROOT / sid
    cwd = ROOT / 'data/523/implementation-work'
    cwd.mkdir(parents=True, exist_ok=True)
    assert not home.exists()
    be = module.CodexBackend(
        model='gpt-5.6-luna', cwd=str(cwd), reasoning_effort='low',
        system_prompt='Isolated acceptance probe. Follow the requested checks only.',
        mcp_servers={'orchestra': {
            'command': sys.executable,
            'args': [str(Path(__file__).with_name('probe_mcp.py'))],
            'enabled_tools': ['audit_ping'], 'env': {'ORCHESTRA_SESSION_ID': sid},
        }},
    )
    print(json.dumps({'module': module.__file__, 'home': str(home), 'initial_exists': False}), flush=True)
    async def turn(prompt):
        await be.send(prompt)
        texts, results = [], []
        async for event in be.events():
            if event.type in ('text', 'tool_use', 'tool_result', 'turn_end', 'error'):
                print(json.dumps({'event': event.type, 'content': str(event.content)[:2000]}), flush=True)
            if event.type == 'text':
                texts.append(str(event.content))
            if event.type == 'tool_result':
                results.append(str(event.content))
        return ''.join(texts), '\n'.join(results)
    async def run():
        start = time.monotonic()
        await be.connect()
        assert (home / 'sessions').is_dir() and not (home / 'sessions').is_symlink()
        print(json.dumps({'phase': 'connected', 'seconds': time.monotonic()-start, 'size': size(home)}), flush=True)
        text, results = await turn('Call audit_ping once and run `echo HOME523_SHELL_OK` once. Report both results. Remember nonce PRIVATE523_CONTEXT_892.')
        assert 'HOME523_MCP_OK' in results and 'HOME523_SHELL_OK' in results, (text, results)
        tid = be._thread_id
        print(json.dumps({'phase': 'first_turn', 'thread_id': tid, 'size': size(home),
                          'runtime_context': be._runtime_context()}), flush=True)
        await be.disconnect()
        await be.connect()
        assert be._thread_id == tid
        print(json.dumps({'phase': 'reconnected', 'same_thread': True}), flush=True)
        text, _ = await turn('Reply only with the nonce I gave in the previous message. No tools.')
        assert 'PRIVATE523_CONTEXT_892' in text, text
        print(json.dumps({'phase': 'two_turns', 'size': size(home),
                          'runtime_context': be._runtime_context(), 'passed': True}), flush=True)
    try:
        await asyncio.wait_for(run(), 100)
    finally:
        await be.disconnect()
        print(json.dumps({'phase': 'disconnected', 'size': size(home)}), flush=True)


asyncio.run(main())
