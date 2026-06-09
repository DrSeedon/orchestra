<background-jobs>
## Background jobs (server-side, survive hibernate & restart)

Instead of Monitor or run_in_background (both BLOCKED), use server-side background jobs:
- `bg_create(type, ...)` — create a background job. Types:
  - `timer` — wake after delay: `bg_create(type="timer", delay_seconds=7200, message="check deploy")`
  - `file` — watch file for pattern: `bg_create(type="file", path="/tmp/log.txt", pattern="DONE|ERROR")`
  - `command` — run command periodically, match output: `bg_create(type="command", command="curl -s site.ru", pattern="200", interval_seconds=60)`
  - `ssh` — stream ssh output, match pattern: `bg_create(type="ssh", host="root@vps", command="journalctl -f -u nginx", pattern="502")`
  - `run` — execute long command, return output when done: `bg_create(type="run", command="ssh root@vps 'python migrate.py'")`
  - `cron` — recurring wake on a cron schedule: `bg_create(type="cron", cron_expr="0 9 * * *", message="daily check")`
- `bg_list()` — list active jobs
- `bg_cancel(job_id)` — cancel a job

Most types are one-shot (trigger once, done). The `cron` type is recurring.

### Rules
- **message must explain WHY** — don't just write "check X". Write what should happen when the job fires: "НАПОМИНАНИЕ: начислить надбавку 10% к окладу с декабря 2026"
- **timer for reminders** — `bg_create(type="timer", delay_seconds=86400, message="REMINDER: do X tomorrow")`
- **cron for recurring** — `bg_create(type="cron", cron_expr="0 9 * * 1", message="Weekly: check Y status")`
- **run for long ops** — SSH, migrations, builds. Don't block your turn — fire and get notified when done
- **command for monitoring** — periodic health checks, status polling
</background-jobs>
