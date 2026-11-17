#!/usr/bin/env python3
"""Zero-setgid IPC spawner & tool-exec boundary for Antigravity under NoNewPrivileges=yes.

Modes (selected via --mode or argv[0] symlink basename):
  - spawner-daemon : runs as User=kesha, Group=agy_oauth (977), NoNewPrivileges=yes.
                     Listens on /run/orchestra-agy/spawner.sock (0600 kesha:kesha).
                     Asserts GID==agy_oauth, live killswitch marker, and proxy chain,
                     then executes /usr/local/libexec/agy-vendor.elf (0750 root:agy_oauth)
                     with caller's stdin/stdout/stderr passed via SCM_RIGHTS.
  - tool-daemon    : runs as User=kesha, Group=kesha (1001), NoNewPrivileges=yes.
                     Listens on /run/orchestra-agy/tool-exec.sock (0660 kesha:agy_oauth).
                     Scrubs residential proxy & daemon secret env vars, blocks OAuth CLI
                     targets, and executes worker tools/shells with exact argv & fds.
  - agy-client     : invoked as `agy.real` by `agy-wrapper.sh`.
  - tool-client    : invoked as `agy-clean-exec` by `agy-clean-shell`, `BASH_ENV`, or MCP.
"""
from __future__ import annotations

import array
import base64
import errno
import fcntl
import time
import grp
import ipaddress
import json
import os
import pwd
import signal
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

SPAWNER_SOCK = os.environ.get("ORCHESTRA_AGY_SPAWNER_SOCK", "/run/orchestra-agy/spawner.sock")
TOOL_EXEC_SOCK = os.environ.get("ORCHESTRA_AGY_TOOL_SOCK", "/run/orchestra-agy/tool-exec.sock")
KILLSWITCH_READY_PATH = Path(
    os.environ.get("ORCHESTRA_KILLSWITCH_READY_FILE", "/run/orchestra-oauth-killswitch.ready")
)
VENDOR_ELF = os.environ.get("ORCHESTRA_AGY_VENDOR_ELF", "/usr/local/libexec/agy-vendor.elf")

PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "GRPC_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "grpc_proxy",
)
NO_PROXY_VARS = ("NO_PROXY", "no_proxy", "NO_GRPC_PROXY", "no_grpc_proxy")
SAFE_LOCAL_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".lan",
    ".home.arpa",
    ".test",
    ".invalid",
)

# Minimal env allowlist passed into agy-vendor.elf
SPAWNER_ENV_EXACT_ALLOWLIST = frozenset({
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TZ",
    "TMPDIR",
    "TMP",
    "TEMP",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "GEMINI_CLI_HOME",
    "GEMINI_HOME",
    "BROWSER",
    "AGY_ACP_FORCE_FILE_STORAGE",
    "ANTIGRAVITY_CLI_HOME",
    "AGY_CLI_DISABLE_AUTO_UPDATE",
    "T3CODE_NO_BROWSER",
    "CI",
    "COLORTERM",
    "NO_COLOR",
    "ORCHESTRA_SESSION_ID",
    "ORCHESTRA_API_URL",
})

TOOL_STRIP_EXACT = frozenset({
    *PROXY_VARS,
    "NO_GRPC_PROXY",
    "no_grpc_proxy",
    "BASH_ENV",
    "ENV",
    "GEMINI_CLI_HOME",
    "ANTIGRAVITY_CLI_HOME",
    "ANTIGRAVITY_PROXY_URL",
    "CODEX_PROXY_URL",
    "CLAUDE_PROXY_URL",
    "GROK_PROXY_URL",
    "ORCHESTRA_RESIDENTIAL_PROXY_URL",
    "TELEGRAM_BOT_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ORCHESTRA_CLAUDE_CREDIT_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "ELEVENLABS_API_KEY",
})

FORBIDDEN_TOOL_BINARIES = frozenset({
    "agy",
    "agy.real",
    "agy-vendor.elf",
    "orchestra-agy-ipc.py",
    "orchestra_agy_ipc.py",
    "codex",
    "claude",
    "grok",
})


def _redact_proxy_url(url: str) -> str:
    try:
        p = urlparse(url)
        if p.hostname and p.port:
            return f"{p.scheme}://{p.hostname}:{p.port}"
    except Exception:
        pass
    return "<invalid-proxy-url>"


def sanitize_no_proxy_strict(raw: str) -> str:
    kept: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(","):
        tok = part.strip()
        if not tok or "*" in tok or "/" in tok:
            continue
        low = tok.lower()
        host = low
        if host.startswith("[") and "]" in host:
            host = host[1 : host.index("]")]
        elif ":" in host and host.count(":") == 1:
            host = host.split(":", 1)[0]
        if not host or host.startswith("."):
            continue
        ok = False
        if host in {"localhost", "127.0.0.1", "::1"}:
            ok = True
        else:
            try:
                ip = ipaddress.ip_address(host)
                ok = ip.is_loopback or ip.is_private
            except ValueError:
                ok = "." in host and any(host.endswith(suf) for suf in SAFE_LOCAL_SUFFIXES)
        if ok and low not in seen:
            kept.append(tok)
            seen.add(low)
    for req in ("localhost", "127.0.0.1", "::1", "[::1]"):
        if req not in seen:
            kept.append(req)
            seen.add(req)
    return ",".join(kept)


def _is_offline_agy_args(argv: list[str]) -> bool:
    args = argv[1:]
    if not args:
        return False
    if args[0] in {"--version", "-v", "-V", "--help", "-h", "agents"}:
        return True
    if len(args) >= 3 and args[0] == "--output-format" and args[2] in {"agents", "--version", "--help"}:
        return True
    return False


def _verify_proxy_chain(proxy_url: str) -> None:
    p = urlparse(proxy_url)
    if p.scheme.lower() not in {"http", "https", "socks5", "socks5h"} or not p.hostname or not p.port:
        raise RuntimeError(f"invalid proxy URL {_redact_proxy_url(proxy_url)}")
    try:
        with socket.create_connection((p.hostname, p.port), timeout=1.5):
            pass
    except OSError as exc:
        raise RuntimeError(f"proxy {p.hostname}:{p.port} unreachable ({exc})") from exc
    upstream_port = int(os.environ.get("ORCHESTRA_UPSTREAM_PROXY_PORT", "10809"))
    if p.hostname in {"127.0.0.1", "localhost", "::1"} and p.port == 18080 and upstream_port > 0:
        try:
            with socket.create_connection(("127.0.0.1", upstream_port), timeout=1.5):
                pass
        except OSError as exc:
            raise RuntimeError(f"upstream xray 127.0.0.1:{upstream_port} unreachable ({exc})") from exc


IPC_REQUEST_TIMEOUT = 5.0
IPC_MAX_CONNECTIONS = 64


def _recv_request_with_fds(conn: socket.socket) -> tuple[dict, list[int]]:
    """Own received rights until validation transfers them to the handler."""
    hdr_buf = bytearray()
    fds: list[int] = []
    max_fds = 4
    cmsg_space = socket.CMSG_SPACE(max_fds * array.array("i").itemsize)
    deadline = time.monotonic() + IPC_REQUEST_TIMEOUT
    previous_timeout = conn.gettimeout()
    try:
        while len(hdr_buf) < 4:
            conn.settimeout(max(0.001, deadline-time.monotonic()))
            chunk, ancdata, flags, _addr = conn.recvmsg(4-len(hdr_buf), cmsg_space)
            # Collect descriptors before ANY validation, including truncation.
            for level, kind, data in ancdata:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    arr = array.array("i")
                    arr.frombytes(data[:len(data)-(len(data)%arr.itemsize)])
                    fds.extend(arr)
            if flags & socket.MSG_CTRUNC or len(fds) > 3:
                raise ValueError("truncated/excess IPC file descriptors")
            if not chunk:
                raise EOFError("empty IPC request header")
            hdr_buf.extend(chunk)
        (length,) = struct.unpack("!I", hdr_buf)
        if not 0 < length <= 2*1024*1024:
            raise ValueError("invalid IPC payload size")
        body = bytearray()
        while len(body) < length:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("IPC request deadline exceeded")
            conn.settimeout(remaining)
            chunk = conn.recv(min(65536,length-len(body)))
            if not chunk:
                raise EOFError("truncated IPC request payload")
            body.extend(chunk)
        request = json.loads(body.decode("utf-8"))
        if not isinstance(request,dict) or len(fds) != 3:
            raise ValueError("invalid IPC request/stdio descriptors")
        return request,fds
    except BaseException:
        for fd in fds:
            os.close(fd)
        raise
    finally:
        conn.settimeout(previous_timeout)


def _send_response(conn: socket.socket, obj: dict) -> None:
    raw = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack("!I", len(raw)) + raw)


def _recv_response(conn: socket.socket) -> dict:
    hdr = bytearray()
    while len(hdr) < 4:
        chunk = conn.recv(4 - len(hdr))
        if not chunk:
            raise EOFError("IPC daemon closed connection before exit status")
        hdr.extend(chunk)
    (n,) = struct.unpack("!I", bytes(hdr))
    body = bytearray()
    while len(body) < n:
        chunk = conn.recv(min(65536, n - len(body)))
        if not chunk:
            raise EOFError("truncated IPC response")
        body.extend(chunk)
    return json.loads(body.decode("utf-8"))


def _verify_peer_uid(conn: socket.socket, allowed_uids: set[int]) -> None:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    if uid not in allowed_uids:
        raise PermissionError(f"unauthorized peer uid {uid}")


def _kill_pgrp(pid: int) -> None:
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(15):
        try:
            os.killpg(pgid, 0)
        except OSError:
            return
        threading.Event().wait(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _handle_spawner_conn(conn: socket.socket, kesha_uid: int, agy_gid: int) -> None:
    fds: list[int] = []
    proc: subprocess.Popen | None = None
    writer_fd = None
    try:
        _verify_peer_uid(conn, {0, kesha_uid})
        req, fds = _recv_request_with_fds(conn)
        if len(fds) != 3:
            raise ValueError(f"expected 3 stdio fds, got {len(fds)}")

        # Hard runtime kernel credential & killswitch verification on EVERY spawn
        if os.getgid() != agy_gid or os.getegid() != agy_gid:
            raise RuntimeError(
                f"spawner GID mismatch: gid={os.getgid()} egid={os.getegid()} expected={agy_gid}"
            )
        if not KILLSWITCH_READY_PATH.is_file():
            raise RuntimeError(f"killswitch ready file missing: {KILLSWITCH_READY_PATH}")
        ks_meta = json.loads(KILLSWITCH_READY_PATH.read_text(encoding="utf-8"))
        if int(ks_meta.get("agy_gid", -1)) != agy_gid:
            raise RuntimeError("killswitch ready file agy_gid mismatch")

        argv = [str(a) for a in (req.get("argv") or [])]
        if not argv:
            argv = [VENDOR_ELF]
        else:
            argv[0] = VENDOR_ELF
        cwd = str(req.get("cwd") or "/tmp")
        if not os.path.isdir(cwd):
            cwd = "/tmp"

        caller_env = req.get("env") if isinstance(req.get("env"), dict) else {}
        is_offline = _is_offline_agy_args(argv)
        allow_dc = str(caller_env.get("ALLOW_DATACENTER_OAUTH_EGRESS") or "") == "1"

        disabled_file = Path(
            str(caller_env.get("ORCHESTRA_DISABLED_PROVIDERS_FILE") or "/home/kesha/orchestra/data/disabled_providers.json")
        )
        if not is_offline and str(caller_env.get("AGY_ALLOW_WHEN_DISABLED") or "") != "1" and disabled_file.is_file():
            try:
                d = json.loads(disabled_file.read_text(encoding="utf-8"))
                items = d.get("disabled_providers", []) if isinstance(d, dict) else d
                if "antigravity" in items:
                    _send_response(conn, {"ok": False, "rc": 77, "error": "antigravity is disabled"})
                    return
            except Exception:
                _send_response(conn, {"ok": False, "rc": 77, "error": "failed reading disabled_providers.json"})
                return

        proxy_url = str(
            caller_env.get("ANTIGRAVITY_PROXY_URL")
            or caller_env.get("HTTPS_PROXY")
            or caller_env.get("ORCHESTRA_RESIDENTIAL_PROXY_URL")
            or "http://127.0.0.1:18080"
        ).strip()

        if not allow_dc:
            _verify_proxy_chain(proxy_url)

        clean_env: dict[str, str] = {
            "PATH": "/home/kesha/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "AGY_CLI_DISABLE_AUTO_UPDATE": "true",
            "SHELL": "/home/kesha/.local/bin/agy-clean-shell",
            "BASH_ENV": "/home/kesha/.local/share/orchestra/agy-bash-clean-env.sh",
        }
        for k, v in caller_env.items():
            ks = str(k)
            if ks in SPAWNER_ENV_EXACT_ALLOWLIST:
                clean_env[ks] = str(v)

        safe_np = sanitize_no_proxy_strict(str(caller_env.get("NO_PROXY") or caller_env.get("no_proxy") or ""))
        if not allow_dc:
            for pv in PROXY_VARS:
                clean_env[pv] = proxy_url
        for npv in NO_PROXY_VARS:
            clean_env[npv] = safe_np

        if not is_offline:
            gemini = Path(clean_env.get("GEMINI_HOME") or Path(clean_env["HOME"]) / ".gemini")
            if "--gemini-dir" in argv:
                gemini = Path(argv[argv.index("--gemini-dir")+1])
            writer_fd = os.open(gemini.resolve() / ".orchestra-vendor-writer.lock",
                                os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
            # Never queue account processes or replay failed requests.
            fcntl.flock(writer_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        proc = subprocess.Popen(
            argv,
            executable=VENDOR_ELF,
            cwd=cwd,
            env=clean_env,
            stdin=fds[0],
            stdout=fds[1],
            stderr=fds[2],
            close_fds=True,
            start_new_session=True,
        )
        for fd in fds:
            os.close(fd)
        fds = []

        done_ev = threading.Event()

        def _watch_disconnect() -> None:
            while not done_ev.is_set():
                try:
                    conn.settimeout(0.5)
                    data = conn.recv(16)
                    if data == b"":
                        _kill_pgrp(proc.pid)
                        return
                except TimeoutError:
                    continue
                except OSError:
                    _kill_pgrp(proc.pid)
                    return

        watcher = threading.Thread(target=_watch_disconnect, daemon=True)
        watcher.start()
        rc = proc.wait()
        done_ev.set()
        conn.settimeout(2.0)
        try:
            _send_response(conn, {"ok": True, "rc": int(rc)})
        except OSError:
            pass
    except Exception as exc:
        try:
            _send_response(conn, {"ok": False, "rc": 78, "error": f"orchestra-agy-spawner: {exc}"})
        except OSError:
            pass
    finally:
        if writer_fd is not None:
            os.close(writer_fd)
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            conn.close()
        except OSError:
            pass


def _handle_tool_conn(conn: socket.socket, kesha_uid: int, kesha_gid: int) -> None:
    fds: list[int] = []
    proc: subprocess.Popen | None = None
    try:
        _verify_peer_uid(conn, {0, kesha_uid})
        req, fds = _recv_request_with_fds(conn)
        if len(fds) != 3:
            raise ValueError(f"expected 3 stdio fds, got {len(fds)}")
        if os.getgid() != kesha_gid or os.getegid() != kesha_gid:
            raise RuntimeError(f"tool-daemon GID mismatch: gid={os.getgid()} expected={kesha_gid}")

        argv = [str(a) for a in (req.get("argv") or [])]
        if not argv or not argv[0]:
            raise ValueError("empty argv in tool-exec")
        base_bin = os.path.basename(argv[0])
        if base_bin in FORBIDDEN_TOOL_BINARIES:
            raise PermissionError(f"refusing to execute provider binary {base_bin!r} via tool-exec")

        cwd = str(req.get("cwd") or "/tmp")
        if not os.path.isdir(cwd):
            cwd = "/tmp"

        caller_env = req.get("env") if isinstance(req.get("env"), dict) else {}
        clean_env: dict[str, str] = {}
        for k, v in caller_env.items():
            ks = str(k)
            if ks in TOOL_STRIP_EXACT:
                continue
            clean_env[ks] = str(v)
        clean_env["_ORCH_TOOL_EXEC_DONE"] = "1"
        clean_env["SHELL"] = "/bin/bash"

        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=clean_env,
            stdin=fds[0],
            stdout=fds[1],
            stderr=fds[2],
            close_fds=True,
            start_new_session=True,
        )
        for fd in fds:
            os.close(fd)
        fds = []

        done_ev = threading.Event()

        def _watch_disconnect() -> None:
            while not done_ev.is_set():
                try:
                    conn.settimeout(0.5)
                    data = conn.recv(16)
                    if data == b"":
                        _kill_pgrp(proc.pid)
                        return
                except TimeoutError:
                    continue
                except OSError:
                    _kill_pgrp(proc.pid)
                    return

        watcher = threading.Thread(target=_watch_disconnect, daemon=True)
        watcher.start()
        rc = proc.wait()
        done_ev.set()
        conn.settimeout(2.0)
        try:
            _send_response(conn, {"ok": True, "rc": int(rc)})
        except OSError:
            pass
    except Exception as exc:
        try:
            _send_response(conn, {"ok": False, "rc": 126, "error": f"orchestra-agy-tool-exec: {exc}"})
        except OSError:
            pass
    finally:
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            conn.close()
        except OSError:
            pass


def _serve_unix_daemon(default_sock_path: str, handler, *handler_args) -> int:
    listen_fds = int(os.environ.get("LISTEN_FDS", "0") or "0")
    if listen_fds >= 1:
        srv = socket.socket(fileno=3)
    else:
        p = Path(default_sock_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(p))
        srv.listen(64)
    srv.setblocking(True)
    capacity = threading.BoundedSemaphore(IPC_MAX_CONNECTIONS)
    def serve(conn):
        try:
            handler(conn, *handler_args)
        finally:
            capacity.release()
    while True:
        conn, _ = srv.accept()
        if not capacity.acquire(blocking=False):
            conn.close()  # bounded refusal before accepting any descriptors
            continue
        try:
            threading.Thread(target=serve, args=(conn,), daemon=True).start()
        except BaseException:
            conn.close()
            capacity.release()
            raise


def _ipc_client_exec(sock_path: str, argv: list[str], env: dict[str, str]) -> int:
    payload = json.dumps({
        "cwd": os.getcwd(),
        "argv": argv,
        "env": env,
    }).encode("utf-8")
    hdr = struct.pack("!I", len(payload))
    fds = array.array("i", [0, 1, 2])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(sock_path)
        s.sendmsg([hdr], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds)])
        s.sendall(payload)

        def _forward_sig(_signum, _frame):
            try:
                s.close()
            except OSError:
                pass
            raise SystemExit(130)

        signal.signal(signal.SIGTERM, _forward_sig)
        signal.signal(signal.SIGINT, _forward_sig)
        signal.signal(signal.SIGHUP, _forward_sig)
        resp = _recv_response(s)
        if not resp.get("ok"):
            err = resp.get("error") or "IPC execution failed"
            sys.stderr.write(f"{err}\n")
        return int(resp.get("rc", 1))


def main() -> int:
    prog = os.path.basename(sys.argv[0])
    args = sys.argv[1:]

    if prog == "agy.real":
        return _ipc_client_exec(SPAWNER_SOCK, [VENDOR_ELF, *args], dict(os.environ))

    if prog == "agy-clean-exec":
        if len(args) >= 2 and args[0] == "--cmdline-b64":
            raw_cmd = base64.b64decode(args[1]).rstrip(b"\x00")
            target_argv = [p.decode("utf-8", errors="surrogateescape") for p in raw_cmd.split(b"\x00")]
        else:
            target_argv = args
        if not target_argv:
            sys.stderr.write("agy-clean-exec: missing target command\n")
            return 2
        clean_env = {k: v for k, v in os.environ.items() if k not in TOOL_STRIP_EXACT}
        clean_env["_ORCH_TOOL_EXEC_DONE"] = "1"
        clean_env["SHELL"] = "/bin/bash"
        kesha_gid = pwd.getpwnam("kesha").pw_gid
        if os.getgid() == kesha_gid and os.getegid() == kesha_gid:
            os.execvpe(target_argv[0], target_argv, clean_env)
        return _ipc_client_exec(TOOL_EXEC_SOCK, target_argv, clean_env)

    if len(args) >= 2 and args[0] == "--mode":
        mode = args[1]
        kesha_pw = pwd.getpwnam("kesha")
        if mode == "spawner-daemon":
            agy_gid = grp.getgrnam("agy_oauth").gr_gid
            return _serve_unix_daemon(SPAWNER_SOCK, _handle_spawner_conn, kesha_pw.pw_uid, agy_gid)
        if mode == "tool-daemon":
            return _serve_unix_daemon(TOOL_EXEC_SOCK, _handle_tool_conn, kesha_pw.pw_uid, kesha_pw.pw_gid)

    sys.stderr.write(f"orchestra_agy_ipc: unknown invocation prog={prog!r} args={args!r}\n")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(141)
