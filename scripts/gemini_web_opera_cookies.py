"""Authorized Opera cookie source. Stdout is a PRIVATE credential pipe, never a log.

Invoked on demand over the existing laptop tunnel. No browser/cache/temp files.
"""
import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
from urllib.parse import quote
COOKIE_DB = Path.home() / ".config/opera/Default/Cookies"
COOKIE_NAMES = ('__Secure-1PSID', '__Secure-1PSIDTS', 'SID', 'HSID', 'SSID', 'APISID', 'SAPISID', '__Secure-1PAPISID', '__Secure-3PAPISID', '__Secure-3PSID', '__Secure-3PSIDTS', 'SIDCC', '__Secure-1PSIDCC', '__Secure-3PSIDCC', 'LSID', '__Host-1PLSID', '__Host-3PLSID')

def load_session_in_memory() -> dict[str, str]:
    from Cryptodome.Cipher import AES
    from Cryptodome.Protocol.KDF import PBKDF2
    from Cryptodome.Util.Padding import unpad

    service = "org.kde.kwalletd6"
    wallet_path = "/modules/kwalletd6"
    app_id = "orchestra-gemini-web-pilot"

    def wallet_call(method, *values):
        process = subprocess.run(
            ["qdbus6", service, wallet_path, "org.kde.KWallet." + method, *map(str, values)],
            capture_output=True, text=True, timeout=12,
        )
        if process.returncode:
            raise RuntimeError("wallet-call-failed")
        return process.stdout.rstrip("\n")

    handle = None
    try:
        wallet = wallet_call("networkWallet")
        if wallet_call("isOpen", wallet) != "true":
            raise RuntimeError("wallet-locked")
        handle = int(wallet_call("open", wallet, 0, app_id))
        if handle < 0:
            raise RuntimeError("wallet-access-declined")
        secret = wallet_call(
            "readPassword", handle, "Chromium Keys", "Chromium Safe Storage", app_id,
        ).encode()
        if not secret:
            raise RuntimeError("storage-secret-unavailable")
    finally:
        if handle is not None and handle >= 0:
            wallet_call("close", handle, "false", app_id)
    key = PBKDF2(secret, b"saltysalt", dkLen=16, count=1)
    del secret
    with sqlite3.connect("file:" + quote(str(COOKIE_DB)) + "?mode=ro", uri=True) as db:
        version = int(db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
        rows = db.execute(
            "SELECT host_key,name,value,encrypted_value FROM cookies "
            "WHERE host_key IN ('.google.com', 'accounts.google.com') AND name IN (" + ",".join("?" for _ in COOKIE_NAMES) + ")", COOKIE_NAMES,
        ).fetchall()
    result = {}
    for host, name, plain, encrypted in rows:
        if plain:
            result[name] = plain
            continue
        if not encrypted.startswith(b"v11"):
            raise RuntimeError("unsupported-cookie-encryption")
        decoded = unpad(AES.new(key, AES.MODE_CBC, iv=b" " * 16).decrypt(encrypted[3:]), 16)
        if version >= 24:
            if decoded[:32] != hashlib.sha256(host.encode()).digest():
                raise RuntimeError("cookie-domain-verification-failed")
            decoded = decoded[32:]
        result[name] = decoded.decode()
    if any(not result.get(name) for name in ("__Secure-1PSID",)):
        raise RuntimeError("essential-cookie-missing")
    return result

if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    os.nice(15)
    try:
        print(json.dumps(load_session_in_memory()))
    except Exception:
        raise SystemExit(1) from None
