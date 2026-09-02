# Message provenance

## Установлено

- `fact:user-message-origin-baseline-2026-09-01` — В frozen live-срезе `logs.type='user_message' AND ts >= '2026-08-25' AND id <= 562928` ровно 2738 строк: user 940, agent-prefix 1136, background-prefix 481, отдельно разобранные 181; граница `id` фиксирует insertion snapshot и не используется как порядок событий · искать: `user_message`, `940`, `2738`, «сообщения приписаны юзеру», `origin` · evidence: read-only SQLite command and classifier in `docs/tasks/433/research.md` §F1 · 2026-09-02, #433
- `fact:user-message-unknown-181-split` — 181 строка вне четырёх исходных prefix-классов раскладывается как operational agent 68, background_task 2, platform 41, system 58, genuinely unknown test artifacts 12; четыре fan-manifest строки имеют два разных происхождения, а 67 initial-delivery rows не имеют authenticated source principal и потому доказывают operational, не security identity · искать: `181`, `LIVE-USER`, `BUG REPORT платформы`, `fan=`, «неопознанное происхождение» · evidence: live receipt joins + trust limit in `docs/tasks/433/research.md` §F2 · 2026-09-02, #433
- `fact:user-message-writer-surface` — `user_message` имеет 29 ingress `send` call sites, три `AgentSession.send` logging branches, один direct compaction `_log` и два transactional direct SQL inserts in `initial_deliveries.py`/`message_deliveries.py`; `db.add_log` не является единственным writer · искать: `manager.send`, `initial_deliveries`, `message_deliveries`, `_log("user_message"`, «все точки записи» · evidence: exact `rg` command and source trace in `docs/tasks/433/research.md` §F3 · 2026-09-02, #433
- `fact:user-message-runtime-prefix-consumers` — Runtime provenance/subtype parsing exists in dashboard `fromMatch`, TG `[from:` handling, RAG `_FROM_RE`, text-tail and runtime-history platform-note filters, session retry-prefix checks and limit-wake content-token checks; `get_worker_logs` additionally labels every `user_message` as human · искать: `fromMatch`, `_FROM_RE`, `WAKE_MESSAGE_PREFIX`, `runtime_history`, `get_worker_logs`, «разбор префикса» · evidence: exact paths/lines in `docs/tasks/433/research.md` §F5 · 2026-09-02, #433

## Отвергнуто

- `fact:user-message-default-origin-not-complete` — «Достаточно добавить default origin в `db.add_log`» отвергнуто: два durable-delivery writer обходят `add_log`, а default скроет пропущенный known-origin caller как `unknown` · искать: `add_log`, `DEFAULT unknown`, `INSERT INTO logs`, «origin по умолчанию» · evidence: `app/initial_deliveries.py:251`; `app/message_deliveries.py:286`; `docs/tasks/433/research.md` §F3 · 2026-09-02, #433
- `fact:user-message-content-cannot-own-origin` — «Prefix/content может остаться fallback-owner происхождения» отвергнуто: одинаковый `fan=...` content в frozen cohort имеет agent и platform origins; явный `unknown` безопасно рендерится слева без parser fallback · искать: `fan manifest`, `content-only`, `unknown слева`, «два владельца происхождения» · evidence: receipt joins in `docs/tasks/433/research.md` §F2/F4 · 2026-09-02, #433

## Пробелы

- Нужен выбор architecture: finite `origin` + non-empty structured `senders[]`/`subtype/ref` versus one validated object; scalar category cannot satisfy «кто именно», scalar `agent:name` cannot satisfy finite-enum contract, mailbox can combine multiple senders · что остановило: user architecture approval and ownership expansion required before Phase 2 · evidence: `app/session_turns.py:577-580`, `docs/tasks/433/research.md` §F3/F6 · 2026-09-02, #433

## Источники

- docs/tasks/433/research.md — frozen live distribution, 181-row provenance ledger, complete writer/consumer inventory and ownership gap.
