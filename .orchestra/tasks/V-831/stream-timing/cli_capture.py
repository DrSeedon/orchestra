"""Timestamp every stream-json line of a real Claude CLI run (V-831 upstream timing)."""
import json, os, subprocess, sys, time
model, out = sys.argv[1], sys.argv[2]
prompt = sys.argv[4] if len(sys.argv) > 4 else ("First write a plain-text answer of about 1500 characters explaining how TCP congestion control works. "
          "Then call the Write tool exactly once to create notes.md containing a 60-line markdown summary "
          "(one bullet per line). Do nothing else.")
cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json",
       "--include-partial-messages", "--verbose"]
start = time.monotonic()
with open(out, "w") as fh:
    extra_env = dict(kv.split("=", 1) for kv in os.environ.get("CAPTURE_ENV", "").split() if "=" in kv)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, cwd=sys.argv[3], env={**os.environ, **extra_env})
    for line in proc.stdout:
        fh.write(json.dumps({"t": round(time.monotonic() - start, 4), "line": json.loads(line)}) + "\n")
    proc.wait()
print("rc", proc.returncode)
