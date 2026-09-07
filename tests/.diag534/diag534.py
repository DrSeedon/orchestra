import time, pytest

def pytest_runtest_logstart(nodeid, location):
    print(f'\nSTART {time.monotonic():.3f} {nodeid}', flush=True)

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    yield
    for name in ('browser', 'dashboard_browser'):
        browser = item.funcargs.get(name)
        if browser:
            contexts = browser.contexts
            print(f'RESOURCES {name}: contexts={len(contexts)} pages={sum(len(c.pages) for c in contexts)}', flush=True)

import os, random, sqlite3, fcntl, termios, array, stat
_servers = []

def pytest_collection_modifyitems(items):
    order = os.environ.get('DIAG_ORDER', 'normal')
    if order == 'reverse':
        items.reverse()
    elif order == 'random':
        random.Random(534).shuffle(items)
    items *= int(os.environ.get('DIAG_REPEAT', '1'))
    for module in {item.module for item in items}:
        if not hasattr(module, '_start_dashboard_server'):
            continue
        original = module._start_dashboard_server
        def start(db_path, _original=original):
            proc, origin = _original(db_path)
            _servers.append((proc, db_path))
            if stat.S_ISFIFO(os.fstat(proc.stdout.fileno()).st_mode) and os.environ.get('DIAG_PIPE_SIZE'):
                fcntl.fcntl(proc.stdout, fcntl.F_SETPIPE_SZ, int(os.environ['DIAG_PIPE_SIZE']))
            if stat.S_ISFIFO(os.fstat(proc.stdout.fileno()).st_mode):
                print(f'PIPE_CAPACITY {fcntl.fcntl(proc.stdout, fcntl.F_GETPIPE_SZ)}', flush=True)
            return proc, origin
        module._start_dashboard_server = start

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    for proc, path in _servers:
        if proc.poll() is not None:
            continue
        pending = array.array('i', [0])
        if stat.S_ISFIFO(os.fstat(proc.stdout.fileno()).st_mode):
            fcntl.ioctl(proc.stdout, termios.FIONREAD, pending)
        else:
            pending[0] = os.fstat(proc.stdout.fileno()).st_size
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as conn:
            counts = {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        print(f'SERVER pid={proc.pid} pipe_bytes={pending[0]} db_bytes={path.stat().st_size} counts={counts}', flush=True)
