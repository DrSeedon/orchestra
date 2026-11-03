"""V-1213 integration: V-1206 streaming and single-copy retained snapshots."""
import asyncio
import errno
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import backend_hub as hub, hub_workspace as hw
from tests.test_hub_workspace import repo, _offline_hub_pool, _git, _turn, FakeSsh
from tests.test_hub_report_order_v1213 import worker
from tests.test_hub_uv import ShellSsh


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, 'STATE_DIR', tmp_path / 'state')
    root = tmp_path / 'root'
    root.mkdir()
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(root), 'synthetic')
    state.save()
    downloaded = tmp_path / 'out.tar'
    payload = b'synthetic return\n' * 20000
    downloaded.write_bytes(payload)
    out = state.path().with_suffix('.sync.tar')
    backend = hub.HubBackend('hub-gpt-6.1-sol', str(root))
    backend._watch_status = 'completed'
    return backend, state, downloaded, out, payload


def force_exdev(monkeypatch, downloaded=None, out=None):
    real_replace = hub.os.replace
    def replace(source, target):
        match = ((source == downloaded and target == out) if downloaded is not None else
                 Path(source).name == 'out.tar' and str(target).endswith('.sync.tar'))
        if match:
            raise OSError(errno.EXDEV, 'synthetic cross-filesystem rename')
        return real_replace(source, target)
    monkeypatch.setattr(hub.os, 'replace', replace)


def test_same_fs_retention_moves_inode_without_any_copy(snapshot, monkeypatch):
    backend, state, downloaded, out, payload = snapshot
    inode = downloaded.stat().st_ino
    def no_copy(*args, **kwargs):
        raise AssertionError('same-filesystem retention must not copy archive bytes')
    monkeypatch.setattr(hub.shutil, 'copyfile', no_copy)
    monkeypatch.setattr(hub.shutil, 'copyfileobj', no_copy)
    backend._retain_sync_snapshot(downloaded, out, state)
    assert out.stat().st_ino == inode
    assert out.read_bytes() == payload
    assert not downloaded.exists() and not out.with_suffix('.tmp').exists()
    assert hw.WorkspaceState.load(state.ws_id).pending_sync['phase'] == 'import'


def test_cross_fs_fallback_bounds_reads_and_removes_source(snapshot, monkeypatch):
    backend, state, downloaded, out, payload = snapshot
    force_exdev(monkeypatch, downloaded, out)
    real_copy = hub.shutil.copyfileobj
    reads = []
    class Reader:
        def __init__(self, handle):
            self.handle = handle
        def read(self, size=-1):
            assert 0 < size <= 65536
            reads.append(size)
            return self.handle.read(size)
    def bounded_copy(source, target, length):
        assert length == 65536
        return real_copy(Reader(source), target, length=length)
    monkeypatch.setattr(hub.shutil, 'copyfileobj', bounded_copy)
    backend._retain_sync_snapshot(downloaded, out, state)
    assert len(reads) > 2
    assert out.read_bytes() == payload
    assert not downloaded.exists() and not out.with_suffix('.tmp').exists()
    assert hw.WorkspaceState.load(state.ws_id).pending_sync['phase'] == 'import'


@pytest.mark.parametrize('failure', ['write', 'promote'])
def test_cross_fs_failure_cleans_partial_and_keeps_source(snapshot, monkeypatch, failure):
    backend, state, downloaded, out, payload = snapshot
    before = state.path().read_bytes()
    force_exdev(monkeypatch, downloaded, out)
    if failure == 'write':
        def fail(source, target, length):
            target.write(source.read(17))
            raise OSError(errno.ENOSPC, 'synthetic disk full')
        monkeypatch.setattr(hub.shutil, 'copyfileobj', fail)
    else:
        real_replace = hub.os.replace
        def fail(source, target):
            if source == out.with_suffix('.tmp'):
                raise OSError(errno.ENOSPC, 'synthetic rename refusal')
            return real_replace(source, target)
        monkeypatch.setattr(hub.os, 'replace', fail)
    with pytest.raises(OSError):
        backend._retain_sync_snapshot(downloaded, out, state)
    assert downloaded.read_bytes() == payload
    assert not out.exists() and not out.with_suffix('.tmp').exists()
    assert state.path().read_bytes() == before and state.pending_sync == {}


def test_other_rename_error_does_not_trigger_full_copy(snapshot, monkeypatch):
    backend, state, downloaded, out, payload = snapshot
    real_replace = hub.os.replace
    def fail(source, target):
        if source == downloaded:
            raise OSError(errno.EACCES, 'synthetic rename refusal')
        return real_replace(source, target)
    def no_copy(*args, **kwargs):
        raise AssertionError('copy fallback is allowed only for EXDEV')
    monkeypatch.setattr(hub.os, 'replace', fail)
    monkeypatch.setattr(hub.shutil, 'copyfileobj', no_copy)
    with pytest.raises(OSError, match='rename refusal'):
        backend._retain_sync_snapshot(downloaded, out, state)
    assert downloaded.read_bytes() == payload and not out.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('cross_fs', [False, True])
async def test_cancelled_retention_keeps_journal_before_import(
    repo, tmp_path, monkeypatch, cross_fs,
):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    if cross_fs:
        force_exdev(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    real_save = hw.WorkspaceState.save
    def save(state):
        real_save(state)
        if state.pending_sync.get('phase') == 'import':
            entered.set()
            assert release.wait(10), 'retention test latch timed out'
    monkeypatch.setattr(hw.WorkspaceState, 'save', save)
    before = _git(repo, 'rev-parse', 'HEAD')
    task = asyncio.create_task(_turn(backend, 'go'))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not parent.calls
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = hw.WorkspaceState.load(backend.session_id)
    assert state.pending_sync['phase'] == 'import'
    assert state.path().with_suffix('.sync.tar').is_file()
    assert not state.path().with_suffix('.sync.tmp').exists()
    assert _git(repo, 'rev-parse', 'HEAD') == before
    assert 'return a - b' in (repo / 'calc.py').read_text()
    monkeypatch.setattr(hw.WorkspaceState, 'save', real_save)
    ssh.get = AsyncMock(side_effect=AssertionError('retained journal must not redownload'))
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert len(parent.receipts) == 1
    assert 'return a + b' in parent.calls[0][3]
    assert not state.pending_sync


@pytest.mark.asyncio
async def test_crash_before_journal_save_discards_orphan_before_redownload(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real_save = hw.WorkspaceState.save
    def fail(state):
        if state.pending_sync.get('phase') == 'import':
            raise OSError('synthetic crash before journal save')
        real_save(state)
    monkeypatch.setattr(hw.WorkspaceState, 'save', fail)
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False and parent.calls == []
    state = hw.WorkspaceState.load(backend.session_id)
    assert not state.pending_sync
    retained = state.path().with_suffix('.sync.tar')
    assert retained.exists()
    assert 'return a - b' in (repo / 'calc.py').read_text()
    partial = retained.with_suffix('.tmp')
    partial.write_bytes(b'synthetic orphan from a process lost during EXDEV copy')
    monkeypatch.setattr(hw.WorkspaceState, 'save', real_save)
    real_get = ssh.get
    async def get(remote_dir, out, *, max_out):
        assert max_out is None
        assert not retained.exists(), 'orphan must not coexist with a new full download'
        assert not partial.exists(), 'partial cross-FS copy must be removed before download'
        await real_get(remote_dir, out, max_out=max_out)
    ssh.get = get
    await backend._sync_back(ssh, state, repo, tmp_path)
    assert len(parent.receipts) == 1 and not state.pending_sync


@pytest.mark.asyncio
async def test_sync_back_opts_out_of_transport_cap_and_does_not_copy_same_fs(repo, tmp_path, monkeypatch):
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real_get = ssh.get
    downloads = []
    async def get(remote_dir, out, *, max_out):
        assert max_out is None
        await real_get(remote_dir, out, max_out=max_out)
        downloads.append(out.stat().st_ino)
    ssh.get = get
    real_record = backend._record_sync
    def record(state, result, before):
        assert state.path().with_suffix('.sync.tar').stat().st_ino == downloads[-1]
        return real_record(state, result, before)
    backend._record_sync = record
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok']
    assert not any('transport limit' in event.content for event in events)
    assert len(parent.receipts) == 1


@pytest.mark.asyncio
async def test_streaming_none_cap_bounds_read_chunks(tmp_path, monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    sizes = []
    async def spawn(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        real_read = process.stdout.read
        async def read(size=-1):
            assert 0 < size <= 65536
            sizes.append(size)
            return await real_read(size)
        process.stdout.read = read
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    out = tmp_path / 'stream'
    await ShellSsh().run('head -c 524288 /dev/zero', stdout=out, max_out=None)
    assert out.stat().st_size == 524288 and len(sizes) >= 9


@pytest.mark.asyncio
@pytest.mark.parametrize('fake', [False, True])
async def test_get_explicit_cap_and_none_remain_distinct(tmp_path, fake):
    remote = tmp_path / 'hub-0123456789abcdef'
    remote.mkdir()
    (remote / 'output.bin').write_bytes(b'x' * 65536)
    ssh = FakeSsh(tmp_path) if fake else ShellSsh()
    out = tmp_path / 'archive.tar'
    with pytest.raises(hw.HubWorkspaceError, match='size limit'):
        await ssh.get(str(remote), out, max_out=1024)
    await ssh.get(str(remote), out, max_out=None)
    assert out.stat().st_size > 65536


@pytest.mark.asyncio
async def test_archive_over_old_transfer_cap_still_obeys_import_guards(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, 'MAX_TOTAL_BYTES', 64 * 1024)
    backend, ssh, mc, parent = worker(repo, tmp_path, monkeypatch)
    real_edit = mc.hub_edit
    def edit(root):
        real_edit(root)
        (root / 'oversize.bin').write_bytes(b'\0' * (256 * 1024))
    mc.hub_edit = edit
    shell = ShellSsh()
    async def get(remote_dir, out, *, max_out):
        assert max_out is None
        await shell.get(remote_dir, out, max_out=max_out)
        assert out.stat().st_size > hw.MAX_TOTAL_BYTES * 2
    ssh.get = get
    events = await _turn(backend, 'go')
    assert events[-1].metadata['ok'] is False
    assert 'return a + b' in _git(repo, 'show', 'HEAD:calc.py')
    assert not (repo / 'oversize.bin').exists()
    assert 'exceeds the size limit' in parent.calls[0][1]['message']
    assert not any('transport limit' in event.content for event in events)
