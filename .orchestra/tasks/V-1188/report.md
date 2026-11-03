# V-1188 — Telegram Bot API connection refusals

## Findings

The V-647 alert is a real temporary outage of Orchestra's **local Telegram Bot API**, not a failure to reach Telegram's public API. The signal reports 30 connection refusals from 2026-11-01 10:12:10.300277 UTC through 10:16:19.097457 UTC. A second order-variant signature counted 22 refusals through 10:16:14.047220 UTC; a traceback-chain line was separately counted 16 times from 10:12:45.745018 through 10:15:47.614874 UTC.

The failed endpoint is `http://localhost:8081`: the live Orchestra process's `TG_LOCAL_API_URL` resolves to that scheme, host, and port; `/etc/systemd/system/telegram-bot-api.service` starts `/usr/local/bin/telegram-bot-api` with `--http-port=8081`. Thus the refused socket belonged to the local `telegram-bot-api.service` listener.

The listener's current process started at 10:16:24 UTC, about five seconds after the last reported refusal. Its unit has `Restart=always` and a five-second initial restart delay. This timing is consistent with a systemd restart and brackets the end of the refusal window, but without the journal it cannot prove the prior process exit or the restart sequence. Orchestra itself last started later, at 10:22:46 UTC, so its restart did not end this incident.

At inspection (11:09 UTC), `telegram-bot-api.service` and `orchestra.service` were active. `ss` showed a listener on `0.0.0.0:8081` owned by `telegram-bot-api`; a local HTTP GET to `127.0.0.1:8081/` returned 404. This proves TCP/HTTP reachability, not authenticated Bot API operation. No Telegram message or authenticated method was sent.

## Disk and cause

The root filesystem was at 97% with 9.9 GB free; inode use was 7%. This is the current snapshot, not a measurement at 10:12–10:16 UTC. Separate local records show `ENOSPC` failures around 10:23 UTC, after the refusal window, and tasks V-1176, V-1187, and V-1186 cover disk-full symptoms in other jobs. Disk pressure is therefore a plausible same-host context, but available evidence does **not** tie it causally to the Bot API outage. The best-supported proximate explanation is that the local API listener was unavailable until systemd brought it up; the initiating failure remains unknown.

Historical unit logs could not be read: `journalctl` reported that this user cannot see other users' messages, and noninteractive `sudo` was blocked by `no_new_privileges`. The read-only session-database window did not contain the raw Telegram connection lines, so the exact endpoint and event interval above come from the V-647 alert, corroborated by the live process configuration and listener. This leaves the prior process exit reason and exact restart sequence unverified.

## Task and classification

V-647 is the completed detector implementation, not a task to fix this outage. V-1188 is the current investigation. In the 847 task summaries returned for the Orchestra project, no separate Telegram Bot API outage task appeared. Related disk tasks exist (V-1176 in progress, V-1187 new, V-1186 done), but none records this connection-refusal incident.

Classification should be adjusted in a follow-up, but the real refusal must remain actionable. `app/error_watch.py:93` filters the generic `During handling of the above exception...` traceback separator, while the V-647 signal's `The above exception was the direct cause of the following exception:` separator is not covered and becomes its own 16-count finding. Filter that exact traceback-only line as context. The two refusal signatures also differ only in the ordering of IPv4/IPv6 connection-failure details; canonicalizing that ordering would report one incident rather than split counts (30 + 22). No code or classification was changed in this read-only task.

## Coverage and limits

Checked the V-647 task/report and emitted alert, all 847 project task summaries plus full details for V-647 and the related disk tasks, the live Orchestra environment's URL authority, both systemd unit definitions/statuses, socket listeners, a local HTTP reachability probe, filesystem and inode usage, and the accessible session-database interval. No raw or private log rows are included here. Historical system journal access was unavailable, and current disk usage cannot establish disk state during the earlier outage.

No Telegram messages were sent; no services, settings, or operational data were changed. This report is the only file added.
