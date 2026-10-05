from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote
import os
import subprocess


TRASH = Path.home() / ".local/share/Trash"
now = datetime.now().astimezone().replace(tzinfo=None)
cutoff = now - timedelta(hours=24)
groups: dict[str, list[tuple[datetime, Path]]] = defaultdict(list)

for info in (TRASH / "info").glob("*.trashinfo"):
    try:
        fields = dict(
            line.split("=", 1)
            for line in info.read_text(errors="replace").splitlines()
            if "=" in line
        )
        original = unquote(fields["Path"])
        deleted = datetime.fromisoformat(fields["DeletionDate"])
    except (KeyError, ValueError):
        continue
    groups[original].append((deleted, info))

candidates = {
    original: records
    for original, records in groups.items()
    if original
    and all(deleted < cutoff for deleted, _ in records)
    and not any(char in original for char in "*?[")
}


def process_env_values() -> list[str]:
    values: list[str] = []
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            raw = Path(f"/proc/{entry.name}/environ").read_bytes().split(b"\0")
        except OSError:
            continue
        values.extend(
            item.split(b"=", 1)[1].decode(errors="replace")
            for item in raw
            if b"=" in item
        )
    return values


def payloads_for(records: list[tuple[datetime, Path]]) -> list[Path]:
    return [TRASH / "files" / info.name.removesuffix(".trashinfo") for _, info in records]


def open_payloads(payloads: list[Path]) -> bool:
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            fds = os.scandir(f"/proc/{entry.name}/fd")
        except OSError:
            continue
        with fds:
            for fd in fds:
                try:
                    target = os.readlink(fd.path)
                except OSError:
                    continue
                if target.endswith(" (deleted)"):
                    continue
                for payload in payloads:
                    if target == str(payload) or target.startswith(str(payload) + "/"):
                        return True
    return False


def referenced_by_env(original: str, values: list[str]) -> bool:
    return any(value == original or value.startswith(original + "/") for value in values)


def allocated_bytes(payloads: list[Path]) -> int:
    total = 0
    for payload in payloads:
        if payload.is_file():
            try:
                total += payload.stat().st_blocks * 512
            except OSError:
                pass
        elif payload.is_dir():
            for directory, _, files in os.walk(payload, followlinks=False):
                for name in files:
                    try:
                        total += (Path(directory) / name).lstat().st_blocks * 512
                    except OSError:
                        pass
    return total


removed = open_skips = env_skips = failed = 0
freed_estimate = 0
for original, records in candidates.items():
    payloads = payloads_for(records)
    if open_payloads(payloads):
        open_skips += 1
        continue
    if referenced_by_env(original, process_env_values()):
        env_skips += 1
        continue
    bytes_before = allocated_bytes(payloads)
    result = subprocess.run(["trash-rm", original], capture_output=True, text=True)
    if result.returncode:
        failed += 1
        print(f"FAILED {result.returncode} {original} {result.stderr.strip()}")
        continue
    removed += 1
    freed_estimate += bytes_before

print(
    f"cutoff={cutoff.isoformat()} candidates={len(candidates)} removed_paths={removed} "
    f"open_skips={open_skips} env_skips={env_skips} failed={failed} "
    f"allocated_bytes_estimate={freed_estimate}"
)
