# #211 — T5 activation + T2 observe-only runbook

Status: prepared only. **None of these host commands has been executed.** The independent T5
review and an explicit user maintenance window are prerequisites.

## Fixed order inside the approved window

Run from the merged `/home/kesha/orchestra` checkout. Stop on the first non-zero exit.

### 1. Stage the prevention hook; do not restart implicitly

```bash
sudo deploy/manage-claude-env-hook.sh install
sudo systemd-analyze verify orchestra.service
systemctl cat orchestra.service --no-pager
```

Expected manager text includes `restart is required and was NOT performed`. The tracked manager
has no `restart`, `start`, or `stop` call. At this point the running Orchestra process is unchanged.

### 2. Explicit maintenance restart, only after the user authorizes it

```bash
sudo systemctl restart orchestra.service
systemctl is-active --quiet orchestra.service
orchestra_pid=$(systemctl show orchestra.service -p MainPID --value)
sudo tr '\0' '\n' < "/proc/$orchestra_pid/environ" | /usr/bin/grep -Fx \
  'CLAUDE_ENV_FILE=/etc/orchestra/claude-env.sh'
```

The restart interrupts active turns. Estimated restart plus health check: 2–3 minutes.

### 3. Fresh Claude worker probe after reconnect

Create one disposable Claude worker through Orchestra after the restart. Its only Bash command:

```bash
set +e
printf 'grep_type=%s\n' "$(type -t grep)"
printf 'grep_path=%s\n' "$(type -P grep)"
printf 'find_type=%s\n' "$(type -t find)"
printf 'find_path=%s\n' "$(type -P find)"
grep CLAUDE_ENV_HOOK_PROBE tests
printf 'plain_rc=%s\n' "$?"
grep -r CLAUDE_ENV_HOOK_PROBE tests/test_claude_env_hook.py
printf 'recursive_rc=%s\n' "$?"
grep --version | head -n 1
find --version | head -n 1
```

Required result: both types `file`, paths `/usr/bin/grep` and `/usr/bin/find`, plain directory
grep exit 2, explicit recursive grep exit 0, GNU grep 3.11 and findutils 4.9.0. Any difference
blocks T2 activation; rollback the hook and use a separately approved restart to remove it.

### 4. Stage the guard without enabling or starting it

```bash
sudo deploy/manage-process-guard.sh stage
sudo systemd-analyze verify orchestra-process-guard.service
sudo awk -F= '$1 == "ENABLED" || $1 == "DRY_RUN" || $1 == "RSS_ACTION" { print }' \
  /etc/orchestra-process-guard.conf
systemctl is-enabled --quiet orchestra-process-guard.service && exit 1 || true
systemctl is-active --quiet orchestra-process-guard.service && exit 1 || true
```

Required policy is exactly `ENABLED=false`, `DRY_RUN=true`, `RSS_ACTION=log`. `stage` records
pre-existing files, owner/mode and prior service state, verifies installed SHA and unit syntax,
and daemon-reloads systemd; it does not enable or start the guard. Estimated time: under 1 minute.

### 5. Explicitly activate observe-only

```bash
sudo deploy/manage-process-guard.sh activate
systemctl is-enabled --quiet orchestra-process-guard.service
systemctl is-active --quiet orchestra-process-guard.service
guard_pid=$(systemctl show orchestra-process-guard.service -p MainPID --value)
cat "/proc/$guard_pid/cgroup"
sleep 25
sudo journalctl -u orchestra-process-guard.service --since '-30 seconds' -o cat --no-pager
```

The cgroup must be the guard's own systemd service, not `orchestra.service`. Journal must contain
`scan_complete` with `dry_run:true` and no `killed` action.

### 6. Bounded exact-match smoke probe

Run this as one controlled Orchestra Bash command while the temporary watcher remains active:

```bash
probe_dir=$(mktemp -d /home/kesha/orchestra/data/guard-probe.XXXXXX)
mkfifo "$probe_dir/input"
set +e
timeout 25s bash -c \
  'exec -a ugrep /usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe -F NEVER_211 "$1"' \
  _ "$probe_dir/input"
probe_rc=$?
set -e
trash-put "$probe_dir"
test "$probe_rc" -eq 124
```

Then verify:

```bash
sudo journalctl -u orchestra-process-guard.service --since '-2 minutes' -o cat --no-pager \
  | /usr/bin/grep -E '"action":"(calibration_sample|scan_complete)"'
sudo journalctl -u orchestra-process-guard.service --since '-2 minutes' -o cat --no-pager \
  | /usr/bin/grep -F '"action":"killed"' && exit 1 || true
```

The sample must contain the controlled PID/starttime/age/VmRSS/VmHWM. `scan_complete` must show
at least one exact match and diagnostic non-match counts for other target-cgroup processes.

## 24-hour collection and precommitted gate

Record the activation UTC timestamp. After one full daily cycle:

```bash
sudo journalctl -u orchestra-process-guard.service --since '<UTC activation timestamp>' \
  -o cat --no-pager > docs/tasks/211/calibration.jsonl
uv run python scripts/analyze_process_guard_calibration.py \
  docs/tasks/211/calibration.jsonl > docs/tasks/211/calibration-result.json
```

The analyzer was fixed before seeing live results:

- age = `ceil(sqrt(max completed legitimate lifetime upper bound × 720 s))`;
- armed poll = 10 s; age + poll must be strictly below the earliest 720 s incident endpoint;
- scan p99 must be below 1000 ms and guard max RSS below 32768 KiB;
- no still-active/right-censored exact match may remain;
- `RSS_ACTION=log` is invariant and RSS cannot arm a kill.

Any failed condition exits 1 and blocks T3; no threshold is adjusted to make the cycle pass.

## Emergency commands

Stop only the guard, keeping files and audit state:

```bash
sudo deploy/manage-process-guard.sh disable
```

Full guard rollback (fails rather than overwriting any post-install manual change):

```bash
sudo deploy/manage-process-guard.sh rollback
```

Hook rollback is separate and requires another explicitly approved Orchestra restart before the
running service environment loses `CLAUDE_ENV_FILE`:

```bash
sudo deploy/manage-claude-env-hook.sh rollback
```

### Manual recovery after a partial hook rollback

This is needed when a previous rollback restored one destination but failed before completing
the other index or before archiving its claim. A retry then fails loudly with
`Could not archive claimed file without overwriting retained data:` followed by
`$STATE_DIR/removed/hook` or `$STATE_DIR/removed/dropin`; it will not overwrite the retained file.

Inspect the named `$STATE_DIR/removed/<key>`, the matching `$STATE_DIR/backup/<key>`, the live
destination, and any sibling `*.rollback-claim.*`. Move the existing `removed/<key>` with
no-clobber semantics to a new uniquely named retention path outside `deploy-state`; do not delete
or overwrite either copy. Confirm the live destination is the intended saved predecessor, then
rerun `sudo deploy/manage-claude-env-hook.sh rollback`.

Known limitation: if `restore_one(0)` fails, the second destination can remain in its inert
`*.rollback-claim.*` path because the loop has no compensation step. The manager exits non-zero,
the originals remain in `$STATE_DIR/backup/`, and recovery uses the same inspection-and-retention
procedure above; this task intentionally does not add compensation to that loop.
