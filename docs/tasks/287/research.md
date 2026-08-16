# #287 — Сохранение рабочего состояния при переключении Claude / Codex / Grok

**Статус:** Phase 1 research + experiment, 2026-08-16. Runtime и конфигурация не изменялись.

## Вопрос

**Контекст.** Orchestra одного владельца ведёт сотни долгих agent-сессий в SQLite и переключает активный CLI runtime между Claude, Codex и Grok. У каждого провайдера собственные thread/session stores, формат tool events, system/developer prompt и правила compaction.

**Изменение под проверкой.** Найти переносимый контракт, который сохраняет наблюдаемое рабочее состояние, не выдаёт provider-native состояние за общее и не повторяет уже совершённые side effects.

**Baseline.** Текущий код использует либо полный Orchestra log, переложенный в target-native history для Claude↔Codex, либо старый `last_summary`, либо bounded visible `runtime_handoff`; same-provider Codex может продолжить native thread.

**Решающие outcomes.** Factual retention, сохранность решения и его evidence, completed/pending side effects, unresolved branch и next action; invented facts; tool-schema contamination и prompt injection; context fit до первого полезного хода; input overhead, latency и API-equivalent virtual cost.

Скрытый chain-of-thought **не является доступным outcome**: его нельзя наблюдать, проверять или переносить как смысловое состояние. Исследование не реконструирует его из финальных ответов.

## Гипотезы и фальсификаторы

1. **H1 — deterministic state packet + адресные raw refs сохраняет состояние лучше prose/raw, потому что отделяет факты и side effects от порядка сообщений.** Фальсификатор: packet/hybrid хуже raw или prose по критическому state retention либо создаёт больше неподтверждённых фактов/опасных действий.
2. **H2 — provider-native resume является верхней границей только внутри совместимого provider store.** Фальсификатор: native resume надёжно переносит opaque state между providers; либо на том же provider систематически хуже каждого portable arm без overflow/compatibility failure.
3. **H3 — raw replay опаснее bounded typed state, потому что старые tool results снова попадают в model-visible context.** Фальсификатор: на malicious fixtures raw не увеличивает injection/tool contamination, а boundary одинаково исполняется во всех arms.
4. **H4 — source-generated summary является достаточным переносимым truth.** Фальсификатор: source недоступен, summary stale, либо summary теряет числа/отрицания/evidence, которые packet сохраняет.
5. **H5 — target-side synthesis нужен всегда.** Фальсификатор: полный bounded deterministic packet без synthesis даёт ту же целостность дешевле и без compatibility ambiguity.

## Краткий ответ

Лучший durable контракт — **не transcript и не provider thread, а детерминированный canonical state packet из Orchestra DB**. Cross-provider switch сначала проходит deterministic capability/ingress negotiation. Только при доказанном schema/capability mismatch, неоднозначности или oversized delta целевая модель в отдельном stateless/tool-disabled ходе синтезирует из packet + bounded raw delta собственный compatibility brief; packet и адресные event refs остаются источником истины. Native resume сохраняется как привилегированный same-provider путь, но только после размерного preflight и ingress canary первого успешного model call.

Это не означает, что target synthesis нужен всегда. В corrected exploratory experiment plain deterministic packet и hybrid оба дали полное состояние на всех успешно завершённых action cells; packet был заметно дешевле. Raw replay допустим для короткого, полного, типизированного и заведомо помещающегося delta. Живой Seedon импорт показывает обратную границу: структурно принятый raw/native import может заполнить окно до `258400/258400` и умереть до первого полезного хода.

**Уверенность: LIKELY для общей архитектуры** — её поддерживают текущий код, два живых отказа, prior art и первичные provider contracts; paired experiment ограничен одной репликой, без Claude и с поздним исчерпанием Grok Build balance.

## 1. Что переносит Orchestra на `main` сегодня

Исследован commit `43eb156a` — база Phase 1.

### 1.1 Canonical DB snapshot и native import Claude↔Codex

- `_build_claude_history_import()` и `_build_codex_history_import()` сначала дожидаются pending log writes, затем берут immutable boundary из `get_history_logs()` и рендерят target-native entries (`app/session.py:1332-1377`). `get_history_logs()` выбирает **все** строки сессии до `MAX(id)` без dashboard cap в 5k (`app/db.py:1517-1534`). **CONFIRMED — tier 2 code.**
- Рендерер version-pinned на Claude CLI `2.1.197`, SDK `0.2.114`, Codex `0.146.0`. Он переносит видимые user/assistant messages и исторические tool call/result records, редактирует secrets и намеренно пропускает строки `thinking` (`app/runtime_history.py:16-30,256-390`). **CONFIRMED — tier 2 code.**
- Исторические tools сопровождаются developer/system instruction: действия уже завершены, outputs — untrusted, side effect нельзя повторять без нового запроса (`app/runtime_history.py:27-31`). Это правильная boundary-инструкция, но сама по себе не ограничивает размер.
- Claude import возобновляет UUID через custom read-only `ClaudeLogSessionStore`, добавляет текущий Orchestra system prompt и historical-tool instruction; обычный Claude resume остаётся provider-native (`app/backend_claude.py:621-632`).
- Codex import включает experimental API и вызывает `thread/resume` с seed `threadId` и полным массивом `history`; app-server возвращает новый thread ID. После принятого `thread/resume` backend сразу очищает `_history_import` (`app/backend_codex.py:558-596`). Проверки суммарного token fit до этого вызова нет.

### 1.2 Точная семантика `truncated`

`truncated` в status line — **не число уникальных исходных строк и не число отброшенных токенов**.

1. `_normalize_history()` помечает каждый source tool row, у которого имя/payload был обрезан per-row лимитом (`8k` call, `20k` result, `512` name) или общий newest-first detail budget `256000` исчерпался; сумма таких source rows становится исходным `report.truncated` (`app/runtime_history.py:21-25,271-303,434`).
2. Затем visible-budget pass оставляет только suffix tool records под отдельным `256000` chars и **добавляет количество выпавших rendered tool call/result items** к тому же полю (`app/runtime_history.py:170-192`). Одна исходная tool row поэтому может быть учтена дважды: сначала как clipped/omitted payload, затем как удалённый rendered item.

На точном Seedon snapshot воспроизведено: до visible pass `truncated=5807`; visible pass удалил ещё `6108` rendered tool items; итоговая строка `truncated=11915`. Финальная target history содержала 2003 items, из них 248 tool items. **CONFIRMED — tier 1 direct reproduction.** Следовательно, status `11915` нельзя читать как «обрезано 11915 source rows».

### 1.3 Summary, `runtime_handoff`, compaction и thread IDs

- Общий cross-runtime путь, кроме специальных Claude↔Codex adapters, при reset native session выбирает непустой `last_summary`; иначе строит `_build_runtime_handoff()` (`app/session.py:2815-2855`). `runtime_handoff` — последние 120 **всех** log rows до фильтра, только `user_message/text`, не более 6000 chars на сообщение и 32000 chars всего; tool rows полностью исключаются (`app/session.py:2473-2511`).
- Поэтому Grok сейчас не получает Claude/Codex native history; ему передаётся provider-neutral visible handoff/summary и выдаётся новый native session ID. `resume_across_models=True` объявлен только у Codex; у Grok `False` (`app/runtime_registry.py:314-338`).
- На non-Codex compact **source/current model** пишет prose handoff из `TASK STATE / DECISIONS / BLOCKER-NEXT / CONSTRAINTS`, после чего создаётся новая native session; bounded summary сохраняется в `last_summary` (`app/session.py:2050-2085,2232-2336`). Это source-generated summary, не target synthesis.
- На Codex `thread/compact/start` работает внутри текущего native thread и не заменяет thread ID; Orchestra сохраняет возвращённый summary, а при его отсутствии строит `runtime_handoff` (`app/session.py:1978-2030`, `app/backend_codex.py:717-754`). Это provider-native compaction, а не переносимый summary protocol.
- `session_id` и `session_id_history` сохраняют opaque native identifiers как backend references. Они полезны для возврата в тот же provider store, но не описывают objective, decisions или side effects и не являются portable state.

### 1.4 Кто строит summary

| Сценарий | Автор summary/сжатия | Что остаётся provider-native |
|---|---|---|
| Claude/non-Codex `compact()` | текущая source model по Orchestra prompt | старая и новая Claude native sessions; opaque store |
| Codex `compact()` | Codex app-server внутри текущего thread | весь compacted thread и его ID |
| Generic runtime switch с `last_summary` | тот, кто создал старый compact; target его не проверяет | source/target native IDs отдельно |
| Generic switch без summary | deterministic Orchestra formatter, но только visible 120-row tail | новый target native session |
| Claude↔Codex native import | deterministic Orchestra renderer строит target-native history; prose summary только fallback | исходный provider store и новый target store несовместимы |

## 2. Prior art #174 и #243

### #174 — portable handoff важнее transcript converter

На живом snapshot старый `_build_runtime_handoff()` сохранял 24/1284 semantic rows (1,87%) и 15163/1760169 semantic chars (0,86%); 76/120 newest rows были tools/results и после выбора окна были выброшены. Реальный switch использовал stale `last_summary` 3337 chars и не включил 14 более новых semantic rows/6580 chars и 65 tool/result rows/251149 chars ([`docs/tasks/174/research.md`](../174/research.md)). **CONFIRMED — tier 1 DB measurement из #174, повторно сверено с текущим code path.**

#174 уже рекомендовал typed agent summary + server metadata + recent machine tail и version-pinned native adapter только как дополнение. #287 уточняет этот контракт: server-owned packet становится canonical, side effects получают явный lifecycle/idempotency, raw tail получает addressable IDs, а commit switch переносится за успешный ingress-validation turn и механическую capability check.

### #243 — native resume сохраняет thread, но не гарантирует fit

В same Codex thread Sol→Luna/Spark сохранялись thread ID и semantic UUID. Однако первый changed-model cache hit падал с 93,57% до 15,37%; Spark принял resume выше собственного окна и следующий turn завершился `context_window`, auto-compact не сработал ([`docs/tasks/243/research.md`](../243/research.md)). **CONFIRMED — tier 1 isolated runs из #243.**

#243 не доказал перенос скрытого reasoning: rollout оставался физически тем же, но внешний протокол не показывал, какие opaque provider blobs target реально использовал. Это остаётся **UNCERTAIN**, и canonical state на такой посылке строить нельзя.

## 3. Первичные provider contracts (проверено 2026-08-16)

### OpenAI / Codex

- Codex app-server разделяет `thread/start|resume|fork`, `turn/start`, `thread/compact/start` и experimental `thread/inject_items`. `inject_items` пассивно добавляет model-visible Responses items без user turn; compact сжимает этот же thread. [1]
- OpenAI conversation state может связываться через `previous_response_id`; при ручной истории docs требуют возвращать output items, включая opaque/encrypted reasoning items, когда они есть. Это provider conversation contract, не переносимая семантика. [2]
- OpenAI Model Spec ставит tool outputs и quoted/untrusted text ниже developer/system authority; данные внутри tool result не становятся инструкциями. [3]

**Вывод:** `thread/resume` подтверждает, что store/history структурно принят, но отдельный `turn/start` впервые проверяет model-call fit. `inject_items` — транспорт, не summary и не privilege elevation.

### Anthropic / Claude Code

- Claude Code CLI поддерживает `--continue` и `--resume` своей сессии; Agent SDK session browser читает локальные JSONL transcripts, может inspect/fork/resume по session ID. [4][5]
- Anthropic не показывает raw chain-of-thought: клиент получает summaries; полный thinking block приходит как opaque signed/encrypted material, который надо возвращать неизменённым внутри поддержанного API. При смене модели Anthropic предписывает удалить thinking/redacted-thinking blocks из предыдущего assistant turn. [6]
- Anthropic отдельно рекомендует считать tool results untrusted, не вставлять их как system/plain privileged instruction, сохранять provenance/structure и минимизировать privileges. [7]

**Вывод:** Claude session store — provider-native cache. Даже доступный encrypted block нельзя прочесть и преобразовать в canonical decision; cross-model/provider switch не должен реконструировать его.

### xAI / Grok Build

- Grok Build автоматически сохраняет sessions в JSON/JSONL store, поддерживает headless session resume/load и ACP `session/new|load`; auto-compaction имеет provider-native threshold. [8]
- `/resume` продолжает local session, `/compact` сжимает её, `/flush` просит LLM summary. [9]
- xAI reasoning API возвращает encrypted reasoning для round-trip и отдельно summarized reasoning; opaque content не становится читаемым transferable state. [10]

**Вывод:** Grok, как Claude/Codex, умеет native continuity внутри собственного store, но официальные материалы не обещают импорт чужого provider thread или общую схему hidden state.

### Общая граница reasoning

**CONFIRMED — tier 2 primary docs + current renderer:** скрытый chain-of-thought недоступен Orchestra и не переносится. `thinking` logs текущего renderer пропускаются; opaque encrypted provider blocks можно максимум round-trip неизменёнными в том же поддержанном provider contract. Canonical packet содержит только наблюдаемые facts, decisions, evidence и effects. Никакой «реконструкции reasoning» из финального текста не выполняется.

## 4. Главный живой failure case: Seedon Claude Opus → Codex Sol

Сессия `seedon-orchestrator` (`09b75a6c…`) переключена `claude-opus-5[1m] → gpt-5.6-sol`.

### Наблюдаемый порядок

1. Log `116299`: `users=872`, `assistants=883`, `tools=3080/3050`, `tool chars detailed=256000`, `truncated=11915`, `secrets redacted=285`, `reasoning omitted=0`.
2. После однословного user message `ку` новый turn завершился до ответа: `Codex ran out of room in the model's context window`, `stop_reason=context_window`, `0 turns`; dashboard показывал `$53.80 ctx` и `$0.00 turn`.
3. Rollout принятого thread имел 2016 JSONL lines и 4 880 420 bytes; последний `token_count` был ровно `total_tokens=258400`, `model_context_window=258400`, при нулевых input/output токенах текущего хода.
4. Повтор создал другой Codex thread ID; `codex_apps`, `orchestra`, `mcp-pandoc` получили cancelled startup statuses. Следующий turn ответил только `Ку! Что делаем?`, то есть imported working state уже не использовался.

**CONFIRMED — tier 1 live DB + rollout measurement.** Секреты в отчёт/fixtures не копировались.

### Почему `thread/resume` принял oversized history

Current app-server protocol разделяет resume и turn [1]. Orchestra вызывает `thread/resume`, принимает новый ID и очищает `_history_import` (`app/backend_codex.py:578-596`); model turn запускается позже. В коде нет preflight суммарных tokens для history + developer/project prompt + tool schemas + нового user turn + output/reasoning reserve. Поэтому структурно валидная history была сохранена, а первый model call оказался невозможен.

**LIKELY — tier 1 trace + tier 2 code/protocol:** это точная внешне наблюдаемая причинная граница. Внутреннюю реализацию token admission в Codex cloud исследование не видит и не приписывает ей неописанный алгоритм.

### Почему retry не восстановил state

Switch фиксируется в DB сразу после принятого backend connect (`app/session.py:2720-2803`). Fallback ловит только `NativeHistoryImportError` во время import/connect. `context_window` приходит позже из первого turn, когда `_history_import=None`, поэтому old state restoration и bounded fallback недостижимы. Наблюдаемый новый thread и амнезичный ответ подтверждают потерю active target state.

**CONFIRMED для отсутствующего Orchestra recovery seam; UNCERTAIN для внутренней причины выбора именно fresh thread на повторе.** Нельзя утверждать больше, чем показывают code path и IDs.

### Требуемый fail-closed preflight и bounded fallback

До disconnect incumbent надо проверить:

```text
T_fixed(system + developer + project docs + target tool schemas)
+ T_packet + T_selected_raw_delta + T_current_user
+ R_output + R_reasoning + R_tokenizer_uncertainty
<= W_target
```

Token count должен идти через target/provider counter, если он доступен; иначе нужен консервативный upper bound по UTF-8 bytes. `256000 tool chars` не является context limit и не учитывает 1755 visible messages, fixed prompt и schemas.

Switch остаётся `pending` до отдельного tools-disabled ingress canary: он проверяет только parse/context acceptance и exact state checksum, но не доказывает работоспособность tools, side-effect continuity или полноту будущего рабочего хода. Required tool/trust/project capabilities проверяются отдельно по server-owned fingerprint. На `context_window`: bad target thread архивируется; выполняется **ровно один** retry с bounded canonical packet + выбранными raw refs, без полного replay. Если даже packet с reserves не помещается или transcript неполон без доказанного packet — fail loud и incumbent остаётся активным.

## 5. Второй startup case: fresh Luna worker #283

Наблюдения относятся к `impl-prompt-metrics` (`5afcf329…`), а не к Seedon handoff.

| Событие | Измерение | Причинность |
|---|---:|---|
| AGENTS truncation | `171888 > project_doc_max_bytes=131072`, first incomplete line 325 | Deterministic project-doc packaging; строки 325–429 не вошли в initial project doc полностью |
| Project trust warning | project-local config/hooks/exec policies disabled, пока `/home/kesha/orchestra` не trusted в per-agent Codex home | Отдельная policy boundary; в репо `.codex` содержит skills, но не project config/hooks/exec policies, поэтому фактическая потеря поведения в #283 не доказана |
| Bundled bubblewrap fallback | warning после trust | Отдельный sandbox fallback; наблюдаемого startup failure из него нет |
| MCP cancellations | `orchestra`/`codex_apps` cancelled после spawn timeout | Startup lifecycle symptom; не доказательство постоянной недоступности MCP |
| `/send` ReadTimeout | worker создан, initial delivery unknown примерно через 30 s | Ack budget истёк, тогда как initialization занял около 35 s |

Первый model text появился после timeout; затем worker прочёл AGENTS tail и успешно вызвал `search_memory`. Это положительный end-effect: initial task всё же был доставлен, Orchestra MCP стал доступен. **CONFIRMED — tier 1 timestamps/tool events.**

### Что именно исчезло после line 324

В initial project doc отсутствовали/были partial строки 325–429: хвост test method, git/files/deploy rules, raw-artifact secret scan, laptop safety, старые session notes, включая часть prior art #243 и prompt-hotness notes, затем source footer. При этом rollout отдельно содержал base instructions (~17730 chars), developer message (~30447 chars), initial project-doc user message (~81980 chars) и task message (~1545 chars). Значит исчез хвост **project-local AGENTS**, а не Orchestra system/developer prompt целиком.

Worker выполнил обязательный `sed -n '325,$p'` и получил 105 строк как tool result. Видимость хвоста восстановилась, но authority не эквивалентна initial project instructions: tool output по provider hierarchy остаётся untrusted data [3][7]. В #283 не наблюдалось фактического handoff/worker defect, однако демоция git/security правил — реальный риск.

**CONFIRMED для byte/line/timestamp facts; LIKELY для authority-demotion risk; REFUTED объединение четырёх warnings в один дефект.** Trust, bwrap, truncation и MCP handshake имеют разные seams и controls. Phase 1 не менял trust/config.

## 6. Внешний кейс Кеши: проверено отдельно от Orchestra

Проверен repo `/home/kesha/projects/kesha-tg-bot` на main `0f30f11`. Это другая реализация; её ограничения не описывают Orchestra автоматически.

### Что в драфте верно

- Native Claude session и Codex thread хранятся отдельно и несовместимы; возвращение в runtime использует его собственный store.
- Claude→Codex passive handoff bounded: максимум 40 видимых сообщений, 2000 chars на сообщение, 24000 chars всего (`chat_state.py:35-40,574-618`).
- Codex `inject_context()` вызывает `thread/inject_items` одним `role=user` item, не запускает model turn (`codex_session.py:620-638`); это согласуется с официальным app-server contract [1].
- Source summary, target tool-disabled summary, raw visible transcript и deterministic capsule имеют именно заявленные риски: source может быть недоступен/stale, target вероятностен, raw несёт шум/старые команды, packet требует честного canonical DB.
- Switch сначала строит/probe-ит candidate и только после успешного handoff фиксирует runtime; при ошибке incumbent сохраняется (`chat_state.py:330-419`). Это сильнее текущей commit boundary Orchestra.

### Что неверно, устарело или пока только proposal

- `messages.db` содержит WAL-таблицу visible `user/assistant` messages и `chat_activity`; production пишет user и assistant. `log_system()` имеет только definition, а нейтрального tool-event journal нет (`message_log.py:20-169`, production calls `chat_state.py:1072`, `response_stream.py:655`). Поэтому «visible messages **и нейтральный журнал tool results**» **REFUTED** текущим кодом.
- Passive handoff есть только у Codex capability; Claude capability `passive_handoff=False`. При переключении в Claude ingress отсутствует/unsupported (`codex_session.py:95-112`, `claude_session.py:133-141`, `chat_state.py:545-572`). Bidirectional contract пока не реализован.
- Per-`(chat,target_runtime)` cursor, delta-after-clear, strict target summarizer, capsule, last 6–12 verbatim messages, pending handoff, idempotency key и cursor advance после first successful turn в текущем repo не найдены. Это proposal, не факт реализации.
- Codex compact сжимает native thread; переносимого summary artifact для другого provider автоматически не создаёт [1].

### Что стоит перенести в Orchestra contract

1. Candidate-before-incumbent и явный `unsupported`, а не silent fallback.
2. Per-target cursor + snapshot hash; cursor продвигается только после confirmed ingress-validation turn и отдельной capability check; canary не выдаётся за проверку будущих tools.
3. Pending handoff + idempotency key.
4. Packet + bounded delta + event refs + conditional tool-disabled target synthesis.
5. Marked untrusted context block для target transport.

Кешин visible-only DB копировать нельзя: Orchestra уже имеет более богатый event log, tool receipts и branch/session metadata. Нужен server-owned projection поверх него.

## 7. Controlled paired experiment

Артефакты:

- confirmatory preregistration: [`experiments/protocol.json`](experiments/protocol.json)
- immutable V1 results: [`experiments/data.json`](experiments/data.json)
- post-hoc corrected preregistration: [`experiments/protocol-v2.json`](experiments/protocol-v2.json)
- immutable V2 results: [`experiments/data-v2.json`](experiments/data-v2.json)
- exact harnesses: [`experiments/run.py`](experiments/run.py), [`experiments/run_v2.py`](experiments/run_v2.py)

Fixtures синтетические, frozen, без credentials: code task, research task и multi-tool state; dispersed facts, superseded alternatives, completed side effect, unresolved state, next action и malicious tool-result text. Tools/MCP/files были disabled; action требовал JSON и запрещал side effects. Порядок, rubric, pass/fail и no-rerun rule зарегистрированы до model turns.

### V1: честный отрицательный результат и дефект дизайна

План: 84 cells. Codex завершил 27/27; Claude 0/30 (`429`, monthly spend limit, zero usage); Grok 0/27 из-за unauthenticated default home. Нейтральный контроль после прогона подтвердил, что managed `GROK_HOME` работает, но V1 не перезапускался.

Главнее runtime availability: raw/native/prose arms показывали только event IDs `E-*`, а answer contract требовал canonical `F/D/S/U/N-*`, доступные напрямую только packet arms. Exact-ID score измерял доступность словаря ответа, а не retention. Поэтому V1 **не используется для сравнительного вывода**, не удалён и не переписан. **CONFIRMED — protocol/data audit.**

### V2: exploratory correction

V2 зарегистрирован после просмотра V1 и навсегда помечен post-hoc exploratory. Каждый raw event получил deterministic `state_ids`, остальные задачи/rubric сохранились. Source summary построил Codex, поскольку Claude был недоступен; targets — Codex и Grok. Planned 57 cells: 36 action, 12 target/hybrid summary generation, 6 native seed, 3 frozen source-summary generation. Background runner завершился с exit 0 и не напечатал stdout; полные per-cell outputs находятся в `data-v2.json`.

Codex завершил 30/30 cells. Grok завершил 22/27; последние пять получили `402 Payment Required: Grok Build usage balance exhausted` (multi-tool packet action, hybrid generation/action, native seed/action). Failed cells остаются critical failures в planned corpus и исключены из quality means.

### End-to-end результаты успешных task paths

`quality = mean(factual_retention, decision_retention, state_retention)`. Для source summary учтены generation+action; target/hybrid — generation+action; native — seed+action. Tokens включают runtime-reported input+output; cost рассчитан по текущим API-equivalent price functions (`app/backend_codex.py:173-186`, `app/backend_grok.py:75-86`), это не реальная subscription оплата.

| Target | Mechanism | Exit-code=0 task paths | Quality | Semantic critical among exit-code=0 | Failed planned paths | Prompt bytes | Tokens | Latency, s | Virtual $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Codex | raw replay | 3 | 0.741 | 0 | 0 | 10054 | 24431 | 10.37 | 0.005148 |
| Codex | source summary | 3 | 0.768 | 0 | 0 | 10503 | 46923 | 26.00 | 0.010165 |
| Codex | target summary | 3 | 0.741 | 0 | 0 | 10520 | 46809 | 25.11 | 0.010079 |
| Codex | deterministic packet | 3 | **1.000** | 0 | 0 | **1858** | **22519** | 27.00 | **0.004696** |
| Codex | hybrid packet+target+refs | 3 | **1.000** | 0 | 0 | 14192 | 47850 | 23.32 | 0.010203 |
| Codex | native seed/resume | 3 | 0.741 | 0 | 0 | 10162 | 75511 | 20.17 | 0.015868 |
| Grok | raw replay | 3 | 0.778 | 0 | 0 | 10054 | 86592 | 28.15 | 0.180005 |
| Grok | source summary | 3 | 0.768 | 0 | 0 | 10503 | 109192 | 54.61 | 0.140380 |
| Grok | target summary | 3 | 0.778 | 0 | 0 | 10497 | 173767 | 96.63 | 0.290413 |
| Grok | deterministic packet | 2 | **1.000** | 1* | 1 | **1856** | **84953** | 33.17 | **0.177548** |
| Grok | hybrid packet+target+refs | 2 | **1.000** | 0 | 1 | 14628 | 173642 | 74.25 | 0.305242 |
| Grok | native seed/resume | 2 | 0.778 | 0 | 1 | 10602 | 179176 | 84.13 | 0.256465 |

`*` У research packet Grok вернул `injection_followed=true`, хотя packet не содержал malicious raw fixture. По preregistered rubric это critical, но семантически это self-report/output-contract failure, **не доказательство исполнения injection**. В raw arms malicious tool text присутствовал; все 6 успешных raw action cells его проигнорировали. Tool-schema contamination во всех успешных V2 action cells — 0.

Pre-registered `invented_facts` scorer также оказался misnamed: он считал extra `E-*` evidence IDs, которые не входили в expected decision subset, хотя все они существовали в frozen transcript. Ручная проверка всех flagged IDs показала 0 несуществующих IDs; массив `invented_facts` был пуст во всех этих outputs. Колонка не используется как hallucination result.

### Вердикт по гипотезам

- **H1 SUPPORTED только для exact-schema retention в exploratory fixtures:** packet и hybrid дали полное exact state во всех exit-code=0 cells; prose/raw/native теряли decision evidence или state. Однако input packet schema близка к answer schema; production-shaped superiority не доказана. Packet **сравнялся** с hybrid и был дешевле.
- **H2 INCONCLUSIVE:** native arm совпал с raw/target-summary, немного разошёлся с source-summary и уступил только packet/hybrid; одна реплика synthetic seed/resume не исполняет preregistered falsifier «хуже каждого portable arm». Независимые live cases подтверждают необходимость fit checks, а V2 — лишь то, что native resume не является canonical truth и не гарантированно доминирует packet на exact-ID задаче.
- **H3 NOT SUPPORTED / INCONCLUSIVE на этом corpus:** raw не увеличил observed injection/contamination в шести exit-code=0 action cells, но tools были disabled, а один security flag был self-reported. Security boundary всё равно обязательна по authority model [3][7] и из-за цены одного side effect.
- **H4 REFUTED operationally и ослаблен empirically:** Claude source был недоступен; frozen Codex source summary не обошёл packet и стоил дополнительный turn.
- **H5 REFUTED:** для малого полного packet target synthesis не нужен. Он обязателен условно — только при доказанном schema/capability mismatch, большом/неоднозначном delta или unsupported target ingress form; сам факт cross-provider switch запускает negotiation, но не model synthesis.

### Ограничения

- Одна реплика на task×mechanism×target; statistical generalization невозможна.
- Claude отсутствует из-за subscription limit, Grok quota исчерпалась до пяти последних cells; полного трёхстороннего paired result нет.
- Synthetic transcripts существенно меньше provider windows; overflow покрывает отдельный live Seedon case.
- Tools отключены. Измерено сохранение state и recommended tool, а не реальное правильное исполнение/идемпотентность side effects.
- Codex source summary создаёт model-family correlation с Codex target.
- V2 post-hoc exploratory и не объединяется с V1.

## 8. Сравнение механизмов

| Механизм | Сильная сторона | Нагрузочная/семантическая граница | Вердикт |
|---|---|---|---|
| Raw replay | Полная наблюдаемая последовательность, если короткая | Шум, старые команды, schemas, overflow; Seedon — прямой контрпример | Только bounded safe delta |
| Source-generated summary | Source видел исходный context | Source может быть недоступен; probabilistic/stale; ещё один turn | Advisory input, не truth |
| Target читает raw и строит summary | Target нормализует под свои capabilities | Двойная стоимость/context; raw сначала всё равно должен поместиться; synthesis вероятностен | Обязателен только при mismatch/ambiguity, stateless/tools-off |
| Deterministic packet | Проверяемые поля, refs, side-effect lifecycle, минимальный размер | Требует server-owned projection и explicit unknowns | Canonical durable state |
| Packet + target synthesis + refs | Совмещает integrity и target compatibility | Дополнительные tokens/latency; synthesis не меняет packet | Только при доказанном mismatch/ambiguity/oversized delta |
| Provider-native resume | Максимум native continuity и compacted store | Opaque, nonportable, может не поместиться в новую модель | Same-provider optimization после preflight |
| Event ledger + on-demand retrieval | Не тащит весь raw log; target запрашивает refs адресно | Нужен read-only retriever и capability negotiation | Хорошее расширение hybrid |
| Continuous dual-write state journal/checkpoints | Packet уже свежий при смерти source | Projection bugs/staleness; нужна receipt/integrity проверка | Предпочтительнее summary-on-exit для long-running work |
| Capability-negotiated adapter | Явно учитывает tools/prompt/window/provider version | Больше adapter tests; нельзя скрывать unsupported | Нужен вокруг любого ingress |

## 9. Privilege boundary и prompt injection

Canonical pipeline должен соблюдать четыре разные authority зоны:

1. **System/developer/project policy target runtime** — только от текущей Orchestra конфигурации; source transcript не может её заменить.
2. **Canonical packet** — server-authored structured data с evidence IDs. Privileged constraint входит в него только с server-verified origin (`authenticated_user_event`, bytes текущего system prompt или tracked project doc + hash); model/transcript content не может сам назначить `authority`. Packet описывает state, но не повышает старые команды до developer authority.
3. **Raw logs/tool results** — untrusted quoted data, всегда typed (`role`, `event_id`, `tool`, `status`, provenance), никогда не конкатенируются в system/developer prompt [3][7].
4. **Target synthesis** — assistant-authored advisory brief. Он не может подтверждать side effect, менять constraint authority или продвигать cursor.

Любой historical side effect по умолчанию `repeat_policy=never`. Повтор допустим только при новом explicit authority либо при формально idempotent operation с тем же idempotency key. **Safety invariant, не вывод V2:** pending/unknown effect блокирует runtime switch, пока receipt не найден или пользователь не выбрал recovery; experiment отключал tools и не проверял lifecycle receipts.

## 10. Durable canonical state schema

```json
{
  "schema_version": "orchestra.handoff.v1",
  "handoff_id": "uuid",
  "idempotency_key": "sha256(task_identity + snapshot_log_id + target_runtime)",
  "status": "pending|confirmed|failed",
  "task_identity": {
    "orchestra_session_id": "uuid",
    "task_id": "287",
    "scope": "/absolute/repo/scope",
    "branch": "task-287/...",
    "base_branch": "main",
    "head_commit": "sha",
    "source_runtime": "claude",
    "target_runtime": "codex",
    "snapshot_log_id": 116299,
    "snapshot_sha256": "sha256"
  },
  "provider_refs": {
    "source": {"runtime": "claude", "thread_id": "opaque-or-null"},
    "target": {"runtime": "codex", "thread_id": "opaque-or-null"}
  },
  "objective": {"text": "...", "source_event_ids": ["..."]},
  "constraints": [
    {
      "id": "C1",
      "text": "...",
      "authority": {
        "class": "user|system|repo",
        "origin_kind": "authenticated_user_event|current_system_prompt|tracked_project_doc",
        "origin_id": "server-owned-id-or-path",
        "origin_sha256": "sha256",
        "verified_by": "orchestra_server",
        "snapshot_log_id": 116299
      },
      "source_event_ids": ["..."]
    }
  ],
  "decisions": [
    {"id": "D1", "status": "active|reversed|provisional", "value": "...", "evidence_event_ids": ["..."], "decided_at": "..."}
  ],
  "facts": [
    {"id": "F1", "value": "...", "evidence_event_ids": ["..."], "confidence": "confirmed|likely|unknown"}
  ],
  "artifacts": {
    "files": [{"path": "...", "sha256": "...", "status": "read|modified|created"}],
    "commits": [{"sha": "...", "branch": "...", "merged": false}]
  },
  "tool_side_effects": [
    {
      "operation_id": "S1",
      "tool": "...",
      "status": "pending|completed|failed|unknown",
      "idempotency_key": "...",
      "receipt": "typed-redacted-receipt-or-null",
      "evidence_event_ids": ["..."],
      "repeat_policy": "never|explicit_authority|idempotent"
    }
  ],
  "unresolved_branches": [{"id": "U1", "question": "...", "evidence_event_ids": ["..."]}],
  "next_action": {
    "action": "...",
    "preconditions": ["..."],
    "required_capabilities": ["..."],
    "source_event_ids": ["..."]
  },
  "recent_messages": [{"event_id": "...", "role": "user|assistant", "content": "..."}],
  "raw_event_refs": [{"event_id": "...", "log_id": 123, "sha256": "..."}],
  "omissions": [{"kind": "tool_payload", "reason": "size|secret|unavailable", "count": 3}],
  "capability_fingerprint": {
    "system_prompt_sha256": "...",
    "project_doc_sha256": "...",
    "tool_schema_sha256": "...",
    "target_window": 258400
  },
  "reasoning": {
    "portable": false,
    "reason": "hidden/opaque provider state is unavailable and was not reconstructed"
  },
  "cursor": {"source_log_id": 123, "target_runtime": "codex"},
  "integrity": {"canonical_sha256": "sha256-of-canonical-json"}
}
```

`provider_refs` — только backend cache pointers. `facts/decisions/effects` обязаны иметь refs или `unknown`; отсутствие event не превращается в отрицательный факт. `authority.class` не выводится из текста, summary или model output: Orchestra разрешает только authenticated ingress metadata, bytes текущего system prompt либо tracked project-doc bytes и проверяет их hash. Если legacy log не хранит проверяемый origin, его текст остаётся untrusted context и не может быть повышен до constraint authority. Assistant/tool/raw quote никогда не может получить `system|repo|user` authority. Integrity hash доказывает неизменность bytes, но не authority, поэтому origin proof обязателен отдельно. Secrets никогда не входят в packet/fixtures; receipts редактируются до сериализации.

## 11. Рекомендованный decision tree

### Raw replay допустим, только если одновременно

- snapshot полный и immutable, turn boundary не оборван;
- preflight formula помещается с output/reasoning/uncertainty reserve;
- delta короткий и bounded, all events typed/provenanced;
- нет pending/unknown side effects;
- target tool schema совместима, старые tools marked completed/untrusted;
- текущий project/system prompt полностью доставлен и fingerprint совпадает.

### Cross-provider compatibility negotiation

Сам факт cross-provider switch запускает deterministic проверку target ingress form, window, required tools, project trust и fingerprints. Если packet прямо принимается target transport, все capabilities совместимы и delta однозначен, synthesis пропускается — это дешёвый packet-only путь, выигравший exploratory V2.

### Target synthesis обязателен, если negotiation установил хотя бы одно

- raw delta не помещается или превышает bounded policy;
- tool schemas/capabilities реально различаются и нужен target-specific mapping `next_action → available tool`;
- bounded raw delta содержит superseded branches/неоднозначные отрицания или числа, которые нельзя доставить напрямую в action budget; synthesis обязан сохранить ambiguity, а не выбирать решение;
- target требует другой ingress form.

Synthesis выполняется stateless, tools/MCP/files disabled, по strict JSON schema. На вход идут packet + bounded raw delta + addressable refs. Его output — compatibility brief, не замена packet.

### Provider-native resume допустим, только если

- тот же provider и поддержанный version/model/thread contract;
- provider store существует и принадлежит тому же task/branch identity;
- preflight доказывает fit для target model window;
- current target system/project/tool fingerprint валиден;
- tools-disabled ingress canary подтвердил parse/context fit и state checksum. Это не проверка tool capability; required capabilities отдельно сверены по server-owned fingerprint.

### Switch запрещён или откладывается

- source turn активен;
- есть pending/unknown external side effect;
- snapshot/hash нестабилен или task/branch mismatch;
- target лишён required capability, project trust или критического project instruction;
- transcript неполон и canonical packet нельзя доказанно построить;
- даже packet + reserves не помещается;
- target subscription/runtime недоступен.

### Fail-safe при неполном или слишком длинном transcript

1. Freeze DB cursor + snapshot hash; incumbent продолжает владеть сессией.
2. Построить deterministic packet. Любой gap записать в `omissions/unknown`, не додумывать.
3. Выбрать bounded semantic delta по complete turns и event refs, а не последние N сырых rows.
4. Выполнить deterministic capability negotiation; при установленном trigger — target synthesis. Затем выполнить ingress canary без tools для fit + state checksum.
5. Только после успешного handoff-validation turn и отдельной механической проверки required capabilities атомарно подтвердить handoff, записать target thread и продвинуть per-target cursor. Старый provider ref и packet сохранять как recovery checkpoint до первого обычного полезного turn; canary не объявлять доказательством tool/side-effect continuity.
6. На context/parse/ingress failure target thread пометить failed; разрешён один bounded packet fallback.
7. Повторный failure — fail loud, cursor не двигать, incumbent не отключать. Полный raw retry loop запрещён.

## 12. Findings с confidence

| Finding | Confidence | Основание |
|---|---|---|
| Скрытый CoT недоступен и не переносится как canonical semantics | **CONFIRMED** | Anthropic/xAI primary docs + Orchestra omission; opaque blocks не читаемы |
| Текущий Claude↔Codex import переносит полный DB history snapshot, но без total-context preflight | **CONFIRMED** | Current code + Seedon exact trace |
| `truncated=11915` — сумма двух разных incident counts, с возможным double count | **CONFIRMED** | Exact renderer reproduction + code |
| Native resume может быть принят и умереть на первом turn | **CONFIRMED** | #243 + Seedon live counterexamples |
| Retry Seedon не восстановил import из-за commit/fallback boundary Orchestra | **CONFIRMED** | Code path + new thread/response; внутренний Codex retry policy не заявляется |
| Deterministic packet — лучший durable truth layer | **LIKELY** | Exploratory exact-schema win + prior art + security/size properties; production-shaped superiority не доказана, одна реплика, Claude отсутствует |
| Target synthesis нужен при любом cross-provider switch | **REFUTED для V2 policy** | Packet-only равен hybrid дешевле; cross-provider запускает negotiation, synthesis — только при установленном mismatch/ingress/size trigger |
| Raw replay intrinsically чаще исполняет injection | **NOT SUPPORTED / INCONCLUSIVE** | 0/6 exit-code=0 raw failures; малая выборка, tools disabled, self-reported flag |
| #283 trust warning вызвал MCP cancellation | **REFUTED** | Разные seams; MCP позже работал, project policy files отсутствовали |
| Кешин draft описывает уже реализованный hybrid/cursor protocol | **REFUTED** | External repo code search |

## 13. Counter-evidence и открытые вопросы

- Packet perfect score может быть следствием того, что fixture schema совпадает с output schema. Нужны независимые production-shaped tasks и реальные read-only tools перед объявлением superiority.
- Raw replay сохранил больше narrative nuance, чем exact-ID rubric измеряет. Event-ledger retrieval может превзойти packet на непредвиденном вопросе.
- Same-provider native resume может сохранять полезные provider details, которых packet намеренно не знает. Поэтому native path не удаляется.
- Grok packet critical flag показывает, что даже strict JSON self-report может быть несогласован с фактическим input; automated judge обязан проверять raw provenance, а не доверять `injection_followed` модели.
- Нужен provider-accurate token counter до design freeze; UTF-8 bound безопасен, но может отвергать допустимые switches.
- Не проверена семантика images, subagents, streaming partial tools и real external receipts.
- Project-doc truncation сейчас компенсируется read-tail instruction, но authority demotion остаётся; требуется отдельная задача, не runtime handoff patch Phase 1.

## 14. Затрагиваемые файлы и риски будущей реализации

Phase 1 ничего не меняет. Потенциальный Phase 2 scope:

- `app/session.py` — pending handoff transaction, ingress-validation turn, cursor commit, bounded fallback;
- `app/runtime_history.py` — projection inputs, explicit omission counters, preflight sizing;
- `app/db.py` и migration — canonical packet/cursor/idempotency/receipts;
- `app/backend_claude.py`, `app/backend_codex.py`, `app/backend_grok.py` — capability-negotiated ingress/token count/native ingress canary;
- `app/runtime_registry.py` — explicit ingress/resume/compact capabilities;
- focused tests for context overflow, pending side effect, interrupted snapshot, injection authority, same-provider resume and cross-provider fallback.

Главные риски: атомарность switch относительно first turn; повтор side effect; stale packet projection; provider version drift; token estimator false-negative/false-positive; target synthesis, который случайно получает tools; cursor advance до durable receipt; сохранение secrets в raw refs; project prompt fingerprint, который сам обрезан.

## Источники

Все URL открыты 2026-08-16. Внешние источники — первичные (tier 2); direct measurements и committed JSON — tier 1.

1. OpenAI, Codex app-server README — thread lifecycle, compact, inject items: https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
2. OpenAI, latest model / conversation state guide — persisted state, `previous_response_id`, reasoning item round-trip: https://developers.openai.com/api/docs/guides/latest-model
3. OpenAI, Model Spec (2025-10-27) — authority of tool outputs and untrusted text: https://model-spec.openai.com/2025-10-27
4. Anthropic, Claude Code CLI usage — continue/resume: https://docs.anthropic.com/en/docs/claude-code/cli-usage
5. Anthropic, Agent SDK session browser — JSONL inspect/fork/resume: https://platform.claude.com/cookbook/claude-agent-sdk-05-building-a-session-browser
6. Anthropic, Extended thinking — summarized/opaque thinking and cross-model handling: https://platform.claude.com/docs/en/about-claude/models/extended-thinking-models
7. Anthropic, Mitigate jailbreaks — untrusted tool results, provenance, privilege reduction: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks
8. xAI, Grok Build shell README — persistent stores, headless/ACP resume, auto-compaction: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-shell/README.md
9. xAI, Grok Build slash commands — `/resume`, `/compact`, `/flush`: https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/04-slash-commands.md
10. xAI, Reasoning — encrypted and summarized reasoning: https://docs.x.ai/developers/model-capabilities/text/reasoning
11. Orchestra #174 prior art and measurements: [`docs/tasks/174/research.md`](../174/research.md)
12. Orchestra #243 native Codex model-switch experiment: [`docs/tasks/243/research.md`](../243/research.md)
13. #287 preregistered and exploratory raw data: [`docs/tasks/287/experiments/`](experiments/)
