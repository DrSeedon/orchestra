"""Run offline checks and retain output with private machine prefixes redacted."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parent
REDACTION = (
    "Redaction: workspace/HOME prefixes, encoded workspace slug and username replaced "
    "by /remote/workspace, /remote/workspaces, /remote/home, remote-workspace and remote-user.\n"
)


def redact(text):
    slug = re.sub(r"-+", "-", re.sub(r"[^a-zA-Z0-9]", "-", str(ROOT)).strip("-")).lower()[:80]
    for private, public in ((str(ROOT), "/remote/workspace"),
                            (str(ROOT.parent), "/remote/workspaces"),
                            (str(Path.home()), "/remote/home"),
                            (slug, "remote-workspace"),
                            (Path.home().name, "remote-user")):
        text = text.replace(private, public)
    return text


if __name__ == "__main__":
    temporary = ARTIFACTS / "tmp"
    temporary.mkdir(exist_ok=True)
    name, *command = sys.argv[1:]
    environment = {**os.environ, "TMPDIR": str(temporary), "UV_OFFLINE": "1"}
    result = subprocess.run(command, cwd=ROOT, env=environment, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = redact("$ " + shlex.join(command) + "\n" + result.stdout + f"\nexit_code={result.returncode}\n")
    (ARTIFACTS / f"{name}.txt").write_text(REDACTION + text)
    print(text[-14000:])
    sys.exit(result.returncode)
