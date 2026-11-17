# Audit disposition and deployment gates
- A1: one canonical ACP token, CLI symlink; private legacy backup; atomic application promotion
  preserves the link, excludes an active vendor writer. Spawner flock serializes manual CLI/ACP
  per --gemini-dir; app removes --process-per-session so one Go token-source mutex owns refresh.
  LIMIT: vendor's own os.WriteFile remains non-atomic on crash. No binary patch/eligibility bypass.
- A2/A10: ordinary RPC/auth/quota/model refusals and >1MiB writes are session-local. Prompt timeout/
  slow cancel quarantines that session and retains capacity until close or process exit.
  Real pipe/wire identity corruption closes transport; later explicit caller may start a new front,
  with no failed prompt replay. Definite account-disabled/ToS remains durable.
  Instructions_sent advances only on successful write+drain.
- A3/A8: fresh cached weekly AND 5h windows project into admission, hard stop 95%.
  Optional explicit counter/quota observations are accepted passively. Context used/size is not
  billed tokens. Cumulative baselines survive backend replacement; an unknown resumed baseline stays
  unknown, API-equivalent price is labelled. G1 Pro rate registered.
  LIMIT: vendor 1.5.9 has not been verified here to emit token/quota payloads. Missing observations
  remain unknown; this work does not create a new active Google observer.
- A4: versioned spawner/tool MemoryHigh=6G, MemoryMax=8G.
- A5/A9: actual synthetic spawner handler -> mocked Popen captures BROWSER, GEMINI_HOME,
  AGY_ACP_FORCE_FILE_STORAGE; unrelated secrets excluded. Malformed IPC FD delta=0,
  request deadline 5s, BoundedSemaphore 64 connections.
- A6: final archive and successful compact release owned native state/maps. Temporary disconnect
  preserves native resume and compact rollback. 100 synthetic create/close cycles plus keeper:
  1 spawn, 101 close RPCs, bounded owner maps, final front exit.
  LIMIT: session/close is optional and only invoked when advertised. Unsupported/failed close does
  not prevent app archive; remaining vendor state ends with last profile exit, never sibling kill.
- A7: exact G1 Pro ID + current aliases; same-runtime retarget uses native selector ACK before
  publishing model change. Availability still depends on actual offered account catalogue.
- A11: runtime capability prevents automatic compaction scheduling and misleading start logs;
  owner manual compact unchanged. Canonical local Antigravity provider prompt reaches backend
  assembly for both worker/orchestrator roles, including custom prompts.
- A12: completed native-response FIFO cache (512), exact retry returns prior response without
  another decision; up to 16 pending requests. Changed-payload ID remains protocol corruption.
- S2: merge_worker only done after SUCCEEDED; PENDING/RUNNING keeps durable entry and blocks close.
- Own events: only proof-bound durable own run/file/merge completions; peer live orchestrator direct
  messages and direct child reports. Cron/cron_command/timer/scheduler/dreaming/retries/system/
  platform/unknown stay denied. Arbitrary creator config is stripped and server-bound.
- GPT-6.2 Sol/Astra: manual-only 500000/272000, prices 2/.10/10 and 8/.40/40, sol62/astra62;
  sol alias and all live orchestrator assignments remain unchanged.

Deployment authorized: fast-forward production main while preserving its three dirty files;
install reviewed IPC/units, daemon-reload, controlled service restart only without running turns;
never restart telegram-bot-api. Passive Hydrogen check only, never Hub or provider prompts.
