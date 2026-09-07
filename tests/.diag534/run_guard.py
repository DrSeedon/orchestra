import os, pathlib, signal, subprocess, sys, time

root = pathlib.Path(__file__).resolve().parent
run = root / sys.argv[1]
run.mkdir()
cmd = [sys.executable, '-m', 'pytest', 'tests/test_frontend.py', 'tests/test_system_chat_entry.py', '-m', 'browser', '-vv', '-s', '-p', 'diag534', '-o', 'faulthandler_timeout=60', '--timeout=180', '--timeout-method=thread', '--basetemp='+str(run/'tmp')]
env = dict(os.environ, PYTHONPATH=str(root), DIAG_ORDER=sys.argv[2] if len(sys.argv)>2 else 'normal', DIAG_REPEAT=sys.argv[3] if len(sys.argv)>3 else '1')
with (run/'pytest.log').open('w') as output, (run/'processes.log').open('w') as snapshot:
    proc = subprocess.Popen(cmd, stdout=output, stderr=subprocess.STDOUT, env=env)
    start = time.monotonic()
    while proc.poll() is None:
        rows = {}
        for path in pathlib.Path('/proc').glob('[0-9]*'):
            try:
                fields = (path/'stat').read_text().rsplit(')', 1)[1].split()
                rows[int(path.name)] = (int(fields[1]), int(fields[21])*os.sysconf('SC_PAGE_SIZE'), path, fields[0])
            except (OSError, ValueError, IndexError):
                pass
        owned = {proc.pid}
        while True:
            found = {pid for pid, row in rows.items() if row[0] in owned}
            if found <= owned:
                break
            owned |= found
        rss = sum(rows[pid][1] for pid in owned if pid in rows)
        snapshot.write(f'ELAPSED {time.monotonic()-start:.1f} RSS {rss}\n')
        for pid in sorted(owned):
            if pid not in rows:
                continue
            _, mem, path, state = rows[pid]
            try:
                cmdline = (path/'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
                snapshot.write(f'{pid} {state} {mem} {(path/"wchan").read_text()} {cmdline}\n')
            except OSError:
                pass
        snapshot.flush()
        if rss > 2*1024**3 or time.monotonic()-start > 1100:
            snapshot.write('GUARD LIMIT\n')
            for pid in sorted(owned, reverse=True):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            break
        time.sleep(5)
    code = proc.wait()
print(f'RUN {sys.argv[1]} exit={code} elapsed={time.monotonic()-start:.1f}', flush=True)
sys.exit(code)
