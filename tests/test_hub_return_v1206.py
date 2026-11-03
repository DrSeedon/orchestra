"""Offline unlimited return transport; independent import/upload boundaries remain."""

import asyncio
import io
import tarfile
import tracemalloc
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import hub_workspace as hw
from tests.test_hub_uv import ShellSsh
from tests.test_hub_workspace import repo


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [600 * 1024**2 - 1, 600 * 1024**2, 600 * 1024**2 + 1])
async def test_get_crosses_former_600_mib_boundary_in_bounded_chunks(tmp_path, monkeypatch, size):
    # Virtual pipes and a counting destination: exercise the real get/run path
    # without allocating or writing a 600 MiB payload (or invoking SSH).
    class Pipe:
        def __init__(self, remaining):
            self.remaining = remaining
            self.largest_read = 0
            self.block = b"x" * 65536

        async def read(self, amount=-1):
            assert 0 < amount <= 65536, "transport must never read an entire pipe"
            self.largest_read = max(self.largest_read, amount)
            count = min(self.remaining, amount)
            self.remaining -= count
            return self.block[:count]

    class Sink(io.RawIOBase):
        received = 0

        def write(self, data):
            assert len(data) <= 65536
            self.received += len(data)
            return len(data)

    sink = Sink()
    out = tmp_path / "out.tar"
    real_open = Path.open

    def open_file(path, *args, **kwargs):
        return sink if path == out else real_open(path, *args, **kwargs)

    proc = SimpleNamespace(stdout=Pipe(size), stderr=Pipe(2 * 1024**2), returncode=0,
                           wait=AsyncMock(return_value=0),
                           communicate=AsyncMock(side_effect=AssertionError("buffered communication")))
    spawn = AsyncMock(return_value=proc)
    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await hw.HubSsh("unused", "unused", "").get(
        "/synthetic/hub-0123456789abcdef", out, max_out=None)
    assert sink.received == size and sink.closed
    assert proc.stdout.remaining == proc.stderr.remaining == 0
    assert proc.stdout.largest_read == proc.stderr.largest_read == 65536
    proc.communicate.assert_not_called()
    assert spawn.await_count == 1


@pytest.mark.asyncio
async def test_other_workspace_snapshots_keep_the_default_output_cap(tmp_path, monkeypatch):
    run = AsyncMock(return_value=b"")
    monkeypatch.setattr(hw.HubSsh, "run", run)
    await hw.HubSsh("unused", "unused", "").get(
        "/synthetic/hub-0123456789abcdef", tmp_path / "snapshot.tar")
    assert run.await_args.kwargs["max_out"] == hw.MAX_TOTAL_BYTES * 2


@pytest.mark.asyncio
async def test_unlimited_in_memory_reply_is_refused_before_process_start(monkeypatch):
    spawn = AsyncMock(side_effect=AssertionError("must not start"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ValueError, match="destination file"):
        await hw.HubSsh("unused", "unused", "").run("unused", max_out=None)
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_large_stderr_retains_final_diagnostic_with_unlimited_return(tmp_path):
    with pytest.raises(hw.HubWorkspaceError, match="synthetic final diagnostic"):
        await ShellSsh().run(
            "head -c 1048576 /dev/zero >&2; printf '\\nsynthetic final diagnostic\\n' >&2; exit 23",
            stdout=tmp_path / "partial.tar", max_out=None)


def test_many_changed_payloads_do_not_accumulate_in_memory(repo, tmp_path):
    archive_path = tmp_path / "changes.tar"
    block = b"\0" * (128 * 1024)
    with tarfile.open(archive_path, "w") as archive:
        for index in range(64):
            member = tarfile.TarInfo(f"results/{index}.bin")
            member.size = len(block)
            member.mode = 0o755 if index == 0 else 0o644
            archive.addfile(member, io.BytesIO(block))
    # 8 MiB of accepted changes: the old pending-bytes list exceeds this budget.
    tracemalloc.start()
    try:
        result = hw.apply_changes(archive_path, repo, {}, known=[])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(result.changed) == 64 and not result.rejected
    assert peak < 2 * 1024**2, f"payload accumulation: {peak} traced bytes"
    assert all((repo / rel).stat().st_size == len(block) for rel in result.changed)
    assert (repo / "results/0.bin").stat().st_mode & 0o777 == 0o755
    assert (repo / "results/1.bin").stat().st_mode & 0o777 == 0o644


def test_return_file_and_total_import_limits_remain_independent(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "MAX_FILE_BYTES", 16)
    monkeypatch.setattr(hw, "MAX_TOTAL_BYTES", 24)
    archive_path = tmp_path / "changes.tar"
    with tarfile.open(archive_path, "w") as archive:
        for name, count in [("too-big", 17), ("accepted", 16), ("over-total", 9), ("exact-total", 8)]:
            member = tarfile.TarInfo(name)
            member.size = count
            archive.addfile(member, io.BytesIO(b"x" * count))
    result = hw.apply_changes(archive_path, repo, {}, known=[])
    assert result.changed == ["accepted", "exact-total"]
    assert result.rejected == [("too-big", "exceeds the size limit"), ("over-total", "exceeds the size limit")]
    assert not (repo / "too-big").exists() and not (repo / "over-total").exists()


def test_upload_total_file_and_count_caps_still_refuse(repo):
    for options in (hw.ProjectOptions(max_total_bytes=1),
                    hw.ProjectOptions(max_files=1)):
        with pytest.raises(hw.HubWorkspaceError, match="too large"):
            hw.plan_upload(repo, known=[], options=options)
    plan = hw.plan_upload(repo, known=[], options=hw.ProjectOptions(max_file_bytes=1))
    assert not plan.manifest
    assert dict(plan.skipped) == {"calc.py": "larger than the per-file limit",
                                  "src/keep.txt": "larger than the per-file limit"}


def test_header_scan_does_not_cache_all_members(tmp_path):
    path = tmp_path / "headers.tar"
    with tarfile.open(path, "w") as archive:
        for index in range(1000):
            archive.addfile(tarfile.TarInfo(f"{index}"))
    count = 0
    with tarfile.open(path, "r:") as archive:
        for member in hw._snapshot_members(archive):
            assert member.name == str(count)
            assert not archive.members
            count += 1
    assert count == 1000


def test_archive_payload_replaced_after_validation_is_not_applied(repo, tmp_path, monkeypatch):
    path = tmp_path / "changes.tar"
    with tarfile.open(path, "w") as archive:
        member = tarfile.TarInfo("calc.py")
        member.size = 3
        archive.addfile(member, io.BytesIO(b"new"))
    original = (repo / "calc.py").read_bytes()
    real_open = tarfile.open
    reads = 0

    def replace_before_apply(name, mode="r", *args, **kwargs):
        nonlocal reads
        if name == path and mode == "r:":
            reads += 1
            if reads == 3:  # header scan, payload validation, then application
                with path.open("r+b") as handle:
                    handle.seek(512)
                    handle.write(b"bad")
        return real_open(name, mode, *args, **kwargs)

    monkeypatch.setattr(tarfile, "open", replace_before_apply)
    with pytest.raises(hw.HubWorkspaceError, match="changed during import"):
        hw.apply_changes(path, repo, hw.plan_upload(repo, known=[]).manifest, known=[])
    assert (repo / "calc.py").read_bytes() == original
    assert (repo / "src/keep.txt").exists()
    assert not list(repo.glob(".*.hub-*"))
