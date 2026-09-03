# #234 — intermittent `/api/usage/quota-map` browser failure

Дата замера: 2026-08-23. Фаза: RESEARCH ONLY. Production-код, тесты и промпты не менялись.

## Question

- **Context:** живой дашборд Orchestra на ноутбуке (`127.0.0.1:8888`), тот же UI через
  SSH-forward к VPS (`127.0.0.1:18888`) и через reverse proxy (`orc.seedon.ru`).
- **Change under test:** установить механизм сообщения
  `Ответ не дошёл — /api/usage/quota-map: 3 попытки по 2.0 с ... ⚠ Usage unavailable`.
- **Baseline:** quota refresh получает JSON с непустыми `generated_at` и `rule`, не только 200.
- **Outcome:** browser request/resource timing, request failures, DOM transitions, marker в
  server journal, latency лёгкого backend-byte control и read-only SQLite timing.

## Hypotheses and falsifiers

1. Endpoint compute превышает 2 с. Фальсификатор: browser failure при быстром loopback и
   отсутствии marker на сервере.
2. GET ждёт один из шести HTTP/1.1 slots, один занят SSE. Фальсификатор: failed marker
   своевременно появляется в access log или контроль с шестью SSE не воспроизводит отказ.
3. `AbortSignal.timeout(2000)` неверно охватывает очередь до wire. Фальсификатор: отказ не на
   границе 2 с или другой класс исключения.
4. Ретраи перекрываются. Фальсификатор: request timestamps показывают строгую
   последовательность «2 с → jitter → следующий fetch».
5. Причина только в public reverse proxy. Фальсификатор: тот же результат на loopback/tunnel.
6. Причина в IndexedDB/SW/cache state. Фальсификатор: fresh context падает до загрязнения, а
   688-row/1.7 MB control не ухудшает исход.
7. `_quotaMapData`/render race сам создаёт `Usage unavailable`. Фальсификатор: quota-map-only
   failure оставляет usage видимым, а usage-only failure создаёт точный текст.
8. 401/redirect ошибочно классифицируется как transport break. Фальсификатор: один `Error`,
   без ретрая и без network banner.
9. Общий event-loop/load stall задерживает все ответы. Фальсификатор: во время медленного
   quota-map `HEAD /api/models` возвращает backend build byte быстро.

## Pre-registered boundaries

- HTTP order: `local,tunnel,local,tunnel,public,tunnel,public,tunnel,local,public,local,public`.
  Browser order identical. Каждый record содержит текущий laptop loadavg.
- Client budget: текущие 2,000 ms × 3, jitter 0–800 ms.
- Успех: 200 + `generated_at` + `rule`; build control: 200 + `X-Orchestra-Build`.
- IndexedDB control: 688 rows × 2,400 content bytes = 1,651,200 bytes, ephemeral context.
- Sample windows: HTTP `11:00:26.850–11:01:04.793Z`; browser
  `11:01:22.747–11:02:21.781Z`; controls `11:04:31.512–11:05:06.217Z`; exploratory
  queue A/B/A/B `11:14:43.241–11:15:40.331Z` [1–5].

## Evidence matrix (filled before recommendation)

| hypothesis | client-side observable | server-side observable | positive control | falsifier | measured runs/failures | verdict |
|---|---|---|---|---|---|---|
| endpoint compute latency | Direct totals: local 32–38 ms warm plus 3,815 ms outlier; tunnel 398–789 ms; public 1,243–6,465 ms | Every direct response had backend byte; read-only trace SQL only 3–12 ms local / 8–20 ms VPS | warm loopback 3/4 at 32–38 ms | browser failures whose marker never reached server | 12 direct, 4 exceeded 2 s (local 1/4, tunnel 0/4, public 3/4) | **CONFIRMED secondary**, not sole cause |
| HTTP/1.1 six-slot scheduling + SSE | Normal local failure: 3 resources at 2,000–2,005 ms, `requestStart=0`; local later success: first two attempts had zeroed timing, third queued 803 ms then completed | failed local marker and failed public marker: 0 **completion** lines; arrival was not instrumented | existing SSE + 5 bounded extra SSE all opened; local and tunnel quota then failed 3/3 with `requestStart=0` | a marker-bearing arrival log for normal failures | normal explicit browser: final failures 3/12; saturation 2/2 failures, 0/2 server completions | **CONFIRMED in six-slot control; LIKELY in normal failures**, ingress unresolved |
| abort/timeout implementation | All terminal attempts: `TimeoutError: signal timed out`, resource duration 1,999.9–2,006.6 ms | CDP 2.5 s latency control produced 3 later server completions although client aborted all 3 | CDP latency=2,500 ms | different timing/class | CDP 1/1 failed, 3/3 attempts at 2 s | **CONFIRMED converter**: timer starts before wire availability |
| retry serialization | Console order is timeout → measured 0–800 ms pause → next request; no overlap | One failed tunnel action still produced 2 late completions after browser moved on | forced CDP and six-slot failures | overlapping attempts | every 3-attempt control serialized; storm current arm needed up to 23 resources for 11 logical calls | **CONFIRMED amplifier**, not initiating cause |
| origins | browser final failures: local 1/4, tunnel 1/4, public 1/4 | local marker absent; tunnel marker completed twice late; public marker absent | interleaved A/B/A/B | one origin exclusively fails | 12 explicit browser actions, 3 final failures | **CONFIRMED multi-origin**, no single-origin cause |
| reverse proxy | successful public browser calls 1,350–1,842 ms; one failed; HTTP direct public 3/4 >2 s | public header `nginx/1.24.0`; tunnel header `uvicorn`; both backend bytes when completed | tunnel bypasses public nginx path | public and tunnel tails equal | direct: tunnel 0/4 >2 s vs public 3/4 | **CONFIRMED tail amplifier**, not root alone |
| browser/IndexedDB/SW/cache | fresh context failed before dirty control; SW=[] and CacheStorage=[] in all contexts | pre-dirty failed marker absent; dirty overlap marker completed | inserted 688 rows / 1,651,200 bytes in 35.5 ms, forced mismatched watermark and concurrent repair | dirty state uniquely reproduces | fresh before: 1/1 failed; dirty+repair overlap: 1/1 success in 1,497.7 ms | **REFUTED as necessary/current cause**; original corrupted #364 state unavailable |
| stale `_quotaMapData` / render race | quota-map-only abort left usage values and showed lane `нет данных`; usage-only abort produced exact `⚠ Usage unavailable` | quota-map-only route was deliberately aborted; `/api/usage` control remained backend-valid | paired fault injection | quota-only abort yields exact text | 2 controlled arms | **REFUTED as transport cause; CONFIRMED separate fallback regression** |
| auth/redirect/error classification | 401 produced `Error: 401...`, exactly one attempt, banner stayed hidden | explicit 401 response | controlled 401 fulfill | 3 retries / TimeoutError | 1/1 | **REFUTED** |
| server load/event-loop stall | during the paired local record quota was 3,814.7 ms and build control 6.1 ms; loadavg across runs 3.19–8.00 | read-only SQL 3–12 ms local; build header present | separate connection started 50 ms after quota future (`probe_http.py`) | preserved per-request start/end timing showing control stalls with route | 12 paired direct runs | **UNSUPPORTED as primary cause**, but raw file lacks exact overlap timestamps |
| provider-refresh stampede | browser gets late/aborted responses even after a slot opens | local journal: 10 Grok billing GETs in the same second; VPS: 2 Anthropic usage GETs in the same expiry burst | current code has locks only in `current_quota_observation`, while quota-map calls `_get_usage_data()` directly | one provider call per refresh window | observed burst 10× local, 2× VPS | **CONFIRMED secondary server amplifier** |

## Findings

### F1 — evidence supports a coupled client queue + uncoalesced server refresh

**LIKELY for normal failures; CONFIRMED in the six-slot control and for the server stampede —
direct browser measurements plus completion-log correlation (tier 1).**

The current page starts `initUsageBar()` and `initQuotaLines()` consecutively
(`app.js:924-925`). `fetchUsage()` immediately starts `/api/usage` and one
`/api/usage/quota-map` (`usage.js:820-823`); `fetchQuotaLines()` starts a second quota-map
(`app.js:8943-8946,8968`). Their 120 s intervals are raw `setInterval`s, outside the phase-shifted
poll coordinator (`usage.js:879`, `app.js:8970`). Therefore one refresh phase begins with three
usage-family GETs, two byte-identical quota-map GETs, alongside session/history/model polling [6].

`api()` creates `AbortSignal.timeout(2000)` before calling `fetch()`
(`app.js:7240-7244`). The two seconds therefore include Chromium's wait for an HTTP/1.1
connection, not merely server time. In a normal local tab, one explicit marker failed all three
attempts and produced zero **completion** lines. Another local call had two zero-timing attempts;
the third waited 803 ms for connection admission, then received the backend body in time. These
normal observations are consistent with pre-wire admission but do not prove arrival absence because
the server has no marker-bearing ingress log. The six-slot positive control does establish the seam:
on both local and tunnel all five added SSE streams opened, quota failed 3/3 at the 2 s boundary,
and no marker completion followed [1][3][4].

When a request does reach a cache-expired backend, `build_quota_map()` calls unguarded
`_get_usage_data()` (`system.py:1428`). Concurrent callers all observe stale state before any writes
`failed_at`/`ts`; the journal recorded ten Grok billing GETs in one local second and two Anthropic
usage GETs in one VPS burst [4][6]. Browser abort does not cancel this route work: the failed tunnel
marker completed twice after the client had timed out. This is why the banner's sentence “сервер
отвечает” is literally true for some attempts and why other attempts have no server record at all.

### F2 — public path adds a large tail, but tunnel and loopback still reproduce

**CONFIRMED — interleaved direct and browser samples with backend-byte control (tier 1).**

Direct tunnel requests were 0/4 over 2 s (398–789 ms). Direct public requests were 3/4 over 2 s
(2,151; 6,465; 4,188 ms), despite backend bytes in all four. Browser explicit calls ended in one
failure per origin (local/tunnel/public). Thus nginx/public routing increases probability but cannot
explain the local and tunnel browser failures [1][2][4]. This reconciles #142/#143/#146: the old
16 KiB Contabo path fault and its Moscow mirror were real then, but today's tunnel is objectively
better and still loses calls at the browser admission seam [9–11].

### F3 — `⚠ Usage unavailable` is a second current regression, not proof quota-map is stale

**CONFIRMED — paired fault injection, current source, and existing named test (tiers 1+2).**

Quota-map-only failure did not produce `Usage unavailable`; it kept usage numbers and degraded
lane text to `нет данных`. `/api/usage`-only failure produced the exact `⚠ Usage unavailable`.
The reason is source-visible: `Promise.allSettled` never enters the `catch`, yet the rejected branch
sets `_usageData = null` and then `snapshotSave('usage', null)` (`usage.js:820-838`). The #197
snapshot restore exists only before the request and inside the unreachable-for-allSettled `catch`
(`usage.js:807-812,839-846`) [3][6].

The pre-existing command
`PYTHONDONTWRITEBYTECODE=1 ...python -m pytest -p no:cacheprovider tests/test_frontend.py::test_dashboard_survives_lossy_channel_from_snapshot -q`
returned exit 1: `Page.wait_for_function: Timeout 15000ms exceeded` while waiting for usage text
containing `5h` (`1 failed in 23.71s`). No test file was edited [12]. This contradicts #197's report
that cached usage survives a lossy second page and explains why the current transport blip is more
annoying than the earlier intended UI [8].

### F4 — IndexedDB is neither necessary nor sufficient for this exact failure

**CONFIRMED within tested state; UNCERTAIN for the unavailable historical corrupted profile (tier 1).**

Fresh ephemeral contexts had no service workers and no CacheStorage entries. A local marker failed
before the synthetic IDB state existed. In the same context, inserting 688 × 2,400 bytes took
35.5 ms; the raw event stream then recorded `[store] watermark 9007199254740991 > max_log_id ...
стираю зеркало`, and concurrent `_storeSync()` + quota refresh succeeded in
1,497.7 ms. The historical #364 state whose deletion cured overall tab slowness was not preserved,
so this does not claim all IndexedDB corruption is harmless. It does prove that IndexedDB is not a
required link in today's quota-map timeout chain [3][7].

### F5 — neither a larger timeout nor a client queue alone is a complete fix

**CONFIRMED for the tested candidates (tier 1).**

The already-recorded 4 s experiment was reverted after worsening the user's queue symptom
(commits `5c77969b`, `47b28811`). A scratch app-side queue of four requests was tested A/B/A/B
under 800 ms CDP latency. Results were `current: 10/11, queue4: 10/11, current: 11/11,
queue4: 11/11`; the last queue arm used 11 physical requests instead of current's 23, but the first
queue arm still lost quota-map. Therefore admission helps retry amplification but cannot cover the
independent cold server path [5][7].

## Smallest evidence-backed fix class

The smallest **root-cause** class has two bounded seams; the experiment refuted either one alone:

1. **Client admission/coalescing before timeout creation:** share one in-flight quota-map result
   between the two consumers and admit a bounded number of GETs before constructing the 2 s
   `AbortSignal`. This removes browser-internal invisible queue time and prevents a retry from
   immediately re-entering the same full pool.
2. **Cache-only quota-map read:** quota-map consumes the already-owned cached observation while
   `/api/usage` owns refresh. This is the bounded server path supported by the cold direct timings;
   single-flight alone cannot guarantee a sub-2-second first refresh.

Provider-refresh single-flight is a separate amplifier mitigation: it turns the observed 10×/2×
burst into one, but it is not interchangeable with the cache-only latency fix.

The smallest **symptom mitigation**, independent and insufficient as a root fix, is to preserve the
last non-null `_usageData`/snapshot on a rejected `/api/usage`; it removes `Usage unavailable` but
does not deliver the missing fresh response.

This is a fix class, not an implementation plan. Exact queue width, ownership function, and tests
belong to Phase 2 if approved.

## Counter-evidence and limitations

- The normal explicit browser sample is 12 actions, not a long-run failure-rate estimate; 3/12 is
  mechanism evidence, not a production probability.
- `requestStart=0` alone is not proof of pre-wire queueing: the CDP latency control also reported
  zeroed timing while the server later completed 3 requests. Receiving-side marker absence is the
  decisive evidence; this is why browser and journal were joined [3][4].
- Tunnel failure had two server completions, while local/public failed markers had none. The same UI error therefore has at least two causes; any one-seam diagnosis is refuted.
- Queue4 A/B has high loadavg (5.9–8.0) and only two runs per arm. It establishes “queue alone is
  not sufficient,” not an optimal concurrency value.
- The original #364 IndexedDB profile is unavailable. Only necessity for this failure and the
  specified 688-row volume/mismatch control were tested.
- `docs/tasks/364*` does not exist in any current Git ref. Its code evidence survives in commits
  `5c77969b`, `47b28811`, `0d8208a7` and AGENTS.md; this missing artifact limits reconstruction.

## Review outcome

Targeted Sol causal review: **APPROVED, no blocking findings**. Four suggestions were accepted:
normal marker absence was narrowed from “never reached” to “no completion / ingress unresolved”;
event-loop exclusion was downgraded because exact overlap timestamps were not persisted; cache-only
and single-flight were separated; the IDB repair event is now cited explicitly. No second round is
permitted for suggestions-only prose under the review gate [13].

## Affected files and risks for a future plan

- `app/static/js/app.js`: `api`, `_pollCoalesce`, `fetchQuotaLines`, `initQuotaLines`.
- `app/static/js/usage.js`: `fetchUsage`, snapshot preservation, duplicate quota-map consumer.
- `app/routes/system.py`: `build_quota_map`, `_get_usage_data`, existing provider locks.
- `tests/test_frontend.py`: existing #197 oracle is already red on current main; a future plan must
  freeze a correct red baseline rather than treat it as passing coverage.
- Risks: queue starvation; counting SSE incorrectly; stale quota display after restart; sharing a
  rejected Promise across consumers; server lock cancellation; hiding provider failures behind
  stale data; changing mutation-request semantics (must remain outside GET retry queue).

## Review decision gate

- Changed artifacts/consumers: docs and bounded probes only; consumers are the Phase-2 decision and
  future dashboard/API work.
- Author runtime: `gpt-5.6-sol` (live session metadata).
- AC: required evidence matrix filled; all named hypotheses separated; exact action measured at
  three origins; raw outputs retained; no production changes.
- Checks: JSON parses; marker/journal correlation; secret-form scan; named #197 test run.
- Route: targeted Sol causal review (no strong independent oracle for the synthesis).

## Sources

1. `docs/tasks/234/browser-baseline.json` — **tier 1**, native Chromium, 12 interleaved actions.
2. `docs/tasks/234/http-baseline.json` — **tier 1**, 12 direct backend-byte requests + HEAD controls.
3. `docs/tasks/234/browser-controls.json` — **tier 1**, SSE saturation, CDP, IDB, render, auth controls.
4. `docs/tasks/234/server-correlation.json`, `journal-local.txt`, `journal-remote.txt` — **tier 1**, receiving-side markers and read-only DB timings.
5. `docs/tasks/234/queue-candidate.json` — **tier 1 exploratory**, scratch A/B/A/B; no production edit.
6. `app/static/js/app.js:919-930,7190-7278,8943-8970`; `app/static/js/usage.js:804-883`; `app/routes/system.py:944-1074,1397-1428` — **tier 2 primary source**.
7. Git commits `5c77969b`, `47b28811`, `0d8208a7`, `a44feb4b`, `24d6308d` — **tier 2 primary history**.
8. `docs/tasks/70/report.md`, `docs/tasks/197/research.md`, `docs/tasks/197/report.md` — **tier 2 task artifacts**, retry/cache prior evidence.
9. `docs/tasks/57/research.md` — **tier 2 task artifact**, exact-action measurement and timeout history.
10. `docs/tasks/142/report.md`, `docs/tasks/143/report.md` — **tier 2 task artifacts**, old Contabo path failure and falsifiers.
11. `docs/tasks/146/report.md` — **tier 2 task artifact**, mirror A/B and SSE behavior.
12. `tests/test_frontend.py::test_dashboard_survives_lossy_channel_from_snapshot` + measured command above — **tier 1 run over tier 2 existing oracle**.
13. `docs/tasks/234/review-research-sol.md` — targeted Sol review, **APPROVED**, no blocking findings; exact research quote present as review evidence.
