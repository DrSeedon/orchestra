"""Bounded local subprocesses with durable streaming receipts and graceful stopping."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import time

from .accounting import Accounting


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


async def run_process(argv, cwd, env, output, *, runtime='fixture', prompt='', timeout=600, grace=15, budget=None, prices=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ledger = Accounting(runtime, prices)
    started = time.monotonic()
    result = {'argv': argv, 'cwd': str(cwd), 'started_unix': time.time(), 'completion': 'starting', 'returncode': None}
    budget_event = asyncio.Event()
    proc = None
    readers = []
    feeder = None
    response = ''

    async def drain(stream, path, parse):
        pending = b''
        with path.open('wb') as file:
            while chunk := await stream.read(65536):
                file.write(chunk)
                file.flush()
                if not parse:
                    continue
                pending += chunk
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    consume(line)
            if parse and pending:
                consume(pending)

    def consume(raw):
        nonlocal response
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeError):
            return
        if isinstance(row, dict):
            if runtime == 'fixture' and row.get('type') == 'bench.result' and isinstance(row.get('response'), str):
                response = row['response']
            elif runtime == 'claude' and row.get('type') == 'result' and isinstance(row.get('result'), str):
                response = row['result']
            elif runtime == 'codex' and row.get('type') == 'item.completed' and isinstance(row.get('item'), dict) and row['item'].get('type') == 'agent_message':
                response = row['item'].get('text', '') if isinstance(row['item'].get('text', ''), str) else ''
            (output / 'response.txt').write_text(response)
        if isinstance(row, dict) and ledger.feed(row):
            receipt = ledger.receipt()
            write_json(output / 'accounting.json', receipt)
            observed = receipt['observed_cost_usd']
            if budget is not None and observed is not None and observed >= budget:
                budget_event.set()

    def send(sig):
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                # Check the group of this still-owned live child, not a historical PGID.
                if os.getpgid(proc.pid) == proc.pid:
                    os.killpg(proc.pid, sig)
                else:
                    proc.send_signal(sig)

    async def finish_after_signal():
        send(signal.SIGINT)
        try:
            await asyncio.wait_for(proc.wait(), grace)
        except asyncio.TimeoutError:
            send(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), min(2, grace))
            except asyncio.TimeoutError:
                send(signal.SIGKILL)
                await proc.wait()
                result['hard_killed'] = True

    cancelled = False
    try:
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        result['pid'] = proc.pid
        write_json(output / 'process.json', result)
        readers = [asyncio.create_task(drain(proc.stdout, output / 'stdout.jsonl', True)), asyncio.create_task(drain(proc.stderr, output / 'stderr.log', False))]
        async def feed_input():
            try:
                proc.stdin.write(prompt.encode())
                await proc.stdin.drain()
                result['stdin_sent'] = True
            except (BrokenPipeError, ConnectionResetError):
                result['stdin_sent'] = False
            finally:
                proc.stdin.close()
        feeder = asyncio.create_task(feed_input())
        waiter = asyncio.create_task(proc.wait())
        budget_waiter = asyncio.create_task(budget_event.wait())
        try:
            done, _ = await asyncio.wait([waiter, budget_waiter], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if waiter in done:
                result['completion'] = 'exited'
            else:
                result['completion'] = 'budget' if budget_waiter in done else 'deadline'
                await finish_after_signal()
        finally:
            budget_waiter.cancel()
            await asyncio.gather(budget_waiter, return_exceptions=True)
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
    except asyncio.CancelledError:
        cancelled = True
        result['completion'] = 'cancelled'
        if proc is not None:
            await finish_after_signal()
    except (OSError, BrokenPipeError) as error:
        result['completion'] = 'launch_error'
        result['error'] = f'{type(error).__name__}: {error}'
        if proc is not None and proc.returncode is None:
            await finish_after_signal()
    finally:
        if feeder is not None:
            if not feeder.done():
                feeder.cancel()
                result['stdin_sent'] = False
            await asyncio.gather(feeder, return_exceptions=True)
        if readers:
            try:
                await asyncio.wait_for(asyncio.gather(*readers), max(2, grace))
            except asyncio.TimeoutError:
                result['stream_incomplete'] = True
        (output / 'response.txt').write_text(response)
        result['returncode'] = proc.returncode if proc else None
        result['wall_seconds'] = time.monotonic() - started
        result['accounting'] = ledger.receipt()
        write_json(output / 'accounting.json', result['accounting'])
        write_json(output / 'process.json', result)
    if cancelled:
        raise asyncio.CancelledError
    return result
