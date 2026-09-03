# fix-tg-bridge-guard — personal notes

## systemd env vars do NOT identify the service process on this VPS
A worker's own Bash inherits `INVOCATION_ID`, `LISTEN_FDS`, `LISTEN_PID`, `NOTIFY_SOCKET` and
`SYSTEMD_EXEC_PID` from `orchestra.service` — measured 18.08.2026, all five present in a
worktree shell. Testing for their *presence* is a check that answers the same way whether or not
the process is the canonical one.

The one non-inheritable fact is pid identity: `os.environ["LISTEN_PID"] == str(os.getpid())` is
true only in the process systemd exec'd (`MainPID=2577299`, `uvicorn app.main:app --fd 3`).
Use that to answer "am I the real instance?"; never `INVOCATION_ID`.

Read the env of the live process with plain `tr '\0' '\n' < /proc/<MainPID>/environ` — same
user, `sudo` is refused here (`no new privileges`).

## `ps` disagrees with the unit file → find the drop-in BEFORE concluding anything
Caught by review on #324. I read `ExecStart=… uv run uvicorn …` in the unit, then measured the
live process as `/opt/.../bin/python -m uvicorn …`, and did not ask why the two differed. The
answer was an untracked drop-in (`/etc/systemd/system/<unit>.d/60-runtime-isolation.conf`) that
resets `ExecStart=`. Because of it I wrote "no unit change required" when the tracked unit would
in fact have broken production.

Rule for next time: `systemctl cat <unit>` (shows base + every drop-in), never `cat` the unit
file alone; and when the observed process does not match the config I just read, that mismatch
IS the finding — resolve it before building anything on top.

Related, worth knowing on its own: **`uv run` does not exec, it forks.** So any systemd contract
keyed to the exec'd pid (`LISTEN_PID`, `sd_notify`, `MainPID`) breaks under an `ExecStart` that
wraps the interpreter. Measured: `uv run` → LISTEN_PID 2751595 vs pid 2751601; direct interpreter
→ equal.
