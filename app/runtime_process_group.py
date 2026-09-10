"""Runtime cgroups nested beneath the supervisor, never separate systemd units.

The launcher joins before exec, so detached descendants stay in the service.
"""
import asyncio
import os
from pathlib import Path
import sys
import uuid


class RuntimeProcessGroup:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def create(cls) -> tuple['RuntimeProcessGroup | None', str]:
        path = None
        try:
            row = next(line for line in Path('/proc/self/cgroup').read_text().splitlines()
                       if line.startswith('0::'))
            parent = Path('/sys/fs/cgroup') / row[3:].lstrip('/')
            path = parent / f'runtime-{uuid.uuid4().hex}'
            path.mkdir()
            # Only process ownership is delegated; we do not enable controllers.
            for name in ('cgroup.procs', 'cgroup.kill'):
                fd = os.open(path / name, os.O_WRONLY | os.O_CLOEXEC)
                os.close(fd)
            return cls(path), ''
        except (OSError, StopIteration) as error:
            if path is not None and path.exists():
                path.rmdir()
            return None, f'Delegated cgroup v2 required for hibernation: {error}'

    def command(self, command: list[str]) -> list[str]:
        return [sys.executable, str(Path(__file__).resolve()), str(self.path), *command]

    def populated(self) -> bool:
        events = dict(line.split() for line in (self.path / 'cgroup.events').read_text().splitlines())
        return events['populated'] == '1'

    def kill(self) -> None:
        # Includes nested groups, concurrent forks and setsid descendants.
        (self.path / 'cgroup.kill').write_text('1')

    async def stop(self, proc: asyncio.subprocess.Process | None, timeout: float) -> None:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(timeout):
                while (proc is not None and proc.returncode is None) or self.populated():
                    await asyncio.sleep(0.05)
        except TimeoutError:
            # Also stop a launcher that has not joined the group yet.
            if proc is not None and proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            self.kill()
            async with asyncio.timeout(timeout):
                while (proc is not None and proc.returncode is None) or self.populated():
                    await asyncio.sleep(0.05)
        if proc is not None:
            await asyncio.wait_for(proc.wait(), timeout)
        # A failed stop retains its owner for retry. Remove only empty owned groups.
        for child in sorted(self.path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if child.is_dir():
                child.rmdir()
        self.path.rmdir()


if __name__ == '__main__':
    group = Path(sys.argv[1])
    (group / 'cgroup.procs').write_text(str(os.getpid()))
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
