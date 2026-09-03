# #469 — Muse Spark 1.3 как runtime Orchestra

> Meta Platforms Inc. признана в РФ экстремистской организацией; её деятельность запрещена на территории РФ.

Только Phase 1. Вердикт и рекомендации намеренно отсутствуют по условию задачи.

## Question

- **Context:** Orchestra запускает воркеров через runtime-specific backend, который реализует `BackendLike`, сохраняет native session, переводит native events в `AgentEvent` и объявляет проверенные capabilities.
- **Change under test:** добавить Muse Spark 1.3 как отдельный runtime рядом с `claude`, `codex`, `grok` либо использовать прямой Meta Model API через harness.
- **Baseline:** текущие `backend_claude.py`, `backend_codex.py`, `backend_grok.py`, runtime registry и `ModelSpec`.
- **Measured outcome:** наличие доступного способа оплаты, машины/CLI и headless protocol, документированного и эффективного context, сетевой достижимости через gateway, разрешающей лицензии/весов и сопоставимых benchmark claims.

## Проверяемые альтернативы и фальсификаторы

| альтернатива | что опровергло бы | что измерено |
|---|---|---|
| Runtime поверх официального Muse Code | нет headless structured protocol, resume, interrupt/steer или session id | Muse Code 1.0.2 имеет `exec --json` и `serve`/MSP; stable schema содержит `session/resume`, `turn/steer`, `turn/interrupt`, `session/compact`, `session/setModel` [8][9]. |
| Прямой Meta Model API без Muse Code | API не self-serve/OpenAI-compatible либо Muse Spark 1.3 в нём отсутствует | Официальная страница называет API direct/self-serve и OpenAI SDK compatible; public endpoint отвечает через gateway, но требует API key [4][6][11]. |
| Отдельная проверка production-equivalence | authorised turn + current Orchestra prompt/tools/resume canary проходит без потерь | Такой canary не выполнялся: credentials отсутствуют; текущий `AGENTS.md` Muse Code обрезал на 65,536-byte startup boundary [8]. |

## Запрошенная таблица

| столбец | что именно |
|---|---|
| доступ | **Muse Code subscription:** официальная карточка показывает Everyday `$5.00/month` и `10–50 requests every 5 hours`; High `$15.00/month` и `3x more usage`; Power `$50.00/month` и `10x more usage` [5]. Это product-level request cap с пятичасовой длительностью; token-window semantics неизвестна, weekly bucket на публичной карточке не указан. Карточка Everyday всё ещё говорит `Access to Muse Spark 1.2`, High — `Access to the latest models`, одновременно announcement говорит, что 1.3 доступен в Muse Code; точный tier для 1.3 не назван [1][5]. **Meta Model API:** public preview, direct/self-serve, оплата по токенам; API key, не подписочное окно [4][6]. **OpenRouter:** текущий каталог содержит обе 1.3-модели [12]. **CONFIRMED** для самих поверхностей; **UNCERTAIN** для точного Muse Code tier, token semantics и непубличных rate limits. |
| цена | Дословная таблица Meta: `muse-spark-1.3-contributor` — `Used to improve our products.` — input `$0.10`/M, cached input `$0.002`/M, output `$0.20`/M; `muse-spark-1.3` — `Not used to improve our products.` — input `$1.25`/M, cached input `$0.15`/M, output `$4.25`/M [4][6]. Separate OpenRouter catalog отдаёт те же input/output цены [12]. **CONFIRMED — primary Meta price table; separate catalog cross-check.** |
| клиент | Announcement даёт installer для **macOS/Linux** [1]. Public release manifest 1.0.2-R2040.1 содержит x86/aarch64 binaries для Linux, macOS и Windows плюс universal macOS pkg; сам bash launcher распознаёт только Linux/macOS [7]. Live Linux binary: `Muse Code 1.0.2`; `muse exec --json` — headless JSONL; `muse serve` — stdio MSP JSON-RPC; `muse schema` экспортирует точную JSON Schema/TypeScript bundle [8]. Official `@muse-code/sdk` 0.1.1 — TypeScript, Node ≥20, MIT, Developer Preview/pre-1.0 без stability promise [9][10]. **CONFIRMED — direct binary and registry measurements.** |
| встраиваемость | Текущий Orchestra contract требует `session_id`, `connect`, `send`, async `events`, `interrupt`, `disconnect` (`app/backend_protocol.py:8-16`); registration/factory/capabilities — `app/runtime_registry.py:26-125,330-388`; model/provider/accounting — `app/models.py:21-53,151-251`; session routing зависит от `mid_turn_inject` и `event_stream` (`app/session.py:1351-1433,1638-1642,2171-2178`) [13]. Live binary schema count — 31 method/23 notification [8]; official SDK schema перечисляет lifecycle, token/context usage, approvals, user input, gap paging и subagents [9][14]. Поэтому runtime path потребует: (1) Python MSP subprocess adapter либо Node sidecar с official SDK; (2) mapping `item/*`, `turn/*`, `session/tokenUsage`, `session/contextUsage` → `AgentEvent`; (3) session start/resume, command-id idempotency, `view/gap`, process death и disconnect; (4) точную доставку Orchestra system prompt/project rules и `.mcp.json`; (5) isolated credential/config home + gateway; (6) `ModelSpec`, `ProviderMetadata`, cache/accounting/quota semantics; (7) canaries перед объявлением `mid_turn_inject`, `resume`, `hibernate`, `model_retarget`, `subagents`. Live trusted-workspace probe: Muse ignored `CLAUDE.md` because `AGENTS.md` wins and truncated produced rules from 219,203 to 65,536 bytes [8]. Official stable MSP schema показывает пустой `SessionConfig` и отсутствие free-form `providerRequestOptions` у `turn/start` [14], поэтому system-prompt path отдельно не доказан. **CONFIRMED** для перечисленных seams; **UNCERTAIN** для production capability flags до authorised canary. |
| контекст | Официальная price/model table заявляет `1M` для обеих 1.3-моделей [4][6]; OpenRouter catalog сообщает `1048576` [12]. Но authorised Muse Code `model/list` не измерен: в окружении нет `~/.config/muse/auth.json` и `META_API_KEY`; unauthenticated stable MSP вернул `models: []`, `source: bundledCatalog` [15]. Следовательно, **CONFIRMED** только advertised API window; **UNCERTAIN** effective window/auto-compaction under Meta account subscription. |
| доступность из РФ | Через exact gateway `http://127.0.0.1:12339`: channel endpoint → HTTP 200, `state:"public"`; Meta Model API `/v1/models` → HTTP 401 с `x-route: model-api-rust` и `invalid_api_key`; x86 Linux binary 263,415,992 bytes скачан, SHA256 совпал с manifest [7][11]. Это **CONFIRMED** для transport/download reachability через gateway; authorised generation, signup/payment eligibility и account geo-policy не проверены. Полный вывод: `raw/muse_check.txt`. |
| лицензия и веса | Дословное обещание announcement: `We have an exciting roadmap lined up, including bigger models, the Muse Spark open weights release, and more. Stay tuned.` [1]. Срок не назван. Текущая official model page предлагает Muse Code, Meta Model API и OpenRouter, но не weights download [4]. В public `meta-models` GitHub org найден Muse Code SDK, не model weights; SDK лицензирован MIT, что не является лицензией модели [9]. **CONFIRMED** обещание будущего релиза; **UNCERTAIN** срок, model-weight license и условия коммерческого использования весов. |
| бенчмарки | Все заданные численные claims сверены с raw lossless WebP scorecard на первоисточнике и OCR [2][11]. Подробная таблица ниже. Scorecard использует Muse Spark 1.3 **max**, а announcement говорит, что max появится после дополнительного safety testing; current CLI help перечисляет reasoning до `ultra`, связи `ultra=max` в источниках не найдено [1][8]. **CONFIRMED** как опубликованные Meta значения; comparability caveats ниже. |

## Бенчмарки — проверка каждого claim

| claim из задания | статус | raw scorecard |
|---|---|---|
| MRCR 256K–512K: Muse 98.5 против Sol 91.5 | **подтверждено** | Muse 98.5; Spark 1.2 66.3; Sol 91.5; Opus `-` [2]. |
| MRCR 512K–1M: Muse 98.1 против Sol 73.8 | **подтверждено** | Muse 98.1; Spark 1.2 55.5; Sol 73.8; Opus `-` [2]. |
| DeepSWE: Muse 75.4 против Opus 74.0 и Sol 73.0 | **подтверждено** | Muse 75.4; Spark 1.2 55.0; Sol 73.0; Opus 74.0 [2]. |
| SWEAtlas: Muse 59.4 против Opus 52.7 / Sol 53.5 | **подтверждено** | Muse 59.4; Spark 1.2 46.2; Sol 53.5; Opus 52.7 [2]. |
| Terminal-Bench 2.1: Muse и Sol 88.8 | **подтверждено** | Muse 88.8; Spark 1.2 82.9; Sol 88.8; Opus 86.7 [2]. |
| В agent section Opus впереди Muse на 4 из 6 | **другое значение** | По primary metrics из methodology Opus выше Muse на **6/6**: GDPVal 1824>1754; JobBench 65.7>64.9; OSWorld partial 68.3>66.9; DeepSearchQA 90.4>89.4; IF Index 59.1>57.8; AutomationBench 50.3>49.4. Если вместо primary OSWorld partial взять secondary binary, Muse 32.0>31.4 и получится Opus **5/6**, не 4/6 [2][3]. |

Mechanical completeness check: `raw/muse_benchmark_check.txt` содержит SHA256 scorecard/PDF и полный `tesseract --psm 11` output; OCR нашёл все заданные значения. Scorecard SHA256: `6d9e135ffcd12edf733c9b779d22fd57fed1f8e561906bee5ccc16ebf9da5d68`.

## Counter-evidence and limits

- Meta methodology сообщает, что для каждой модели публикуется highest comparable primary value из собственного прогона, official leaderboard или provider self-report; это не один одинаковый A/B harness [3].
- Third-party runs названы best-effort; prompts/tools/runtime могут быть не настроены под proprietary models [3].
- DeepSWE: Muse запущен Meta через mini-swe-agent, остальные значения взяты с Datacurve leaderboard; Terminal-Bench: internal Meta harness, Sol value — model card [3].
- MRCR — 100 examples на каждый band, 8-needle, OpenAI data re-binned по `o200k_base`; это retrieval без agent tools [3].
- Benchmark 1.3 max опубликован до заявленной доступности max режима; current binary не документирует соответствие `ultra` и `max` [1][8].
- Official SDK облегчает idempotency/fold/gap handling, но он TypeScript-only и pre-1.0; прямой Python adapter обязан повторить эти protocol invariants самостоятельно [9].
- Current binary reports stable schema fingerprint `sha256:03312c…`, while official SDK commit `fbce769…` pins `sha256:cfd31e…`; counts remain 31/23, but exact schema snapshots differ [8][14].
- Trusted-workspace echo probe ran with `--no-session-log`, so local session messaging was disabled; it also reported one malformed imported `computer-use` skill. The probe establishes rule precedence/truncation, not full messaging/MCP compatibility [8].
- Authorized Muse turn, effective context, exact subscription quota consumption, Russian account signup/payment, MCP startup/recovery, resume after process death and full untruncated Orchestra prompt delivery не измерялись.

## Affected files, risks, edge cases

Research-only; production files and tests were not modified.

- Contract/registry: `app/backend_protocol.py`, `app/runtime_registry.py`, `app/models.py`, `app/session.py` [13].
- A runtime would also need its own backend module and focused tests; no filename or implementation is selected in Phase 1.
- Edge seams: 65,536-byte rule truncation; `AGENTS.md` precedence over `CLAUDE.md`; foreign personal context import; Developer Preview protocol churn/fingerprint mismatch; view gaps; server-initiated approvals/user input; command replay/idempotency; durable vs ephemeral session profile; binary auto-update/pinning; two billing/data-use model ids; max-vs-ultra naming; API vs subscription quota accounting; gateway reachability without account eligibility.

## Raw evidence

- `raw/muse_check.txt` — full gateway network output required by the task.
- `raw/muse_cli_check.txt` — live binary version/help, echo completion, MSP handshake/schema counts, trusted-workspace truncation.
- `raw/muse_benchmark_check.txt` — raw image/PDF hashes and full OCR output.
- `raw/muse_pricing_check.txt` — exact rendered official subscription/API pricing sections and DOM hashes.
- `raw/muse_announcement_check.txt` — exact announcement lines found in curl-downloaded source.
- `raw/muse_release_check.txt` — exact public release-manifest platform/checksum projection and launcher platform switch.
- `raw/muse_sdk_check.txt` — official SDK commit, preview/stability/license text and npm registry metadata.
- `raw/muse_schema_check.txt` — official SDK schema counts, method/notification lists, `SessionConfig` and `TurnStartParams` extraction.
- `raw/muse_model_list_check.txt` — exact unauthenticated MSP `model/list` tool output recovered from this session log.
- `raw/research_checks.txt` — mechanical completeness, `git diff --check` and KB-contract result.

## Sources

1. [Meta AI Research — Introducing Muse Spark 1.3](https://research.meta.ai/blog/introducing-muse-spark-1-3), raw HTML fetched 2026-09-03 — **tier 2, primary announcement**.
2. [Raw benchmark scorecard](https://research.meta.ai/articles/introducing-muse-1-3/benchmarks/benchmark-scorecard-v5.webp), fetched 2026-09-03 — **tier 2, primary published score table**.
3. [Muse Spark 1.3 Evaluation Methodology](https://research.meta.ai/static/muse-spark-1-3-multimodal-evaluation-methodology), raw PDF fetched 2026-09-03 — **tier 2, primary methodology**.
4. [Muse Spark 1.3 model page](https://developer.meta.com/ai/models/muse-spark/), rendered official DOM fetched 2026-09-03 — **tier 2, primary product/price page**.
5. [Muse Code product page](https://developer.meta.com/ai/products/muse-code/), rendered official DOM fetched 2026-09-03 — **tier 2, primary subscription page**.
6. [Meta Model API product page](https://developer.meta.com/ai/products/meta-model-api/), rendered official DOM fetched 2026-09-03 — **tier 2, primary API/price page**.
7. [Official installer](https://dev.meta.ai/install.sh), [launcher](https://api.meta.ai/muse-launcher.sh), [public channel](https://api.meta.ai/muse-code/channels/muse-stable) — **tier 2 + tier 1 live download measurement**.
8. Muse Code 1.0.2-R2040.1 live binary probes in `raw/muse_cli_check.txt` — **tier 1, direct measurement**.
9. [meta-models/muse-code-sdk](https://github.com/meta-models/muse-code-sdk) at `fbce769ccb75ab971d00e01a00fe076de4c773fc` — **tier 2, official source/protocol SDK**.
10. [npm `@muse-code/sdk`](https://www.npmjs.com/package/@muse-code/sdk) registry metadata, 0.1.1 — **tier 2, primary package registry**.
11. Gateway, API and OCR outputs in `.orchestra/tasks/469/raw/` — **tier 1, direct measurement**.
12. [OpenRouter models catalog](https://openrouter.ai/api/v1/models), fetched 2026-09-03 — **tier 2 for OpenRouter route; independent corroboration of Meta pricing/context**.
13. Current Orchestra source: `app/backend_protocol.py:8-16`, `app/runtime_registry.py:26-125,330-388`, `app/models.py:21-53,151-251`, `app/session.py:1351-1433,1638-1642,2171-2178` — **tier 2, primary source code**.
14. [Official stable MSP schema](https://raw.githubusercontent.com/meta-models/muse-code-sdk/fbce769ccb75ab971d00e01a00fe076de4c773fc/schema/msp/stable/msp.schema.json) and manifest, extracted in `raw/muse_schema_check.txt` — **tier 2, official source/protocol schema**.
15. `raw/muse_model_list_check.txt` — **tier 1, direct measurement recovered byte-for-byte from this session's stored tool result**.

## Review gate inputs

- Changed consumers: research/KB only; no production consumer changed.
- Author runtime: Codex full-cycle worker (`research-muse-spark` session metadata), not inferred from name.
- AC: every requested table row populated; every supplied benchmark number marked confirmed/not found/different; raw gateway output attached; no recommendation or verdict.
- Mechanical checks: raw scorecard OCR, exact pricing-section extraction, SDK/binary schema probes, gateway command output, KB contract check (recorded after review).
- Selected route: docs/fact extraction → mechanical completeness + one Luna completeness pass under `codex-debate`.

## Review outcome

- Luna round 1: no blocking findings; verdict `APPROVED WITH NON-BLOCKING CHANGES` in `review-luna-research.md`.
- Accepted suggestions: removed the accidental adoption verdict; separated request cap from token-window semantics; attached the missing `model/list` result; attached exact schema-derived protocol details; recorded trust-probe warnings.
- No second round: the review had no blocking finding, so `codex-debate` does not authorize another prose round merely to re-check suggestions.
