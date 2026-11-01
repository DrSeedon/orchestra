"""Disable just the new guard, run the existing regression tests, restore it."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
NOTES = Path(__file__).resolve().parent
module_path = ROOT / "app" / "error_watch.py"
original = module_path.read_bytes()
needle = b'and event.get("tool_name") == "Bash" and event["message"].strip() == "Terminated"):'
assert original.count(needle) == 1
command = [
    "uv", "run", "--frozen", "python", "-m", "pytest",
    str(NOTES / "isolated_checks.py"), "-q",
    f"--confcutdir={NOTES}", f"--basetemp={NOTES / 'tmp' / 'mutation'}",
]
try:
    module_path.write_bytes(original.replace(needle, b"and False " + needle))
    with (NOTES / "mutation.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=60)
finally:
    module_path.write_bytes(original)
assert result.returncode == 1, f"Expected assertion failures, got {result.returncode}"
print("Mutation rejected by regression tests; original module restored byte-for-byte.")
