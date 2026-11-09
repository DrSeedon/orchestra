"""Explicit operator probe/import. Secret bytes pass only captured pipes and SSH stdin.

Runs existing authorized cookie reader in RAM on the owner's laptop, then imports
exactly three distinct AVAILABLE accounts directly to VPS SSH stdin. No secret stdout.
"""
import json
import os
from pathlib import Path
import resource
import subprocess

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent

INIT_PROGRAM = r'''
import asyncio, importlib, json, re, sys
incoming = json.load(sys.stdin)
namespace = {"__name__": "pool_worker"}
exec(incoming["worker_source"], namespace)
identity = {}
namespace["disable_cookie_files"](identity, "discovery@invalid.example", incoming["index"])
access = importlib.import_module("gemini_webapi.utils.get_access_token")
# Discovery is init-only: capture the principal, never generate before validation.
# The worker's wrapper checks a fixed owner, so use the original vendor parser here.
def capture(response):
    match = re.search(r'"oPEP7c"\s*:\s*("(?:\\.|[^"\\])*")', response.text)
    email = json.loads(match.group(1)) if match else ""
    if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[A-Za-z]{2,}", email):
        raise RuntimeError("principal missing")
    identity["email"] = email.lower()
    # Call the unwrapped vendor parser captured in checked_payload's closure.
    return vendor_extract(response)
vendor_extract = dict(zip(access._extract_payload.__code__.co_freevars,
                          (c.cell_contents for c in access._extract_payload.__closure__)))["original"]
access._extract_payload = capture
from gemini_webapi import GeminiClient
async def run():
    cookies = incoming["cookies"]
    client = GeminiClient(cookies["__Secure-1PSID"], cookies["__Secure-1PSIDTS"], proxy=incoming["proxy"])
    try:
        await asyncio.wait_for(client.init(timeout=25, auto_refresh=False, auto_close=False, verbose=False), 45)
        return {"email": identity["email"], "account_status": client.account_status.name,
                "models": [{"name": m.model_name, "available": m.is_available} for m in (client.list_models() or [])]}
    finally:
        await client.close()
try:
    print(json.dumps(asyncio.run(run())))
except Exception as error:
    print(json.dumps(namespace["safe_error"](error)))
    sys.exit(1)
'''

LAPTOP_PROGRAM = r'''
import ctypes, json, os, resource, socket, subprocess, sys, time
from pathlib import Path
os.nice(15)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
bundle = json.load(sys.stdin)
pilot = {"__name__": "pool_pilot", "__file__": "<in-memory-pilot>"}
exec(bundle["pilot_source"], pilot)
python = str(Path.home() / ".local/share/orchestra-gemini-web-pilot/.venv/bin/python")
tunnel = None
try:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    tunnel = subprocess.Popen(["ssh", "-N", "-T", "-D", f"127.0.0.1:{port}",
        "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes",
        "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=2",
        "kesha@158.220.127.161"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 12
    while True:
        if tunnel.poll() is not None:
            raise RuntimeError("tunnel failed")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                break
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError("tunnel timeout")
            time.sleep(0.1)
    # Metadata-only profile scan; no other browser database is exported.
    profiles = []
    for browser in ("opera", "google-chrome", "chromium"):
        base = Path.home() / ".config" / browser
        for database in sorted(set(base.glob("*/Cookies")) | set(base.glob("*/Network/Cookies"))):
            profiles.append(database)
    profiles.sort(key=lambda path: ("opera" not in str(path), str(path)))
    accounts, checks, seen = [], [], set()
    for database in profiles:
        pilot["COOKIE_DB"] = database
        try:
            cookies = pilot["load_session_in_memory"]()
        except Exception:
            checks.append({"profile": str(database.relative_to(Path.home())), "cookie_pair_available": False})
            continue
        for index in range(5):
            data = {"cookies": cookies, "index": index, "worker_source": bundle["worker_source"],
                    "proxy": f"socks5h://127.0.0.1:{port}"}
            child = subprocess.run([python, "-c", bundle["init_program"]], input=json.dumps(data).encode(),
                                   capture_output=True, timeout=55)
            result = json.loads(child.stdout)
            checks.append({"profile": str(database.relative_to(Path.home())), "index": index, **result})
            email = result.get("email")
            if child.returncode == 0 and result.get("account_status") == "AVAILABLE" and email not in seen:
                seen.add(email)
                accounts.append({"cookies": cookies, "expected_email": email, "authuser_index": index})
        if len(accounts) >= 3:
            break
    installed = False
    if len(accounts) == 3:
        install = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "kesha@158.220.127.161",
            "cd /home/kesha/orchestra && .venv/bin/python -m app.gemini_web_auth"],
            input=json.dumps({"accounts": accounts}).encode(), capture_output=True, timeout=20)
        installed = install.returncode == 0
    for check in checks:
        if "email" in check:
            local, domain = check["email"].rsplit("@", 1)
            check["email"] = local[:3] + "…" + local[-3:] + "@" + domain
    print(json.dumps({"account_count": len(accounts), "checks": checks, "installed": installed}))
except Exception:
    print(json.dumps({"error": "Laptop discovery failed; diagnostics withheld"}))
    sys.exit(1)
finally:
    if tunnel is not None:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait()
'''


def mask(email):
    local, domain = email.rsplit("@", 1)
    return local[:3] + "…" + local[-3:] + "@" + domain


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # No untrusted subprocess output is printed, even on failure.
    bundle = {"pilot_source": (TASK / "gemini-web-pilot.py").read_text(),
              "worker_source": (ROOT / "app/harness/gemini_web_worker.py").read_text(),
              "init_program": INIT_PROGRAM}
    response = subprocess.run([
        "on-remote", "--pc-home", ".local/share/orchestra-gemini-web-pilot/.venv/bin/python",
        "-c", LAPTOP_PROGRAM,
    ], input=json.dumps(bundle).encode(), capture_output=True, timeout=450)
    incoming = json.loads(response.stdout)
    summary = {"checks": incoming.get("checks", []), "account_count": incoming.get("account_count", 0),
               "installed": response.returncode == 0 and incoming.get("installed", False)}
    if summary["account_count"] != 3:
        summary["error"] = "Exactly three AVAILABLE accounts required; private authorization left unchanged"
    (TASK / "gemini-web-pool-import-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["installed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("Pool discovery/import failed; untrusted diagnostics withheld")
        raise SystemExit(1)
