"""Reproduce the bounded installation and startup checks; never reads credentials."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import time

TASK = Path(__file__).resolve().parent
ROOT = TASK.parents[2]
EVIDENCE = TASK / "evidence"
SCRATCH = TASK / "scratch"
SHA = json.loads((EVIDENCE / "latest-commit.json").read_text())[0]["sha"]
SOURCE = SCRATCH / f"diff-tour-{SHA}"
for directory in (SCRATCH / "tmp", SCRATCH / "bin", SCRATCH / "config", SCRATCH / "cache"):
    directory.mkdir(parents=True, exist_ok=True)

if not SOURCE.exists():
    archive = SCRATCH / "source.tar.gz"
    subprocess.run([
        "curl", "-fsSL", "--max-time", "45",
        f"https://codeload.github.com/init-co-jp/diff-tour/tar.gz/{SHA}",
        "-o", str(archive),
    ], check=True)
    expected = json.loads((EVIDENCE / "hashes.json").read_text())["source_archive_sha256"]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError("Source archive differs from the recorded research snapshot")
    with tarfile.open(archive) as snapshot:
        snapshot.extractall(SCRATCH, filter="data")

env = os.environ.copy()
env.update({
    "TOUR_VERSION": "v0.5.0",
    "TOUR_INSTALL_DIR": str(SCRATCH / "bin"),
    "TMPDIR": str(SCRATCH / "tmp"),
    "XDG_CONFIG_HOME": str(SCRATCH / "config"),
    "XDG_CACHE_HOME": str(SCRATCH / "cache"),
})


def run(label, args, cwd=ROOT, timeout=55):
    started = time.monotonic()
    try:
        result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=timeout)
        code, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as error:
        code, output = "TIMEOUT", error.stdout or b""
    (EVIDENCE / f"{label}.output.txt").write_bytes(output)
    record = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": shlex.join(map(str, args)), "cwd": str(cwd),
        "environment_overrides": {key: env[key] for key in
            ("TOUR_VERSION", "TOUR_INSTALL_DIR", "TMPDIR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")},
        "exit_code": code, "elapsed_seconds": round(time.monotonic()-started, 3),
        "output_file": f"{label}.output.txt",
    }
    (EVIDENCE / f"{label}.command.json").write_text(json.dumps(record, indent=2) + "\n")
    print(label, code, record["elapsed_seconds"])
    return code


run("git-history", ["git", "log", "-5", "--oneline"])
run("git-show", ["git", "show", "HEAD", "--stat"])
run("uv-version", ["uv", "--version"])
run("go-version", ["go", "version"])
if run("install", ["sh", str(SOURCE / "install.sh")], SCRATCH) == 0:
    binary = str(SCRATCH / "bin" / "tour")
    run("tour-version", [binary, "--version"], SCRATCH)
    run("tour-help", [binary, "--help"], SCRATCH)
    run("tour-orchestra", [binary, "HEAD", "--repo", str(ROOT), "--lang", "en"], SCRATCH)
    run("tour-setup-no-tty", [binary, "setup"], SCRATCH)
    run("tour-russian", [binary, "--lang", "ru"], SCRATCH)
