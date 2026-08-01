# #116 — свежесть доставленного агенту состояния

Дата измерений: 2026-08-01. Это Phase 1: runtime-код не менялся. Ниже есть
кандидатные тикеты с ценой и зависимостями по прямому запросу задачи, но это ещё не
Phase 2 plan и не разрешение на реализацию.

## Короткий ответ

Проблема здесь не гипотетическая. На read-only снимке live DB в
`2026-08-01T07:57:26Z` было 81 non-archived session:

- у **28 из 33** существующих живых Claude worker-worktree pipeline skills
  доказанно расходились с текущим источником: отсутствующий/старый untracked
  managed skill или untracked orphan; **6** из них всё ещё держали удалённый
  `self-analysis`. У 32 worktree роль требовала хотя бы один skill; один
  `researcher` не имел skill contract;
- у **54 из 81** sessions сохранённый `template_hash` не равнялся текущему hash
  base/role template; этот hash не покрывает память, `AGENTS.md` и bytes skills,
  поэтому это нижняя, а не верхняя граница общего prompt drift;
- среди **30** живых Codex-worktree `AGENTS.md` отсутствовал у 2 и расходился с
  локальным `CLAUDE.md` ещё у 5. Ещё 28 отличались от `scope/CLAUDE.md`, но это
  только at-risk upper bound: часть различия может быть намеренным состоянием
  feature branch;
- canonical worker-memory существовала для 3 sessions; **1 из 3** была точно не
  доставлена. Это `prompt-engineer`: текущий `docs/workers/prompt-engineer.md`
  содержит 12,487 chars, а `<worker-memory>` в сохранённом prompt отсутствует.
  Ещё один worker имел новое worktree-local memory, которой ещё нет в canonical
  scope.

Изменения можно доставлять без рестарта Orchestra. Минимальный рабочий механизм —
проверять content hash в уже централизованной точке следующего send, ничего не
добавлять при совпадении и при расхождении делать одно из двух:

1. явно append-only factual addition — один раз добавить к следующему user turn
   короткий platform envelope и только изменившийся payload/path. Текущая
   worker-memory может содержать правила, поэтому автоматически относить её сюда
   нельзя;
2. worker-memory, authoritative instruction/`AGENTS.md`/skill-catalog change — перед следующим
   idle turn reconnect/resume только backend с тем же native session/thread id и
   новым system/developer prompt. Если reload не удался, вернуть явный
   `stale_state`, а не начинать strict/new turn молча. Для legacy session, где
   historical delivery недоказуема и T2 ещё недоступен, rollout временно разрешает
   compatibility-turn, но повторяет warning agent+parent и никогда не помечает hash
   applied.

Полный prompt нельзя переливать каждый ход: у 81 live sessions его размер сейчас
`4,765 / 19,213 / 41,542 / 43,842` chars (`min/median/p95/max`), то есть примерно
`1.2k / 4.8k / 10.4k / 11.0k` tokens по используемой в Orchestra эвристике
`chars/4`. Один turn на всю fleet — около **455k лишних tokens**. Hash check при
совпадении стоит **0 model tokens**; три полных последовательных scan по 83
sessions заняли `13.828 / 11.605 / 9.833 ms`, в среднем `0.12–0.17 ms/session`.

Для Codex исходная предпосылка задачи нуждается в поправке: текущий backend — не
новый CLI process/thread на каждый turn. Один persistent app-server держит один
thread; `turn/start` создаёт только следующий turn. Установленная schema разрешает
`developerInstructions` на `thread/start|resume`, но не на обычном `turn/start`.
Значит дешёвый suffix можно добавить к следующему user input, а authoritative
developer refresh требует reconnect/resume. Применение нового значения provider-ом
к существующему Codex thread ещё **не доказано**: до отдельной provider-пробы такой
refresh нельзя отмечать delivered. Для Claude прямой эксперимент подтвердил путь:
`--resume` вместе с новым `--append-system-prompt` сохранил session UUID и применил
новый system prompt.

Цена authoritative refresh реальна. В controlled Claude/Haiku run с тем же session
UUID:

```text
RUN 1 ALPHA: cache_read=0,    cache_create=6841
RUN 2 ALPHA: cache_read=6841, cache_create=689
RUN 3 BETA:  cache_read=0,    cache_create=8494
```

То есть unchanged resume прочитал старый prefix, а изменение system append обнулило
cache read и пересоздало prefix. Делать это каждый turn нельзя; делать один раз при
реальном hash mismatch — честная цена authoritative change. Для Sol cached input в
предыдущем measured research стоил в 10 раз дешевле fresh input, а weighted live
cache ratio был 96.08% на 1,969 calls [4]. User-tail delta сохраняет старый exact
prefix eligible for cache; системный rewrite меняет ранний prefix и дороже.

RAG hook не мёртв: он фактически запускается. Но stale window и отсутствие статуса
подтверждены. В live `vec.db` сначала было 4 stale SHA из 412 Orchestra files, затем
в ходе исследования осталось 2 из 413 (`BUGS.md` и
`docs/workers/prompt-engineer.md`) — backfill догоняет постепенно, а search всё это
время возвращает только `results`. В journal merge `bizdev` завершился в 14:37:37,
а seedon backfill читал файлы в 14:42:20, через 4m43s. С 2026-07-20 journal содержит
269 merge requests, 0 ручных `/api/memory/reindex` и 0 logged
`RAG backfill after merge failed`. Значит сначала нужен visible watermark, отдельно
— retained/coalesced scheduler.

Typed MCP errors — самый дешёвый независимый срез. 37 HTTP calls в 34 tools проходят
через одну `_api`, но 30 tools превращают failure в обычную строку с
`isError:false`; status, retry-after, type и request id теряются. Классификацию можно
закрыть централизованно в `_api` + одном MCP result adapter. Точечно остаются только
partial success `spawn_worker` и optional role-icons; mutating POST timeout нельзя
автоматически объявлять safe-to-retry.

## 1. Вопрос, hypotheses и falsifiers

**Context.** Orchestra держит persistent Claude/Codex sessions, prompt собирает при
spawn/load, skills и `AGENTS.md` материализует другими путями, а RAG и MCP HTTP
boundary отдают derived state агенту.

**Change under test.** Content-bound freshness: сравнить источник с последним
доставленным поколением, а расхождение либо доставить, либо показать как stale.

**Baseline.** Текущий birth/load/reconnect snapshot без post-change signal.

**Outcome.** Число реально расходящихся live sessions; model tokens и cache effect;
время stale RAG window; доля MCP failures с machine-readable decision fields.

Рассмотрены конкурирующие hypotheses:

1. **H1: divergence редок, поэтому отдельный механизм не окупится.**
   Falsifier: заметная доля live sessions имеет byte/hash mismatch. H1 refuted:
   28/33 Claude worker-worktree имеют untracked managed skill drift и 54/81
   template fingerprints stale.
2. **H2: изменения можно доставить только service/session restart.**
   Falsifier: same native id принимает обновлённый authoritative prompt. H2
   **refuted для Claude** direct measurement. Для Codex schema подтверждает только
   request shape reconnect/resume; применение provider-ом остаётся UNCERTAIN, и
   fallback пока — явный `stale_state`, а не ложная отметка delivered.
3. **H3: full prompt injection на каждый turn проще и достаточно дёшев.**
   Falsifier: measured prompt volume или cache invalidation несоразмерны частоте
   изменения. H3 refuted: median ≈4.8k tokens/turn, fleet ≈455k tokens/round;
   changed Claude system prefix дал zero cache read.
4. **H4: merge RAG trigger вообще не запускается.**
   Falsifier: backfill activity после merge без ручного reindex. H4 refuted direct
   journal/in-process route evidence. Reliability остаётся weak, но path живой.
5. **H5: typed errors требуют править десятки tools по одному.**
   Falsifier: одна boundary видит transport/status/body и FastMCP adapter может
   создать `isError`. H5 mostly refuted: classification central; две operations
   требуют semantic catch из-за partial/optional outcome.

## 2. Метод и raw measurements

### 2.1 Live prompt-state snapshot

Live `data/orchestra.db` открыт read-only. Live = status
`idle|running|waiting|starting`; archived rows исключены. Для каждого row:

- current template hash вычислен текущим `prompt_template_hash(role)`;
- Claude expected skills взяты из `session.pipeline` (`''` нормализован к
  `default`) и resolved persisted role. На снимке 80/81 sessions уже имели
  `pipeline=default`, одна legacy row — пустой alias default; среди измеренных
  worker-worktree non-default pipeline не было. Required files сравнены
  byte-for-byte; tracked project-owned mismatch отмечен отдельно, extras считались
  stale только если untracked;
- Codex disk mirror сравнивался `worktree/AGENTS.md ↔ worktree/CLAUDE.md`; сравнение
  со `scope/CLAUDE.md` записано отдельно как upper bound branch drift;
- canonical memory выбиралась тем же priority `name.md → role.md`, что manager, и
  сравнивалась с `<worker-memory>` в persisted `system_prompt`;
- hash CPU benchmark перечитывал relevant source+copy для каждой session без
  dedupe, три итерации.

Raw final snapshot:

```text
UTC 2026-08-01T07:57:26.327352+00:00
ACTIVE 81 CLAUDE 50 CODEX 31
TEMPLATE_STALE 54
CLAUDE_SKILL 33 STALE 28 SELF_ANALYSIS_LIVE 6
CODEX_AGENTS 30 MISSING 2 LOCAL_MISMATCH 5 SCOPE_MISMATCH 28
MEM_CANON_SESSIONS 3 CANON_STALE 1 WT_STALE 2
```

Повторный adversarial пересчёт тем же live DB после замечания Codex разделил
ownership явно:

```text
ACTIVE_CLAUDE_NON_ORCH 35
EXISTING_NAMED_WORKTREES 33
EXPECTED_SKILLS 32
STALE 28
WITH_UNTRACKED_MANAGED_EVIDENCE 28
ONLY_TRACKED_AMBIGUOUS 0
```

У одного из этих 28 worktree был также changed tracked required skill, но в той же
сессии были untracked managed mismatches; он не добавил ни одной сессии к итогу.
Две Claude rows не имели существующего именованного worktree и не входят в
знаменатель. Поэтому 28/33 — lower bound materialized worker drift, а не upper bound
от project-owned файлов.

Raw hash timings (более ранний snapshot 83 sessions; no dedupe):

```text
HASH_SCAN_MS 1 13.828
HASH_SCAN_MS 2 11.605
HASH_SCAN_MS 3 9.833
```

Для fail-closed RAG watermark отдельно измерена цена чтения текущего Git HEAD всех
11 namespaces live index (три последовательных прохода):

```text
REV_PARSE 1 255.238 ms projects=11 ok=11
REV_PARSE 2 199.328 ms projects=11 ok=11
REV_PARSE 3 17.501 ms projects=11 ok=11
```

Полный dirty-tree check оказался заметно дороже и почти всегда срабатывает
(`1391.739 / 58.448 / 62.110 ms`, dirty 9/11), поэтому минимальный watermark ниже
доказывает именно commit freshness после merge, а не выдаёт working-tree freshness.

После Codex counterexample измерены две backfill-only проверки тем же include
contract (`*.md`, exclusions как в `_walk_files`) для всех 11 namespaces:

```text
RAG_DIRTY_CHECK 1 386.839 ms projects=11 ok=11 dirty=3 changed_paths=31
RAG_DIRTY_CHECK 2 75.024 ms  projects=11 ok=11 dirty=3 changed_paths=31
RAG_DIRTY_CHECK 3 76.215 ms  projects=11 ok=11 dirty=3 changed_paths=31
CONTENT_MANIFEST 1 4062.220 ms projects=11 files=3719 bytes=30794425
CONTENT_MANIFEST 2 428.173 ms  projects=11 files=3719 bytes=30794425
CONTENT_MANIFEST 3 444.926 ms  projects=11 files=3719 bytes=30794425
```

Exact content-manifest слишком дорог для каждого search, но один verification pass
в конце уже минутного backfill добавляет доли секунды warm (до 4.1 s cold на все 11)
и связывает `indexed_head` с реально прочитанными bytes.

Важно: точное содержимое уже загруженного Codex/Claude model prompt нигде не
fingerprint-ится. Поэтому disk mismatch даёт доказанный lower bound, но disk match
не доказывает, что persistent model session прочитала свежие bytes. Это и есть
observability gap, которую должен закрыть delivered hash.

### 2.2 Claude same-session authoritative refresh

Критерий задан до controlled run:

- same append + same UUID должен дать cache read;
- changed append + same UUID должен вернуть новый codename и снизить/обнулить
  cache read;
- иначе `--resume + --append-system-prompt` не является рабочим hot refresh.

Команда запускала bundled Claude Agent SDK CLI 0.2.114 в temp cwd, model `haiku`,
`setting-sources=local`, tools disabled, proxies только из Orchestra `.env`.

Raw selected JSON fields:

```text
RUN 1 RESULT ALPHA. SESSION_OK True CACHE_READ 0 CACHE_CREATE 6841 INPUT 9 OUTPUT 133
RUN 2 RESULT ALPHA. SESSION_OK True CACHE_READ 6841 CACHE_CREATE 689 INPUT 9 OUTPUT 400
RUN 3 RESULT BETA. SESSION_OK True CACHE_READ 0 CACHE_CREATE 8494 INPUT 9 OUTPUT 1654
```

Две предварительные независимые пары тоже сохранили UUID и во втором ответе явно
видели generation 2; их usage:

```text
pair 1: first create=6844/read=0; second create=10373/read=0
pair 2: first create=6906/read=0; second create=8345/read=0
```

Setup attempt с relative CLI path не дошёл до provider и завершился дословно:
`FileNotFoundError: [Errno 2] No such file or directory:
'.venv/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude'`. Повтор с
absolute path дал результаты выше.

### 2.3 Codex current protocol

Проверены текущий `app/backend_codex.py`, официальный app-server manual и schema,
сгенерированная установленным binary:

```text
codex app-server generate-json-schema --out /tmp/codex-schema-116.HZ6OzH
```

`ThreadStartParams` и `ThreadResumeParams` содержат nullable
`developerInstructions`; root properties `TurnStartParams` этого поля не содержат.
Manual также определяет one persistent thread, turns и `thread/inject_items` [3].
Текущий Orchestra действительно передаёт developer instructions только на
`thread/start|resume`, а `turn/start` — user input/model/effort
(`app/backend_codex.py:242-306`).

Израсходовать оставшиеся 11% Codex quota на provider experiment было бы плохим
tradeoff перед обязательным research review. Поэтому применение changed
`developerInstructions` на resume — **UNCERTAIN: protocol accepts the field, provider
behavior not measured here**; user-tail injection — **CONFIRMED by local request
shape**.

### 2.4 RAG trigger and live lag

Route test со всеми merge/TM/RAG dependencies patched, без filesystem/DB mutation:

```text
{'merge_ok': True,
 'response_returned_before_task': True,
 'backfill_calls': ['/tmp/fake-scope']}
```

Journal measurement обновлён во время parent verification:

```text
since 2026-07-20: merge_requests=269 reindex_requests=0 backfill_failures=0
2026-07-28 14:37:37+07:00 POST /api/sessions/bizdev/merge 200
2026-07-28 14:42:20+07:00 RAG backfill_files seedon reads/skips (+4m43s)
```

Live SHA comparison `files.sha256` с текущими bytes Orchestra:

```text
first snapshot: 4 mismatches / 412 indexed files
later snapshot: 2 mismatches / 413 indexed files, 0 missing
remaining: BUGS.md; docs/workers/prompt-engineer.md
```

Это один полезный natural experiment: index реально догоняет, но потребитель не
видит ни `indexing`, ни partial skips, ни target/indexed generation.

### 2.5 MCP error boundary

Статический аудит нашёл 37 `_api` calls в 34 MCP tools. Direct protocol/mock
measurements:

```text
HTTP failure from send_message:
  content="Send failed: boom", isError=false
empty httpx.ReadTimeout:
  isError=true, text="Error executing tool send_message: ", no type/fields
send_file ReadTimeout catch:
  typed human text, isError=false
429 JSON + Retry-After:24 + X-Request-ID:
  _api returned only {"error": "<raw body>"}
```

Текущая `_api` на non-2xx оставляет только `r.text`; на non-JSON 2xx возвращает
success-shaped error dict; FastMCP при exception строит текст из `str(e)`. Поэтому
пустой `httpx.ReadTimeout('')` закономерно превращается в пустую причину
(`app/mcp_stdio.py:76-96`; installed `mcp/server/lowlevel/server.py:468-472,
538-576`).

## 3. Проблема 1 — что реально работает

### 3.1 Почему текущее состояние протухает

Сейчас существуют три delivery moments:

1. Claude skills копируются только в spawn path
   (`app/manager.py:500-524`, `app/prompting.py:116-140`). Reconnect не вызывает
   этот helper; exact-set/prune нет. Сам sync принадлежит #94 и не входит в #116.
2. `sync_agents_md()` вызывается только при создании backend
   (`app/session.py:765-779`). Persistent backend не пересоздаётся на file change;
   сохранённого hash bytes, которые app-server уже прочитал, нет.
3. Worker memory читается manager только на spawn/load
   (`app/manager.py:440-445, 969-986, 1139-1160`). Оба compact paths живут в
   `AgentSession` и не вызывают `_load_worker_memory`.

В коде уже есть почти нужный transport: после load один раз prefix-ится полный
`_current_prompt`, сравнивается старый `template_hash`, после accepted send ставится
`_prompt_injected=True` (`app/session.py:657-757`). В live logs найдено 79 таких
injections. Дефект — boolean/one-shot и неполный hash, а не отсутствие способа
добавить server note к следующему turn.

`prompt_template_hash()` тоже уже существует, но фактически хэширует только default
`base.md + role_prompt_file(role)`; вопреки docstring, skill bodies и worker memory
в digest не входят (`app/prompting.py:93-103`). Создавать новый synchronization
framework не нужно: заменить one-shot boolean сравнением небольших component
fingerprints at send boundary. Но один `delivered_hash` недостаточен: observation
и применение на разных priority нельзя смешивать. Нужны как минимум
`observed_hash` и отдельный `authoritative_applied_hash`; user-priority notification
никогда не продвигает второй. #94 гарантирует только exact-set skill bytes, не hash:
catalog digest после #94 вычисляет сам #116. `AGENTS.md` и worker-memory имеют свои
digests, чтобы изменение одного компонента не cold-reload-ило всё без причины.

### 3.2 Claude vs Codex

| Runtime | Текущее состояние | Дешёвый next-turn delta | Authoritative refresh без Orchestra restart |
|---|---|---|---|
| Claude | Один persistent SDK client; system append задаётся при connect. Current backend при `resume_id` вообще не передаёт `system_prompt` (`app/backend_claude.py:145-173`). | Prefix к следующему user message работает уже сейчас; старый cache prefix остаётся перед новым suffix. | Да: disconnect client → resume same UUID с текущим `--append-system-prompt`. Direct run применил BETA, UUID сохранился. Changed early prefix дал zero cache read. |
| Codex | Один persistent app-server и thread; новый только turn, не process/thread. | `turn/start.input` либо `thread/inject_items`; текущий backend уже умеет первый путь. Это user priority. | Protocol разрешает reconnect → `thread/resume(developerInstructions=...)` с тем же thread id. Provider effect не измерялся; schema/manual подтверждают только request contract. До provider-пробы — experimental, hash не advance-ится. |

User-tail delivery достаточна для явно append-only factual additions, но текущая
`<worker-memory>` не является таким каналом: в ней лежат и факты, и предписывающие
уроки. Удаление или изменение старого правила в system prompt невозможно отменить
user note. Автоматически классифицировать prose как «безопасный факт» — уже новый
ненадёжный механизм, поэтому worker-memory по умолчанию authoritative. Для неё и
остальных authoritative layers нужен provider reconnect/resume; если он не удался
или для Codex ещё не доказан, strict/new turn не стартует и agent/parent получает
`stale_state`. Единственное rollout-исключение — legacy unknown/stale до появления
verified T2: turn разрешён с повторяемым warning agent+parent, без продвижения
applied hash.

### 3.3 Варианты и цена

| Вариант | Model tokens | Cache effect | Покрытие | Verdict |
|---|---:|---|---|---|
| Полный prompt каждый turn | median ≈4.8k, p95 ≈10.4k; fleet ≈455k/round | Системная перезаливка меняет ранний prefix; user-copy ещё и навсегда раздувает history | Доставляет bytes, но дорого и конфликтует с priority | **REFUTED** |
| Hash compare, no mismatch | **0** | Нет изменения request | Обнаружение без model cost | **Брать** |
| Hash mismatch → маленький envelope + changed payload/path | Envelope ориентировочно 50–150 tokens; payload только один раз. Текущая memory prompt-engineer ≈3.1k tokens, full AGENTS median ≈5.8k | Стабильный old prefix eligible; добавляется tail | Явно append-only facts + visible warning; не заменяет старое правило | **Брать только для low-priority data** |
| Hash mismatch → backend reconnect/resume with authoritative prompt | Нет дублирующего user payload, но changed system prefix cold-fills; measured Claude `read 6841→0`, `create 689→8494` | One-time cold suffix/prefix rebuild; same native id | Contradictory role rules, `AGENTS.md`, native catalog | **Брать только для authoritative change** |
| Читать только при compact | 0 между compacts | Compact и так меняет context/cache; stale window остаётся до compact | Не покрывает idle long-lived sessions; Codex native compact не reload-ит developer instructions | **Не делать отдельным workflow** |
| Агент сам вызывает новый freshness tool каждый turn | +1 tool call + result every turn | User/tool tail растёт каждый turn | Честно только если вызов не забыт | **Не брать** |
| Hash mismatch → note с canonical path; agent читает существующим Read | 0 при match; note + один Read только при change | Prefix сохраняется; file content появляется только при change | Хороший fallback для large docs/skills | **Брать как hybrid**, новый MCP tool не нужен |

Token estimates используют существующую UI эвристику Orchestra `chars/4`, а не
provider tokenizer; measured char counts приведены, чтобы не выдавать estimate за
точный bill.

### 3.4 Compact

Технически перечитать перед/после compact можно, но делать compact вторым delivery
route не нужно:

- Claude compact создаёт fresh backend для ack, однако использует frozen
  `self.system_prompt`; manager current prompt/memory не пересобирается
  (`app/session.py:1162-1365`).
- Codex native `thread/compact/start` сохраняет thread и не принимает новое
  `developerInstructions` (`app/session.py:1110-1160`, `app/backend_codex.py:360-430`).

Правильный single path: compact не обновляет delivered hash сам. Следующий normal
send через #93 обязан увидеть mismatch. Для Claude compact ack можно использовать
тот же helper позже как optimization, но это не correctness dependency.

### 3.5 Honest tool/path alternative

Путь уже существует: Codex skill index содержит absolute canonical paths, а у
обоих runtimes есть Read/Bash. Но без invalidation signal агент не знает, что файл
изменился. Требование «читай каждый раз» превращается в лишний tool call every turn;
«читай по необходимости» сохраняет silent stale bug.

Минимальный честный hybrid для low-priority data: server hash comparison → при
mismatch короткая platform note с component/hash/path → existing Read only if
payload large. Для worker-memory/static instructions этот путь может только
показать mismatch, но не отметить его authoritative-applied; до backend refresh
turn должен fail loud. Это не новая система синхронизации и не новый tool.

## 4. Проблема 3 — typed MCP errors

### 4.1 Где теряется информация

- `_api` схлопывает non-2xx в `{"error": r.text}`: исчезают HTTP status,
  `Retry-After`, exception type, structured body и request id
  (`app/mcp_stdio.py:76-96`).
- 32/37 calls в 30 tools проверяют top-level `error` и возвращают обычную строку;
  FastMCP маркирует её `isError:false`.
- Five exceptions to the usual pattern are worse in different ways:
  `list_agents`, `list_orchestrators`, `bg_list` stringify dict as success;
  optional role-icons silently discards failure; `report_bug` может сказать
  `Bug reported`, получив error dict.
- Transport exception обычно достигает FastMCP, но generic handler оставляет только
  `str(e)`. `send_file` точечно добавляет class name, однако всё равно возвращает
  success-shaped string.

### 4.2 Минимальная граница

Один `ApiToolError` в `_api` должен нести:

```json
{
  "code": "transport_timeout|http_429|http_5xx|invalid_response|domain_error",
  "message": "human readable",
  "status": 429,
  "retryable": false,
  "request_id": "client/server id",
  "retry_after_seconds": 24,
  "outcome_unknown": true
}
```

Один MCP adapter должен превратить его в `CallToolResult(..., isError=True)` и
сохранить envelope в `structuredContent`. Classification делается только в `_api`;
34 tools не получают собственных parsers.

Остаются две semantic point fixes:

1. `spawn_worker`: timeout/error второй POST происходит после создания worker.
   Outcome partial; повторять spawn unsafe. Known HTTP rejection доставки может
   разрешить явный resend, но timeout/connection loss означает
   `delivery_outcome_unknown`: `list_agents` подтверждает только созданного worker,
   не факт принятия `/send`. В этом случае нельзя советовать resend до проверки
   текущего turn/status/log; без idempotency key безопасного auto-retry нет.
2. optional role-icons: failure не должен ронять `list_agents`, но обязан попасть в
   warning/log; это intentional degrade, не generic success.

Retry conservative: transient GET может быть `retryable=true`; timeout mutating
POST — `retryable=false, outcome_unknown=true`, пока route не имеет idempotency key.
Это особенно важно для сегодняшних пустых merge errors, но merge mechanics #115
не входят в #116.

## 5. Проблема 2 — RAG freshness

### 5.1 Trigger живой, delivery status мёртвый

Successful merge schedule-ит unreferenced `asyncio.create_task` только после Git
success (`app/routes/sessions.py:711-737`). Search идёт параллельно через read-only
executor и API возвращает только `{"results": ...}`
(`app/rag_service.py:77-84`, `app/routes/memory.py:30-43`). MCP wrapper затем
выбрасывает все response fields кроме `results` (`app/mcp_stdio.py:848-878`).

Fire-and-forget defects separate from freshness:

- task reference/completion/retry/coalescing отсутствуют; restart теряет pending;
- `is_enabled()` означает env flag, а не successful initialize;
- один global write executor сериализует все scopes;
- live scan отмечает path seen до read, а OSError продолжает partial index;
- per-file commits делают mixed generation visible во время scan.

### 5.2 Watermark first, reliability second

Минимальный fail-closed watermark не должен зависеть от записи
`requested_generation` после merge: если та же metadata write упадёт, старый row
может остаться `fresh`. Источник поколения уже durable — Git commit. Поэтому search
читает текущий `source_head`, а additive RAG metadata хранит поколение, которое
успешно закончило scan:

```text
indexed_head
indexed_manifest
trusted = false | true
state = unindexed | indexing | stale_at_head | fresh_at_head | working_tree_unverified | error | unknown
started_at / indexed_at / last_error
```

До **первой** per-file mutation backfill обязан durable записать
`state=indexing, trusted=false`; если invalidation write не удалась, scan
прерывается и старый индекс не меняется. Во время scan считается manifest реально
прочитанных `(path, content)` bytes. В конце второй pass считает manifest текущих
bytes, проверяет docs-only Git cleanliness, отсутствие skip и неизменный HEAD.
`indexed_head/trusted=true` записываются только при совпадении manifest и clean tree;
иначе остаётся `working_tree_unverified/error`. Поэтому transient dirty content,
прочитанный посреди scan, не может быть приписан commit только по одинаковому HEAD.
Если финальная metadata write падает, заранее сохранённый `trusted=false` остаётся.

Search возвращает `fresh_at_head` только при читаемой metadata,
`trusted=true` и `source_head == indexed_head`; metadata/HEAD error даёт `unknown`,
mismatch — `stale_at_head`. Поэтому merge меняет source HEAD сразу, даже если
schedule вообще не запустился; а scan никогда не модифицирует trusted index без
предварительной fail-closed invalidation.

Это намеренно **commit watermark**, закрывающий доказанный post-merge bug. Он не
обещает freshness незакоммиченного working tree: full tree dirty в 9/11 scopes,
RAG-relevant Markdown dirty в 3/11. Dirty bytes можно продолжать индексировать, но
результат остаётся `working_tree_unverified`, а не `fresh_at_head`. Response на
каждом search называет basis (`source_head`, `indexed_head`, `trusted`,
`working_tree_checked_at_backfill`), а не выдаёт commit freshness за абсолютную
свежесть текущих локальных bytes.

`memory/search` возвращает freshness рядом с results; `cross_project` —
`freshness_by_project` для **всех namespaces, реально охваченных query**, даже если
stale namespace не дал hit, плюс явный coverage marker. MCP обязан печатать header
до результатов. Embedding/backfill не блокируется. Цена live HEAD lookup для всех
11 текущих namespaces измерена как `255.238 / 199.328 / 17.501 ms` cold→warm;
single-project query платит один lookup, cross-project — весь набор.

Schema warning: текущий `vec.db` — 456 MB, schema v1, 3,264 indexed files, 21,990
logs и 11 projects. Нельзя просто поднять `SCHEMA_VERSION`: текущая migration при
любом mismatch drop-ает все index tables (`app/rag.py:285-303`). `rag_state` должна
быть additive `CREATE TABLE IF NOT EXISTS` без full re-embed либо отдельной
non-destructive migration. O(1) state row/read намного дешевле 4-minute rebuild.

Reliability — отдельный ticket: retained task set, one runner per scope, dirty bit
для одного follow-up scan, start/end/duration/error logs, initialized readiness и
shutdown behavior. Не await full backfill в merge: measured lag minutes, это
заморозит delivery ради derived index.

## 6. Candidate tickets: цена, риск, зависимости

Это независимые vertical slices для будущего Phase 2. #94 остаётся отдельным A/B
task и не поглощается.

### T1 — Component hashes + fail-visible next-turn gate

- Dependency: **#93** (central `SessionManager.send`). Не зависит от #94.
- Files after #93 lands: `app/manager.py`, `app/session.py`, `app/db.py`,
  `tests/test_manager.py`, `tests/test_session.py`, `tests/test_db.py`.
- Slice: persisted per-component `observed_hash` и
  `authoritative_applied_hash`; recompute before idle turn, zero payload on match.
  Static prompt, worker-memory, AGENTS and skill catalog mismatch возвращает typed
  `stale_state` до начала turn; user notification никогда не продвигает
  authoritative hash. Explicitly low-priority component в будущем может получить
  bounded next-turn delta через тот же detector, но current memory таким не считается.
- Migration/rollout: никогда не seed applied hash из current source. Для legacy row
  base/role baseline берётся из persisted `template_hash`, memory — только из
  фактического `<worker-memory>` persisted `system_prompt`; AGENTS/skills, чью
  фактическую загрузку доказать нельзя, получают
  `legacy_unknown`. Пока T2 для runtime не готов, `legacy_unknown/known_stale`
  даёт повторяемое visible warning agent+parent (≈50–150 tokens/turn), но
  compatibility-turn разрешён и applied hash не двигается. New sessions seed hashes
  только после successful connect; после первого verified T2 refresh session
  переходит в strict blocking mode.
- AC: changed authoritative component виден на самом следующем normal send и stale
  turn не стартует для strict/new/refreshed session; legacy unknown is explicitly
  warning-only until refresh support and never masquerades as applied; unchanged
  **known/strict** send byte-for-byte не меняется, legacy unknown предупреждает на
  каждом turn; failed notification/refresh не marks applied; mid-turn change stays
  pending; compact не consumes hash; dynamic worker list не входит в digest и не
  вызывает churn.
- Price: **1–1.5 days** including legacy migration/rollout tests.
- Risk: medium — warning-only legacy window preserves availability but remains
  visibly stale until T2; no prose classifier is introduced.

### T2 — Authoritative backend refresh for role/AGENTS/catalog

- Dependency: **blocked by T1 and #93**; skill-catalog branch additionally
  **depends on #94**.
- Files: `app/backend_claude.py`, `app/backend_codex.py`, `app/session.py`, provider
  unit tests. `app/workspace.py` и exact-set code не трогать.
- Slice: only on authoritative component hash mismatch, idle disconnect/reconnect,
  resume same Claude UUID/Codex thread with current system/developer instructions;
  existing AGENTS sync runs before connect; after #94 native skill bytes are already
  exact-set current, while #116 computes the catalog digest itself.
- AC: same native id; current prompt passed on resume; no reconnect on hash match;
  reload failure returns typed `stale_state` and no turn starts; Claude unit contract
  matches direct experiment. Codex branch additionally requires a live provider
  probe proving changed `developerInstructions` affect the resumed existing thread;
  request-shape-only test не закрывает AC, а unconfirmed/failed probe не advances
  `authoritative_applied_hash`.
- Price: **1–2 days**.
- Risk: medium — one-time cache cold fill, provider resume quirks. Это честная цена
  priority-correct update, не hidden every-turn tax.

### T3 — Typed MCP HTTP errors

- Dependency: **independent** of #93/#94/#115.
- Files: `app/mcp_stdio.py`, `tests/test_mcp_stdio.py`; optional request-id logging
  middleware only if end-to-end correlation is approved.
- Slice: central `ApiToolError` + MCP `CallToolResult isError` adapter; semantic
  catches only for spawn partial-success and optional icons.
- AC: timeout, connect, 429+Retry-After, JSON/non-JSON 4xx/5xx, non-JSON 2xx and
  2xx `{error}` preserve `code/status/retryable/request_id`; protocol tests assert
  `isError=true`; mutating timeout sets `outcome_unknown`; report_bug cannot false-
  success; spawn mapping survives delivery failure; known delivery rejection и
  unknown delivery outcome имеют разные guidance, unknown не предлагает resend.
- Price: **2–3 days** (3–4 with server-logged request id everywhere).
- Risk: medium — 34 tools change from success-shaped text to MCP errors; unsafe
  retries are the main regression.

### T4 — Fail-closed RAG commit watermark in search result

- Dependency: **independent** of #93/#94/#115; no merge-route edit is needed.
- Files: `app/rag.py`, `app/rag_service.py`, `app/routes/memory.py`,
  `app/mcp_stdio.py`, RAG/route/MCP tests.
- Slice: additive per-project `indexed_head/indexed_manifest/trusted` metadata;
  live Git `source_head` comparison at search; durable trust invalidation before
  first index mutation; actual-read manifest vs final source manifest, docs-only
  cleanliness, unchanged HEAD and completeness before restoring trust; visible
  `fresh_at_head/stale_at_head/working_tree_unverified/indexing/error/unknown`, basis
  and MCP header. Search reads hits + trust state from one SQLite RO snapshot.
- AC: immediately after merge, before any trigger task, search says stale_at_head;
  merge-during-scan cannot be marked fresh by old task; failed metadata write,
  dirty/transiently changed bytes, skip/exception and unreadable HEAD never return
  fresh; failed pre-scan invalidation aborts before index mutation, failed completion
  write leaves `trusted=false`; cross-project reports every namespace actually
  searched even with zero hits and declares coverage; a query concurrent with
  invalidation sees either old trusted hits or new untrusted state, never a mixed
  trust/result claim; existing 456 MB v1 index opens without drop/re-embed.
- Price: **1–2 days**.
- Risk: medium — HEAD/scan races and additive migration. Search adds one Git lookup
  per covered namespace (`17.5–255.2 ms` measured for all 11); backfill adds one
  exact verification pass (`0.43–4.06 s` for all 11), embedding cost unchanged.

### T5 — Retained/coalesced RAG backfill scheduler

- Dependency: **depends on #93 for edit sequencing in `app/routes/sessions.py`**;
  independent of #94/#115. T4 should land first so state/logs are visible.
- Files: `app/rag_service.py`, one route call after #93 edit conflict is gone,
  scheduler/route tests.
- Slice: retain tasks, one runner per scope, dirty bit for one rerun, readiness,
  duration/result/error logs and shutdown cleanup.
- AC: two merges during scan produce at most current scan + one rerun; failed init
  does not schedule; error remains observable; successful merge response does not
  await minutes-long backfill.
- Price: **0.5–1 day**.
- Risk: low–medium — lost wakeup/coalescing bug if state transitions are wrong.

Recommended order matching user priority: **T1 → T2 → T3 → T4 → T5**. T3 and T4
можно запускать сразу независимо; T1/T2 ждут #93, skill branch T2 — ещё и #94, T5
ждёт #93 только из-за общего route hunk. Если одобрен только minimum fail-visible
set: **T1 + T3 + T4**. T2 upgrades fail-loud detection into priority-correct reload;
T5 hardens a trigger already proven alive.

## 7. Conflict boundaries and files not touched

- #93 owns lifecycle and central send: T1 implements after it lands, T2 after T1.
  Research found no design contradiction; ticket T4 inside #93 (central send) is
  the correct hook for #116 T1/T2. #116 T4 (RAG) is unrelated and independent.
- #94 owns exact-set `.claude/skills` sync and slug hash. Он не обещает catalog
  generation/hash: #116 вычисляет digest уже синхронизированных bytes сам; никакая
  sync/prune/copy logic не дублируется.
- #115 owns merge mechanics. #116 uses empty merge errors only as evidence; no merge
  retry/idempotency/transaction change proposed.
- No changes proposed to `app/tg_bridge.py`, `pipelines/`,
  `app/static/js/app.js`, Serena or worktree lifecycle. Runtime files listed above
  are future Phase 2 scope only; this phase changed documentation only.

## 8. Counter-evidence, risks and confidence

- **CONFIRMED:** live managed-skill/template/memory divergence; current one-shot user-prefix
  path; Claude resume+new system append keeps UUID and applies new value; changed
  system prefix cold-fills; RAG hook runs; search response has no freshness; MCP
  boundary loses fields.
- **UNCERTAIN:** Codex `thread/resume` applies changed developerInstructions to an
  existing thread. Installed schema/manual prove that the field is accepted by the
  protocol, not that the provider changes priority state. T2 cannot mark it applied
  without a live provider probe.
- **UNCERTAIN:** exact model prompt staleness when disk files match. No delivered
  fingerprint exists, so exact count is unobservable by construction.
- Branch `CLAUDE.md` differences are not automatically bugs. Therefore only
  missing/local mirror mismatch is counted as definite AGENTS disk stale; scope
  mismatch is a separate upper bound.
- Claude direct cache numbers are Haiku and small prompts. They prove direction
  (changed early prefix → cold) but do not predict exact Sol/Opus token amount.
- `chars/4` is an estimate. Decisions use orders of magnitude and raw char counts,
  not false tokenizer precision.
- A platform note at user priority cannot supersede contradictory developer/system
  instructions. Any design claiming otherwise still lies; T2 exists for this case.
- Commit watermark makes the measured post-merge stale window visible; it does not
  certify dirty working-tree bytes and does not make a mixed per-file index atomic.
  Atomic snapshot swap or a full content-generation scan would be a larger system
  and is not justified by the measured bug.
- Client-generated request id is not end-to-end correlation until server logs it.
  T3 can ship useful typed errors without expanding into tracing infrastructure.

## 9. Sources and evidence tier

1. Current Orchestra source: `app/prompting.py`, `app/manager.py`, `app/session.py`,
   `app/backend_claude.py`, `app/backend_codex.py`, `app/runtime_registry.py` —
   **tier 2 primary code**, opened 2026-08-01.
2. Live read-only `data/orchestra.db`, worktree bytes and three-run hash scan —
   **tier 1 direct measurement**, raw outputs in §2.1.
3. [Official Codex App Server manual](https://learn.chatgpt.com/docs/app-server) +
   installed `codex app-server generate-json-schema` — **tier 2 primary docs/code
   artifact**, fetched/generated 2026-08-01.
4. `docs/tasks/codex-cache-research/research.md` — **tier 1 prior local measurement
   + tier 2 official pricing/docs**: 1,969 calls, 96.08% weighted cache, 10×
   fresh/cached subscription input.
5. Bundled Claude Agent SDK CLI 0.2.114, `--help`, temp same-session experiment —
   **tier 1 direct measurement**, raw selected JSON in §2.2.
6. Current RAG source: `app/rag.py`, `app/rag_service.py`,
   `app/routes/memory.py`, `app/routes/sessions.py`, `app/mcp_stdio.py` — **tier 2
   primary code**.
7. systemd journal, live read-only `data/vec.db`, safe patched route experiment —
   **tier 1 direct measurement**, raw outputs in §2.4.
8. Current `app/mcp_stdio.py`, installed MCP FastMCP source and mocked protocol/
   HTTP calls — **tier 1 direct measurement + tier 2 primary code**, §2.5.
9. `docs/tasks/110/research.md` and `docs/tasks/90/audit.md` — **tier 2 prior
   project research/code experiment**, used as hypotheses and cross-check, not as a
   substitute for the live measurements above.
10. `docs/tasks/93/plan.md`, `docs/tasks/90/plan.md` — **tier 2 approved project
    design artifacts** for dependency/conflict boundaries.

## 10. Adversarial review

Full artifact: `docs/tasks/116/codex-review-research.md`.

Round 1 verdict: **Needs revision before Phase 2**. Codex challenged seven
load-bearing details; all were checked against code/live state rather than accepted
as style comments:

1. Skill denominator was recomputed from persisted pipeline with tracked/untracked
   ownership. Result remained 28/33; all 28 have untracked managed evidence.
2. Worker-memory was moved from automatic user-tail delivery to authoritative by
   default; only explicitly append-only factual data is safe at user priority.
3. `observed_hash` and `authoritative_applied_hash` were split; T1 cannot consume
   the mismatch needed by T2.
4. Codex resume was downgraded from likely to uncertain; T2 now requires a provider
   behavior probe and refuses to advance hash on request shape alone.
5. RAG `requested_generation` write was replaced by fail-closed live Git HEAD ↔
   `indexed_head`, so a failed metadata write cannot leave an old post-merge `fresh`.
6. Cross-project freshness now covers all searched namespaces, not only hit owners;
   unknown spawn delivery no longer recommends a potentially duplicate resend.
7. #94 is correctly only an exact-set bytes dependency; catalog hash belongs to
   #116.

Round 2 verdict: **Needs one more revision before Phase 2**. First-round blockers
were resolved; three remaining corrections were accepted:

1. HEAD alone did not bind dirty working-tree bytes to a commit. T4 now invalidates
   trust before mutation and compares the actual-read manifest with a final clean
   source manifest; failure leaves `trusted=false`. Costs were measured.
2. T2 is explicitly blocked by T1, which owns persisted component state.
3. Legacy sessions never seed «applied» from current sources. Reconstructable
   prompt bytes come from persisted prompt; unprovable AGENTS/skills start
   `legacy_unknown`, visible warning-only until verified refresh, then strict.

Round 3 verdict: **APPROVED — ready for Phase 2**. No blocking correctness, race,
dependency or cost claim remained. Единственная non-blocking suggestion — явно
согласовать overview с warning-only legacy compatibility mode — внесена выше.
