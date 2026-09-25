TASK STATE
- I am the orchestrator of the Orchestra project (VPS, `/home/kesha/orchestra`). It is 24.09, around 05:40 Berlin time.
- The owner commanded «Рестарт» at 10:34 Krasnoyarsk time. The restart is done: the service became active at 05:36:53 CEST (MainPID 1383961) and HTTP returns 302.
- The restart activated everything merged since the previous one:
  - V-626 owner-time telemetry. The table `owner_activity_events` exists and the backfill wrote 2557 rows with `source=estimated`.
  - V-627 precompact.
  - V-628 TG collapse.
  - V-620 and V-621.
  - The compaction-report fix.
  - GPT-6 prices and `luna→gpt-6-luna`.
- Merged today, each accepted with my own mutation check:
  - V-626 (commit `7556cfa`). History recomputed with the owner's rules: 46.70 h estimated, compared with 101.12 h under the old 10-minute think window and 163.12 h under V-57's 30-minute gap. Largest scopes: comfy 12.92 h, seedon 11.91 h, orchestra 10.07 h.
  - V-627 (`b3aae16`). Precompact now fires in IDLE and WAITING regardless of active background jobs.
  - V-628 (`759b3be`). Each non-owner incoming message becomes one TG message with a header and an EXPANDABLE_BLOCKQUOTE capped at 4096; the compaction summary is also routed that way.
- Workers `owner-time`, `fix-precompact` and `tg-incoming` are killed. They were one-shot, merged and clean.
- Remaining workers are all idle: `prompt-engineer` (persistent), `bench2-opus5` (V-623), `bench2-opus55` (V-624) and `laptop-rescue` (V-625).
- The VKRS package (University) is closed. The director had already sent their own version, and nothing more is needed from me.
- Seedon was at 57% context. It should self-compact via precompact after its next turn plus about 55 minutes idle.

DECISIONS
- V-626, owner's decisions:
  - Keep raw events forever.
  - Use a random token per tab.
  - Count presence only when the tab is visible, the window is focused and the last input was within 5 minutes.
  - Attribute time to exactly one scope per second; presence wins over a message.
  - Message think window is 1 minute, extended by message length or voice duration, capped at 10 minutes.
  - Days are counted in Krasnoyarsk time (UTC+7).
  - No TG reactions or edits.
- V-627: the owner said to compress even when background jobs are active.
- V-628: incoming messages are collapsed and closed by default. The compaction summary is shortened in TG too. Overflow text gets a "полный текст в дашборде" notice; there is no link because the bridge has no dashboard URL.
- Earlier decisions still stand:
  - Luna is GPT-6; Sonnet is the Claude-side analog; Opus is for special tasks. Astra and Sol are banned.
  - Opus 5.5 effort is medium.
  - No Co-Authored-By trailer.
  - Laptop Orchestra must always be running.

FILES AND ARTIFACTS
- `.orchestra/tasks/V-626/report.md` and `owner-time.html`: merged. I read the report in full.
- New and changed code, merged:
  - `app/owner_activity.py`
  - `app/routes/owner_activity.py`
  - `app/static/js/owner-activity.js` and `owner-activity-policy.js`
  - changes in `app/db.py`, `app/schema.sql`, `app/main.py`
  - `tests/test_owner_activity.py`
- `app/session.py`: precompact gate changed, and the compaction summary now carries platform provenance. Merged.
- `app/tg_bridge.py`: `_incoming_message_parts`, `_expandable_message`, `_truncate_utf16`. Merged.
- `CHANGELOG.md`: entries for V-627 and V-628.
- DB backup before the restart: `/home/kesha/orchestra/data/orchestra-pre-v626-20260924.db` (1.97 GB).
- `/tmp/vkrs-review2/*`: my edited VKRS copies. Not used; the director sent their own version.

COMMANDS AND TOOL OUTCOMES
- Restart command: `ssh kesha@localhost "sudo -n systemctl restart --no-block orchestra"` returned RESTART_QUEUED. The owner denied my follow-up sleep check. After the restart I verified that the service is active.
- The journal after the restart shows two old recurring errors, present at every restart since 22.09:
  - `project layout migration failed` for dnd-game-master: `ORCHESTRA_LAYOUT_PARTIAL`.
  - The same for cog-second-brain: `ORCHESTRA_LAYOUT_GIT_ERROR`, stash `fb3d4d…`.
  - Cog's dirty file `02-personal/katya/katya-health-2026-07.md` is 59398 bytes, so it is not zeroed.
- TG `topic_status` returned TimeoutError right after startup. This looks transient.
- `publish_artifact` returned http_4xx; I used `send_file` as a fallback.
- Working pytest interpreter: `/home/kesha/orchestra/.venv/bin/python -m pytest`.

BLOCKER / NEXT
- No blocker.
- Cron `bg-241e7f1463` fires at 07:00 UTC on 24.09. When it does:
  - check the Claude quota;
  - wake `bench2-opus55` (undelivered `bg-cc536e89a8`) and `laptop-rescue` (undelivered `bg-5b9a7aa887`, pin preserve snapshots first);
  - create a task and worker for the layout-preserve data-loss fix. It also covers the dnd and cog migration failures on the VPS;
  - create one for the laptop SIGTERM hang;
  - propose the seedon V-44 adhoc-merge fix;
  - compare Opus 5 and 5.5 on bench-2, merge the better branch, then kill both.

CONSTRAINTS
- Durable:
  - Implementation needs the owner's word; research does not.
  - Only the owner initiates a restart.
  - Architectural forks go to the owner first.
  - Replies are in Russian, verdict first, with a table.
  - Accept work by artifact plus my own mutation, and read reports in full.
  - No tests pinned to wording.
  - Tests never touch the live DB or task store.
  - No git stash.
  - Heavy runs go outside the cgroup via `ssh kesha@localhost`.
  - Only `:free` OpenRouter routes.
  - Don't touch other projects' contours unless explicitly asked.
  - Don't push to the public origin unless asked.
  - Zahoron is never touched.

USER MESSAGES AND RAW TRANSCRIPT
Raw transcript: `/api/sessions/Orchestra-orchestrator/logs?scope=/home/kesha/orchestra`. Messages since the previous summary, verbatim, in order (forwarded posts are summarized):
1. [16:47] «все баги сегодня в туду запиши. оркестра на ноуте должна быть всегда в работе что за цикл чинить надо все. гейт жди завтра продолжим пока сегодня все замери давай в мд запиши чтобы не потерять»
2. (seedon relay of an owner request) «Надо в оркестре продумать как сделать замер времени сколько и когда я сижу. Учитывать и фронт дашборд сайт там просто думаю и тг когда общаюсь с тобой»
3. [18:14] «Да давай сначала ресерч и план и в хтмл артефакт все это чтобы я понимал как будет система работать наглядно»
4. (University relay: VKRS package review; not a direct owner message)
5. [20:50] «да переписывай все на слайде ты че сразу надо было»
6. [20:52] «по учету времени давай развилки какие поясни и сам предложи давай обсудим»
7. [20:57] «1 а если не удалять че зачем удалть пусть леэат не много же данных. 2 у меня только на ноуте дашборд. да все равно делай. 3 да 4 надо четко считать в каком проекте сижу сколько секунд все бещшовно. 5. 10 минут не бывает типо я думаю почти вслух то есть думаю и печатаю тебе. может минуту?  7 красноярск. да реакции я тебе не ставлю»
8. [23:38] «чекай хули компакт сидона не срботал и остальных изучи» (pasted seedon card: claude-opus-5-5[1m], $3522.10, ctx 53%, ⏳ ждёт)
9. [10:11] «Да чини механизм все равно сжимать даже с бг»
10. [10:13] «Крч сообщения тг надо доработать видишь какой сплошной текст ответов это пиздец давай все приходящие сообщения форматировать в 1 сообщение и типо ответ от такого-то и текст в раскрывающимся будет и а по умолчанию закрыт», plus forwarded examples: a Slipways V-45 WIP report and cog's compaction summary.
11. [10:15] «И компакт ответ тоже сокращать втг», plus forwarded examples.
12. [10:34] «Рестарт»