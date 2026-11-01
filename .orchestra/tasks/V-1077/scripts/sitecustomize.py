"""Offline test-process guard. Enabled only through the isolated check runner's PYTHONPATH."""
import os
from pathlib import Path
import socket
import subprocess

if os.environ.get("V1077_OFFLINE_CHECKS") == "1":
    def no_network(*args, **kwargs):
        raise RuntimeError("V1077 offline checks: network denied")

    socket.socket.connect = no_network
    socket.create_connection = no_network
    original_popen = subprocess.Popen

    def guarded_popen(args, *positional, **kwargs):
        if isinstance(args, str) or kwargs.get("shell"):
            raise RuntimeError("V1077 offline checks: shell command denied")
        command = [os.fsdecode(arg) for arg in args]
        executable = Path(command[0]).name
        if executable in {"ssh", "curl", "wget", "claude", "codex", "grok", "node", "npx"}:
            raise RuntimeError(f"V1077 offline checks: executable denied: {executable}")
        if executable == "git" and set(command[1:]) & {"commit", "push", "clone"}:
            raise RuntimeError("V1077 offline checks: git write operation denied")
        return original_popen(args, *positional, **kwargs)

    subprocess.Popen = guarded_popen
