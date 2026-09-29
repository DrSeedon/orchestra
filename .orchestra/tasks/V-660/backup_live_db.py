"""Create a consistent SQLite backup of the active Orchestra database."""
import argparse
import pathlib
import sqlite3
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--snapshot', required=True, help='destination SQLite file on a filesystem with enough space')
out = pathlib.Path(parser.parse_args().snapshot)
out.parent.mkdir(parents=True, exist_ok=True)
pid = subprocess.check_output(['systemctl', 'show', 'orchestra', '-p', 'MainPID', '--value'], text=True).strip()
if not pid.isdigit() or pid == '0':
    raise SystemExit(f'No active orchestra MainPID: {pid!r}')
environ = pathlib.Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
paths = [entry.split(b'=', 1)[1].decode() for entry in environ if entry.startswith(b'ORCHESTRA_DB_PATH=')]
if len(paths) != 1:
    raise SystemExit(f'Expected one ORCHESTRA_DB_PATH in PID {pid}, got {len(paths)}')
src_path = pathlib.Path(paths[0])
if not src_path.is_file():
    raise SystemExit(f'Configured DB path is not a file: {src_path}')
src = sqlite3.connect(f'file:{src_path}?mode=ro', uri=True, timeout=60)
dst = sqlite3.connect(out)
try:
    src.backup(dst, pages=256, sleep=0.01)
    integrity = dst.execute('PRAGMA integrity_check').fetchone()[0]
    tables = {r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'turn_usage', 'usage_snapshots'}
    if not required <= tables:
        raise SystemExit(f'Missing required tables: {required - tables}')
    print(f'pid={pid} db_path={src_path} snapshot={out} bytes={out.stat().st_size} integrity={integrity}')
    print('turn_usage_columns=' + ','.join(r[1] for r in dst.execute('PRAGMA table_info(turn_usage)')))
    print('usage_snapshots_columns=' + ','.join(r[1] for r in dst.execute('PRAGMA table_info(usage_snapshots)')))
    print('turn_usage_rows=' + str(dst.execute('SELECT count(*) FROM turn_usage').fetchone()[0]))
    print('usage_snapshots_rows=' + str(dst.execute('SELECT count(*) FROM usage_snapshots').fetchone()[0]))
finally:
    dst.close()
    src.close()
