# #240 — почему standalone Codex ощущается быстрее Orchestra Codex/Sol

## Вердикт

**В измеренном одноходовом no-tool сценарии болезненного overhead Orchestra нет.** При одинаковых
CLI 0.149.0, `gpt-5.6-sol`, `xhigh`, Standard tier, cwd, 60-байтовом задании и прокси:

- `codex exec` от запуска до доставленного `turn.completed`: **10.735 / 12.678 с**;
- bare app-server от запуска до той же точки: **11.490 / 12.948 с** — парная разница
  **+0.270 / +0.756 с** в пользу exec, не многократный разрыв;
- Python JSON-RPC transport: median **0.058 ms**, p95 **0.087 ms** на 200 локальных
  request/response;
- `turn/start` ack через Orchestra wrapper: **6–21 ms**;
- C→D (добавлены managed home, 58 188 Б role prompt и Orchestra MCP) меняет model-turn wall на
  **+0.012 / −0.584 / +1.272 с** (median **+0.012 с**) при собственном разбросе одинакового C
  **6.715–8.932 с** и D **6.727–9.327 с**.

В наблюдаемом D-turn практически всё время находится до первого model event: TTFT
**6.573–9.152 с**, а от первого event до `turn/completed` — **0.092–0.175 с**. Один раз при
218 468 input tokens настоящей архивной истории TTFT был **9.948 с**, final **10.071 с**.
Значит измеренный delay распределяется так: локальный transport ≈0; turn ack ≈0.01 с; managed
connect premium median 0.161 с; оставшиеся 6.6–14.2 с — model-start/provider path и его шум,
не Python orchestration. [M1][M2]

**Симптом пользователя целиком не объяснён.** PONG-turn намеренно держал tool rounds=0 и поэтому
изолировал harness latency, но не измерил различие поведения: полный Orchestra role может породить
больше tool/model round-trips и больше работы на ход. Это сильнейшая оставшаяся гипотеза: в #170
семь `xhigh`-ходов дали 87.45% active wall, `duration↔output_tokens r=0.944`, а effective tool wait
занял только 5.19%; в #175 у Codex было 7.87 tool calls/turn против 4.07 у Opus и 22% дословно
повторённых Bash-команд. Эти исторические измерения согласуются с «долго делает много», но не
являются matched replay сегодняшнего пользовательского действия. [H1][H2]

**Confidence: CONFIRMED** для измеренных transport/ack величин; **LIKELY** для того, что в этих
двух A/B-парах крупный app-server overhead не наблюдался; **UNCERTAIN** для причинного вклада
history и причины субъективного разрыва на обычных tool-using задачах.

## Вопрос

- **Контекст:** установленный Codex CLI 0.149.0 вызывается standalone и через Orchestra на одном
  ноутбуке; пользователь наблюдает, что standalone быстрее, включая negative control без Fast.
- **Изменение под тестом:** последовательно добавить app-server, Python transport, managed
  prompt/AGENTS/skills/MCP/home и persisted history.
- **Baseline:** `codex exec` на том же `gpt-5.6-sol`, `xhigh`, Standard tier, cwd, задании и прокси.
- **Outcome:** connect/init, `turn/start` ack, TTFT, final wall, tool rounds, token usage и знак
  парной A/B разницы при напечатанном loadavg.

## Архитектура — установлена до latency-выводов

Production path доказан одновременно живым `/proc` и кодом:

1. Live argv: `node /home/maxim/.npm-global/bin/codex ... app-server --stdio`; дочерний native
   executable имеет тот же argv и SHA-256
   `bbc3341e44c9ead340ed9570c17be936e37870f570751a941699ffd04d672827`.
2. `AgentSession._make_backend` формирует `BackendBuildContext`
   (`app/session.py:791-837`), `_codex_factory` создаёт `CodexBackend`
   (`app/runtime_registry.py:205-265`).
3. `CodexBackend.connect` запускает CLI через `asyncio.create_subprocess_exec`, затем шлёт
   `initialize`, `initialized`, `thread/start|resume` (`app/backend_codex.py:918-1079`).
4. `send` шлёт `turn/start` (`app/backend_codex.py:1096-1134`); `_request/_write` коррелирует id
   и пишет newline JSON в stdio (`app/backend_jsonrpc.py:399-427`).
5. Поиск `codex-sdk|from openai|import openai` не нашёл Python Codex/OpenAI SDK в production
   app или зависимостях.

Это соответствует текущей официальной документации app-server: двунаправленный JSON-RPC с
опущенным wire-header, JSONL по stdio, handshake `initialize`→`initialized`, затем
`thread/start|resume`, `turn/start` и поток notifications до `turn/completed`. [1]

**Finding A — CONFIRMED, evidence tier 1+2:** Orchestra использует установленное CLI app-server
через собственный Python JSON-RPC transport, не Python Codex SDK. Полный снимок — [M3].

## Метод

### Гипотезы и фальсификаторы

| Гипотеза | Что доказывает её неверной | Итог |
|---|---|---|
| CLI/version drift | один exact CLI package/version во всех arms и production; версия current официально | REFUTED |
| Python wrapper дорог | локальный RPC ≪1 ms и B/C без устойчивой добавки | REFUTED как sufficient cause |
| app-server mode дорог | A/B total-to-final отличается не более ~0.8 с в обеих парах | REFUTED как sufficient cause |
| role prompt / AGENTS truncation или повторная инъекция | файл ниже cap; удаление слоя не даёт устойчивого speedup; warm prefix cache виден | truncation REFUTED; behavioral impact UNCERTAIN |
| MCP schema/handshake дорог | positive status/list control видит ready+41 tools; C→D connect мал, D/F-no-MCP wall sign меняется | REFUTED как sufficient cause на no-tool turn |
| persisted history / 828K setting дорог сам по себе | fresh→warm неустойчив, реальный 218K context остаётся около 10 с | 828K setting REFUTED; used history UNCERTAIN |
| xhigh mismatch | argv/turn одинаково `xhigh` | REFUTED как cross-arm mismatch |
| Fast vs Standard | Standard зафиксирован во всех arms; пользовательский no-Fast control всё равно быстрее | REFUTED пользователем как sufficient cause |
| proxy/environment mismatch | shell/systemd/Node/native proxy hashes одинаковы | REFUTED |
| config-digest reconnect | unchanged check ≈1.4 ms; forced reconnect ≈0.48 с | REFUTED как large recurring cost |
| auto-compact/settling | context ниже thresholds; exact status markers отсутствуют в measured session | REFUTED для measured turns |
| host load | slowest factor runs при load1 1.92–2.12; authoritative n=20 load1↔total-to-TTFT r=−0.412 | REFUTED для measured spread |
| provider/model-start variance | одинаковый arm расходится на секунды; factor deltas меняют знак | SUPPORTED |

### Предзаданные условия

- Task: `Reply with exactly PONG and nothing else. Do not call tools.`
- CLI/model/effort/tier: 0.149.0 / `gpt-5.6-sol` / `xhigh` / `default`.
- Same cwd and inherited proxy; each arm has an isolated scratch CODEX_HOME and never modifies
  `~/.codex/config.toml`.
- A/B/A/B is interleaved and prints loadavg per run. A's final oracle is the timestamp of
  `turn.completed`, not process exit; the first pilot that used process exit is retained in raw
  data but excluded from the authoritative pair.
- Pass for a layer-as-cause: same-sign added latency larger than before-vs-before/provider spread.
  A sign flip or a delta within identical-arm range does not pass.
- Each model turn is bounded to 180 s. The authoritative table contains 20 completed zero-tool
  turns; eight completed pilots/oracle-correction turns remain in raw files but are excluded from
  the final comparisons.

The exact 20-row required table (full argv/config SHA-256, bytes, times, tokens, proxy, load and
outcome) is [M1]. Sanitized raw JSONL and the generating scripts are [M4]–[M12].

## Measurement summary

| Arm | n | Static change | connect median/range, s | TTFT median/range, s | final median/range, s | input tokens | cached tokens | tools |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| A `codex exec` | 2 | standalone; AGENTS; fresh | included in turn-start ack 1.752–1.804 | 11.688 / 10.733–12.643 | 11.706 / 10.735–12.678 | 37 480–37 490 | 9 984 | 0 |
| B bare app-server | 2 | JSON-RPC; AGENTS; fresh | 1.912 / 1.856–1.969 | 9.922 / 9.180–10.663 | 10.307 / 9.634–10.979 | 38 051–38 056 | 11 008 | 0 |
| C Python wrapper | 3 | no Orchestra role/MCP/history | 1.526 / 1.293–1.878 | 8.005 / 6.592–8.814 | 8.055 / 6.715–8.932 | 38 031–38 046 | 11 008 corrected run | 0 |
| D managed full | 3 | +58 188 B role, +32 634 B MCP schemas | 1.589 / 1.485–2.039 | 8.256 / 6.573–9.152 | 8.348 / 6.727–9.327 | 51 602–51 627 | 11 008 corrected run | 0 |
| E warm one-turn | 3 | resume D persisted thread | 1.599 / 1.375–1.602 | 9.078 / 9.049–10.506 | 9.160 / 9.140–10.997 | 54 558–54 598 | 50 944 corrected run | 0 |
| E real archived | 1 | 1 370 598 B rollout; 218 468-token request | 2.638 | 9.948 | 10.071 | 218 468 | 11 008 | 0 |
| F no role prompt | 2 | D minus 58 188 B role | 1.849 / 1.727–1.971 | 10.313 / 6.771–13.855 | 10.369 / 6.838–13.901 | 38 121–38 146 | 11 008 corrected run | 0 |
| F no project doc | 2 | D minus 104 615 B AGENTS | 1.514 / 1.426–1.601 | 10.635 / 7.101–14.169 | 10.795 / 7.284–14.307 | 30 116–30 141 | 11 008 corrected run | 0 |
| F no MCP | 2 | D minus 41-tool server | 1.612 / 1.579–1.645 | 8.204 / 7.748–8.660 | 8.350 / 7.833–8.868 | 51 537–51 562 | 11 008 corrected run | 0 |

A's `final` starts at process launch; B–F `final` starts at `turn/start`. [M1] therefore has a
separate comparable `total-to-final`: A=`final`, B–F=`connect+final`. Cache usage is absent in nine
first-pass rows because the initial collector used the wrong metadata key; every arm has a
corrected capture, and missing cells remain `—`. Reasoning-token breakdown is unavailable from the
app-server usage contract and is also `—`, not zero (bare B exposed zero in its narrower event).

No-model controls:

- Python JSON-RPC stdio echo: n=200, median 0.058 ms, p95 0.087 ms, max 20.155 ms.
- Empty-state CODEX_HOME initialize+thread/start: 1.334 s, not slower than healthy-state runs.
- Unchanged managed config digest: 1.236 / 1.514 ms.
- Forced digest change and persisted-thread reconnect: 0.452 / 0.499 s.

### Layer apportionment

1. **Standalone vs bare app-server.** Comparing from process launch, B−A total-to-TTFT is
   **−0.010 / +0.303 с**, B−A total-to-final **+0.270 / +0.756 с**. In these two pairs a
   multi-second addition was not observed; n=2 is not a statistical upper bound.
   **LIKELY, tier 1 matched A/B/A/B.**
2. **Python transport.** Local request/response is 0.058 ms median; real `turn/start` ack is
   6–21 ms. **CONFIRMED negligible relative to multi-second TTFT.**
3. **Managed home/MCP/prompt.** D−C connect is +0.193/+0.063/+0.161 s; D−C turn wall
   +0.012/−0.584/+1.272 s. **CONFIRMED small connect premium; REFUTED stable turn penalty.**
4. **Prompt and AGENTS.** Role prompt adds ~13 581 input tokens; AGENTS adds ~21 496. Removing
   either makes wall faster once and slower once. **CONFIRMED token effect, UNCERTAIN latency
   effect; provider noise is larger than observed factor effect.** `AGENTS.md` 104 615 B is below
   `project_doc_max_bytes=262144`, so current truncation is **REFUTED**. Official config reference
   defines this key as the byte cap used when building project instructions. [2]
5. **MCP.** A no-model positive control observed `orchestra: starting→ready`; the official
   `mcpServerStatus/list(detail=toolsAndAuthOnly)` returned exactly the expected 41 Orchestra tool
   names with zero missing. [M9] The tools/list surface is 32 634 B; removing it changes model input
   by only 65–75 tokens in matched static configs and final wall by +0.519/−1.495 s versus adjacent
   D baselines. **LIKELY schemas are not eagerly charged as full prompt on this no-tool turn;
   CONFIRMED that active MCP had no stable wall sign in this corpus.**
6. **History.** One-turn warm E−D wall is +4.270/+0.792/−0.167 s (median +0.792, sign not stable).
   A real archived 218 468-input-token thread finishes at 10.071 s but lacks a synchronous fresh
   control. **UNCERTAIN: no causal history cost is established, including beyond 218K.**
7. **Config/state lifecycle.** Initial connect is 1.3–2.6 s; cold state creation is not worse;
   forced config reconnect is ~0.48 s and unchanged checks ~0.0014 s. **CONFIRMED not the recurring
   multi-second turn delay.**
8. **Provider/model-start noise.** 30 141-token F took 14.307 s while 218 468-token E-real took
   10.071 s; on the exact authoritative M1 n=20 corpus, using comparable total-to-TTFT
   (A from process launch; B–F connect+turn TTFT), input r=0.126 and load1 r=−0.412.
   Identical-arm ranges are
   0.8–2.6 s. **CONFIRMED noise dominates the small factor effects on this corpus; attribution to
   a specific provider subsystem remains UNCERTAIN.**

## Independent hypotheses outside the layer benchmark

### CLI/version

Both the live Orchestra child and standalone launcher resolve to installed package 0.149.0. The
official changelog lists **Codex CLI 0.149.0 on 2026-08-20** and no later CLI release by the
2026-08-23 measurement date. [3]

**CONFIRMED / REFUTED drift, evidence tier 1+2.** Updating Codex is not indicated by this evidence.

### Effort

Production argv and every benchmark turn use `xhigh`; there is no standalone-vs-Orchestra effort
mismatch. Official config reference lists `model_reasoning_effort` and describes it as the
reasoning control; the current Sol model page lists `xhigh` support. [2][4]

`xhigh` can still explain absolute duration on real work: #199 measured one closed Sol task at
42→73 s for medium→xhigh, but another at 51→54 s; #170 found duration followed output volume.
[H1][H3] **REFUTED as mismatch; LIKELY as task-dependent absolute cost.**

### Service tier / Fast

Standalone base config has `service_tier="fast"`; managed config intentionally omits it. The
official config says Fast maps to priority, and the Responses reference says `default` is Standard
while Fast is explicit. [2][5] Every #240 model call explicitly pinned `default`. User's 18:10
negative control says standalone remains faster without Fast, so Fast is accepted as **REFUTED as
a sufficient cause**. Historical #208 found only 1.23× cold / 1.43× warm wall speedup (about five
seconds) on medium-effort fixtures, consistent with a marginal contributor rather than the full
symptom. [H4]

### Proxy/network

Shell, systemd MainPID, Node wrapper and native app-server had identical HTTPS_PROXY, HTTP_PROXY and
NO_PROXY hashes; the standalone launcher loaded the same hashes. [M3]

**CONFIRMED / REFUTED mismatch, evidence tier 1.** This does not prove provider transit has zero
jitter; it proves the two paths did not use different configured routes.

### 828K context, auto-compact and settling

App-server reports 828 400 effective tokens from the live 872 000 raw setting, reproducing #209.
The official model card's API surface is 1 050 000 total; #209 correctly warned not to equate API
and ChatGPT-auth CLI surfaces. [4][H5]

The measured fresh/warm/real contexts (30 116–218 468) remained below the live
784 800 auto-compact limit and below Orchestra precompact's 60% arm threshold (497 040). Exact
status matching for this #240 session found zero `codex context compacted`, config reconnect or
settling status rows; substring hits were only the user's hypothesis and code/tool output.

**REFUTED for the measured turns; UNCERTAIN near the window limit.** The larger configured ceiling
does not itself add tokens; used history does.

### Project skills

Two discoverable project skills total 40 662 B. Current `_codex_factory` leaves generated skill
index injection off and relies on native discovery (`app/runtime_registry.py:205-242`); the
benchmark did not invoke a skill. Removing the directory would violate same-cwd or mutate the live
worktree, so this factor was not run. **UNCERTAIN but bounded by the D/F observations; explicit
skill invocation remains unmeasured.**

## Counter-evidence and limitations

- The user's repeated observation, including no-Fast standalone, is counter-evidence to “there is
  no real symptom.” #240 instead says the symptom is not reproduced by a 60-byte no-tool task.
- A one-word answer is ideal for transport isolation and poor for workflow behavior. It cannot
  reveal extra search/read/review/model rounds induced by full-cycle instructions.
- Factor cells have n=2; their signs flip. No equivalence claim is made.
- Reasoning-token breakdown is not exposed in app-server `tokenUsage`; the table marks it `—`
  instead of inventing zero. Bare app-server reported zero in its narrower event shape.
- First-pass MCP serialization omitted input/output schemas (16 530 B). The corrected mechanical
  tools/list calculation is 32 634 B; old raw rows remain immutable and the derived table uses the
  corrected static value.
- The first real-history copy retained an absolute `threads.rollout_path` and appended one PONG
  turn to the archived original. Before size 1 370 598 B and newline boundary were recorded; the
  appended region was exactly 15 complete rows dated 2026-08-23, a backup SHA-256 was made, and the
  original was restored to 1 370 598 B with final event `2026-07-18 ... task_complete`. The script
  now rewrites and verifies the scratch DB path before launch. This does not change the latency
  result, but it is why `raw-real-history.jsonl` records the post-turn size while [M1] uses the
  pre-turn size.
- Today's separate #229 artifact did not appear in this checkout; no conclusion was copied from it.
- First-round reviewer correctly required a positive MCP discovery control and challenged the
  overstrong A/B/history confidence. The ready+41-tools control and all confidence/table fixes are
  retained here; the dissent remains verbatim in `review-research.md`.

## Historical reconciliation

- **#170/#175:** current result agrees that raw delivery/MCP is not the dominant wall; historical
  long tail followed output/work and extra tool rounds. [H1][H2]
- **#178/#345:** their cost finding (each round-trip replays context) does not prove latency by
  itself, but it explains why behavioral extra rounds can hurt both cost and wall. [H6][H7]
- **#199/#208:** `xhigh` and Fast have task-dependent latency effects, but #240 holds both constant;
  neither is a cross-arm explanation. [H3][H4]
- **#209:** 828 400 effective window reproduces on CLI 0.149.0; a larger cap is capacity, not
  per-turn work until history grows. [H5]
- **#214/#289:** `codex_review` may add a distinct long job (historical median 79 s, p90 180 s),
  but it is not inside B/C/D's ordinary turn transport. A user judging a full phase including
  review may perceive this workflow wall, which #240 PONG excludes. [H8][H9]
- **#323/#327:** old truncation findings depended on smaller caps and stale mirrors. Current live
  cap/file are 262 144/104 615 B, so present truncation is false while prompt weight remains real.
  [H10][H11]

## Smallest next experiment

First reproduce end-to-end behavior with **one exact ordinary user task that previously felt
slow**, without edits, as D/A/D/A on a frozen cwd and Standard/xhigh. Preserve natural tool use
and record per model round:
`turn/start→first model event`, tool local wall, next-model TTFT, output tokens, and total tool-round
count. Pass condition for reproducing the user symptom: D repeatedly exceeds A beyond the A/A noise
band. Only after reproduction, run D-role-on/D-role-off with the same app-server/home/MCP to test
whether the role itself causes extra model/tool rounds. A single read-only task that forces exactly
one named file read is enough for a pilot; a no-tool PONG cannot decide the remaining workflow
hypothesis.

No implementation recommendation is justified before that representative replay.

## Adversarial review

Route: targeted Sol causal-research review, two prose rounds (the skill ceiling).

- Round 1: `NEEDS WORK`; blocking MCP premise accepted. A config/list size did not prove the MCP
  server was active. Added the no-model `starting→ready` + 41/41 status/list positive control and
  corrected every nonblocking calibration issue.
- Round 2: `APPROVED`; reviewer mechanically reproduced 20 authoritative rows, correlations,
  20+6+2 turn accounting and MCP 41/41. Artifact-read evidence is the exact research sentence
  “A one-word answer is ideal for transport isolation and poor for workflow behavior.”
- The sole remaining suggestion was correct: raw TTFT had mixed origins. It was accepted after
  review by replacing the auxiliary correlations with comparable total-to-TTFT. No third round is
  permitted for prose and no blocker remains.

Full first-round dissent and final verdict are preserved in [M13].

## Affected files and risks if a later phase is approved

- `app/backend_jsonrpc.py` — transport; current measured overhead is negligible.
- `app/backend_codex.py` — CLI argv, managed home, connect/resume, turn lifecycle, config digest.
- `app/runtime_registry.py` and `app/session.py` — role prompt/MCP/history assembly and workflow.
- `pipelines/default/prompts/` and `AGENTS.md` — behavior and round count; reducing them can remove
  safety/verification requirements even when latency improves.
- `.codex/skills/` and MCP tool surface — native discovery/tool behavior; removing schemas can
  break capabilities while producing no latency benefit.

## Sources

Official sources fetched in this session (evidence tier 2):

1. [OpenAI Codex App Server documentation](https://learn.chatgpt.com/docs/app-server) — protocol,
   stdio JSONL, initialize/thread/turn lifecycle.
2. [OpenAI Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
   — reasoning effort, service tier, project-doc byte cap.
3. [OpenAI ChatGPT & Codex changelog](https://learn.chatgpt.com/docs/changelog) — CLI 0.149.0,
   2026-08-20.
4. [OpenAI GPT-5.6 Sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol) —
   model id, supported effort and API context surface.
5. [OpenAI Responses API create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
   — Standard/default and explicit Fast/priority service tier semantics.

Current measurements and code/history primary sources (evidence tier 1):

- [M1] [`measurements.md`](measurements.md) — required per-run table and exact argv catalog.
- [M2] [`analysis.json`](analysis.json) — mechanical paired deltas and ranges.
- [M3] [`architecture-snapshot.md`](architecture-snapshot.md) — live argv, config, proxy and code path.
- [M4] [`raw-ab-final.jsonl`](raw-ab-final.jsonl) — authoritative corrected A/B/A/B.
- [M5] [`raw-runs.jsonl`](raw-runs.jsonl) — first layered run and no-model control.
- [M6] [`raw-backend-rerun.jsonl`](raw-backend-rerun.jsonl) — corrected backend usage fields.
- [M7] [`raw-reconnect.jsonl`](raw-reconnect.jsonl) — digest/reconnect control.
- [M8] [`raw-real-history.jsonl`](raw-real-history.jsonl) — real archived-history arm.
- [M9] [`raw-mcp-control.jsonl`](raw-mcp-control.jsonl) — positive ready + 41-tools MCP discovery.
- [M10] [`raw-exec-rerun.jsonl`](raw-exec-rerun.jsonl) — excluded exec oracle-correction pilots.
- [M11] [`measure_latency.py`](measure_latency.py) — isolated benchmark generator.
- [M12] [`summarize_latency.py`](summarize_latency.py) — table/delta generator.
- [M13] [`review-research.md`](review-research.md) — two-round adversarial review and evidence.

Historical local sources reproduced or read (tier 1 for their stated cohorts, not current causal
proof):

- [H1] `docs/tasks/170/research.md`; [H2] `docs/tasks/175/research.md`;
  [H3] `docs/tasks/199/research.md`; [H4] `docs/tasks/208/fast-mode.md`;
  [H5] `docs/tasks/209/research.md`; [H6] `docs/tasks/178/research.md`;
  [H7] `docs/tasks/345/research.md`; [H8] `docs/tasks/214/report.md`;
  [H9] `docs/tasks/289/research.md`; [H10] `docs/tasks/323/state-20260818.md`;
  [H11] `docs/tasks/prompt-cleanup/audit.md` (#327).
