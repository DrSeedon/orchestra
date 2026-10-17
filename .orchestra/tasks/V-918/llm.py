"""V-918 helper: run one prompt (inline text) on a model. luna -> codex exec, sonnet -> claude -p. Usage: import llm; llm.run(model, prompt)"""
import subprocess, tempfile, os
def run(model, prompt, timeout=900):
    if model == "luna":
        with tempfile.TemporaryDirectory(dir="/home/kesha/v918-work") as d:
            o = os.path.join(d, "o.md")
            p = subprocess.run(["codex", "-m", "gpt-6-luna", "-s", "danger-full-access", "-a", "never", "exec", "--skip-git-repo-check", "-o", o, "-"],
                               cwd=d, input=prompt.encode(), capture_output=True, timeout=timeout)
            return open(o).read() if os.path.exists(o) else "ERR " + p.stderr.decode()[-300:]
    with tempfile.TemporaryDirectory(dir="/home/kesha/v918-work") as d:
        p = subprocess.run(["claude", "-p", "--model", "claude-sonnet-5-5", "--tools", "", "--no-session-persistence"],
                           cwd=d, input=prompt.encode(), capture_output=True, timeout=timeout)
        return p.stdout.decode() or "ERR " + p.stderr.decode()[-300:]
