"""Fail-closed provider boundary. This module never changes host configuration."""
import asyncio
import ctypes as C
import errno
import os
from pathlib import Path
import shutil
import subprocess
import sys

VENDOR_BWRAP = '/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/codex-resources/bwrap'
PROVIDER_HOSTS = frozenset({'chatgpt.com', 'api.openai.com', 'auth.openai.com', 'api.anthropic.com', 'platform.claude.com'})


def bwrap_path():
    found = shutil.which('bwrap')
    return found or (VENDOR_BWRAP if Path(VENDOR_BWRAP).is_file() else None)


def mounts(binary, workspace, *, readonly=False, runtime_paths=(), home=None):
    args = [binary, '--die-with-parent', '--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/home', '--dir', '/home/bench', '--dir', '/etc']
    for path in ['/usr', '/bin', '/lib', '/lib64', '/etc/ssl', '/etc/ld.so.cache', '/etc/hosts', '/etc/resolv.conf', '/etc/nsswitch.conf', '/etc/passwd', '/etc/group', '/etc/bash.bashrc', *runtime_paths]:
        if Path(path).exists():
            args += ['--ro-bind', path, path]
    if home:
        args += ['--bind', str(home), '/home/bench']
    args += ['--ro-bind' if readonly else '--bind', str(workspace), '/work', '--chdir', '/work']
    return args


def preflight(runtime_paths=()):
    import tempfile
    binary = bwrap_path()
    if not binary:
        raise RuntimeError('приватный /tmp недоступен: bubblewrap не найден (PATH и vendor path проверены)')
    with tempfile.TemporaryDirectory(prefix='local-bench-probe-') as folder:
        r = subprocess.run(mounts(binary, folder, runtime_paths=runtime_paths) + ['/bin/sh', '-c', 'printf probe >/tmp/probe; test -r /proc/self/status; test -f /tmp/probe'], capture_output=True, text=True, timeout=15)
    if r.returncode:
        detail = r.stderr.strip()
        if any(word in detail.lower() for word in ('uid map', 'user namespace', 'operation not permitted', 'permission denied')):
            setting = Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns')
            value = setting.read_text().strip() if setting.exists() else 'unknown'
            raise RuntimeError('приватный /tmp недоступен: запрещены непривилегированные user namespaces '
                               f'(kernel.apparmor_restrict_unprivileged_userns={value}). '
                               'Снятие защиты — решение владельца; используйте offline fixture-режим '
                               'или другую машину с разрешёнными namespaces. Детали: ' + detail)
        raise RuntimeError('приватный /tmp недоступен: ' + detail)
    # Network restriction must be available too, before any provider is contacted.
    libc = C.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 4:
        raise RuntimeError('provider-сеть недоступна: требуется Landlock ABI >=4')
    try:
        C.CDLL('libseccomp.so.2')
    except OSError as error:
        raise RuntimeError('provider-сеть недоступна: требуется libseccomp.so.2') from error
    with tempfile.TemporaryDirectory(prefix='local-bench-net-probe-') as folder:
        command = mounts(binary, folder, runtime_paths=runtime_paths)
        child_probe = "import os; os.listdir('/proc/self/fd')"
        probe = ("import socket,subprocess,sys; "
                 "s=socket.socket(); assert s.connect_ex(('127.0.0.1',1)) in (1,13); "
                 f"subprocess.run([sys.executable,'-c',{child_probe!r}],check=True)")
        command += ['--ro-bind', str(Path(__file__).resolve()), '/bench-network.py',
                    '/usr/bin/python3', '/bench-network.py', '0', '/usr/bin/python3', '-c', probe]
        checked = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if checked.returncode:
            raise RuntimeError('provider sandbox preflight failed before model launch: ' + checked.stderr.strip())
    return {'bwrap': binary, 'landlock_abi': abi, 'private_tmp': True, 'network_filter': True, 'child_proc': True}


class Relay:
    def __init__(self):
        self.events = []
        self.connections = set()

    async def start(self):
        self.server = await asyncio.start_server(self.client, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def client(self, reader, writer):
        task = asyncio.current_task()
        self.connections.add(task)
        peer = None
        pumps = []
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            parts = header.split(b'\r\n', 1)[0].decode('ascii').split()
            target = parts[1] if len(parts) == 3 else ''
            host, _, port = target.rpartition(':')
            allowed = len(parts) == 3 and parts[0] == 'CONNECT' and host in PROVIDER_HOSTS and port == '443'
            self.events.append({'target': target, 'allowed': allowed})
            if not allowed:
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                await writer.drain()
                return
            upstream, peer = await asyncio.open_connection(host, 443)
            writer.write(b'HTTP/1.1 200 Connection established\r\n\r\n')
            await writer.drain()
            async def pump(src, dst):
                while data := await src.read(65536):
                    dst.write(data)
                    await dst.drain()
            pumps = [asyncio.create_task(pump(reader, peer)), asyncio.create_task(pump(upstream, writer))]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except (OSError, ValueError, UnicodeError, asyncio.TimeoutError, asyncio.IncompleteReadError) as error:
            self.events.append({'error': type(error).__name__})
        finally:
            for pending in pumps:
                pending.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            writer.close()
            if peer:
                peer.close()
            self.connections.discard(task)

    async def close(self):
        self.server.close()
        await self.server.wait_closed()
        for task in list(self.connections):
            task.cancel()
        await asyncio.gather(*list(self.connections), return_exceptions=True)


def restrict_network(port):
    """Called inside bwrap: /proc and /tmp already belong to this PID/mount namespace."""
    class Ruleset(C.Structure):
        _fields_ = [('fs', C.c_uint64), ('net', C.c_uint64)]
    class Net(C.Structure):
        _fields_ = [('access', C.c_uint64), ('port', C.c_uint64)]
    libc = C.CDLL(None, use_errno=True)
    def check(result):
        if result < 0:
            raise OSError(C.get_errno(), os.strerror(C.get_errno()))
        return result
    rule = Ruleset(0, 3)
    fd = check(libc.syscall(444, C.byref(rule), C.sizeof(rule), 0))
    try:
        if port:
            net = Net(2, port)
            check(libc.syscall(445, fd, 2, C.byref(net), 0))
        check(libc.prctl(38, 1, 0, 0, 0))
        check(libc.syscall(446, fd, 0))
    finally:
        os.close(fd)
    # No host Unix socket connection, including abstract AF_UNIX names on shared netns.
    sec = C.CDLL('libseccomp.so.2')
    class Arg(C.Structure):
        _fields_ = [('arg', C.c_uint), ('op', C.c_int), ('a', C.c_uint64), ('b', C.c_uint64)]
    sec.seccomp_init.argtypes = [C.c_uint32]
    sec.seccomp_init.restype = C.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes = [C.c_char_p]
    sec.seccomp_rule_add_array.argtypes = [C.c_void_p, C.c_uint32, C.c_int, C.c_uint, C.POINTER(Arg)]
    sec.seccomp_load.argtypes = [C.c_void_p]
    sec.seccomp_release.argtypes = [C.c_void_p]
    ctx = sec.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('seccomp_init failed')
    try:
        arg = Arg(0, 4, 1, 0)
        nr = sec.seccomp_syscall_resolve_name(b'socket')
        if sec.seccomp_rule_add_array(ctx, 0x50000 | errno.EPERM, nr, 1, C.byref(arg)):
            raise RuntimeError('seccomp Unix socket restriction failed')
        udp = Arg(1, 7, 15, 2)  # masked SOCK_DGRAM, including NONBLOCK/CLOEXEC flags
        if sec.seccomp_rule_add_array(ctx, 0x50000 | errno.EPERM, nr, 1, C.byref(udp)) or sec.seccomp_load(ctx):
            raise RuntimeError('seccomp network isolation failed')
    finally:
        sec.seccomp_release(ctx)


if __name__ == '__main__':
    restrict_network(int(sys.argv[1]))
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
