> **SUPERSEDED SCOPE — 2026-08-13.** Both rounds below reviewed the pre-Latvia-account
> negative report. After this review, a supported-region account passed eligibility and live
> tools, exact resume, isolation and MCP probes changed the evidence base. The `APPROVED` verdict
> below does **not** approve the final `research.md`. The prose review round ceiling was exhausted,
> so no third round was run.

## Summary

Исследование обоснованно рекомендует не начинать интеграцию: ни один успешный agent turn не выполнен, а tools, MCP, inference entitlement и точный resume не подтверждены. Различие model registry и inference entitlement, а также Jio-specific gaps описаны корректно.

Главный недостаток — причинность account region и бесполезность покупки Pro сформулированы как доказанные, хотя доступные наблюдения показывают сильную корреляцию, но не отделяют account region от account-specific/backend eligibility logic.

Подтверждение чтения артефакта — точная строка из `research.md`, которой не было в prompt:

> «Промо может исчезнуть в середине сессии; сохранённый OAuth token тогда ещё может быть валиден, поэтому наличие файла не является entitlement probe.»

## Findings

suggestion: [research.md:45] Формулировка «Точная причина — associated region Google-аккаунта» сильнее доказательств. Два Russia-associated аккаунта действительно получили одинаковый location error с разрешённого egress, а документация направляет к ToS-country. Но нет контрольного аккаунта с поддерживаемым ToS-country, и сам отчёт на строках 225 и 432 сохраняет альтернативу account-specific/backend bug. Корректнее: «наиболее вероятный и адресно подтверждённый blocker для этих аккаунтов — associated region; точная серверная причинность не изолирована». IP-only объяснение опровергнуто, но участие IP в комбинации сигналов — нет.

suggestion: [research.md:47, research.md:227, Confidence summary] «Покупка AI Pro на втором аккаунте ничего бы не изменила» и `REFUTED` также переоценивают free-account control. Одинаковый отказ показывает, что бесплатный аккаунт не прошёл eligibility, но не доказывает порядок внутренних tier/region checks и не исключает plan-dependent `eligibleTiers` или исключение для платного аккаунта. Практический вывод «не покупать Pro ради непроверенного обхода» силён; контрфактическое утверждение следует пометить `UNTESTED / no evidence that Pro bypasses the gate`, а не `REFUTED`.

question: [research.md:202, research.md:307] В разделе 4.3 написано, что geography «остановила запрос раньше» определения Jio quota, однако прямого server trace порядка проверок нет. Это вывод из пустой usage/turn и одинаковой ошибки или задокументированный контракт `loadCodeAssist`? Если только вывод, слово «раньше» следует заменить на наблюдаемое: «ответ не раскрыл tier/quota и не позволил проверить entitlement».

suggestion: [research.md:316] `CONFIRMED для wire shape` охватывает больше, чем измерено. Live подтверждён только terminal error frame; успешные `init`, `step_update`, tool events, usage и завершение известны из changelog/schema. Лучше разделить: terminal error frame — `CONFIRMED`; полный successful stream shape/parser suitability — `LIKELY / untested live`.

suggestion: [research.md:332, research.md:434] Root-conversation-ID риск реален и независим от geography, но слово `BLOCKER` следует связать с конкретным deployment mode. Текущий код действительно разрешает sessions без worktree, где несколько сессий могут делить `cwd`; там `-c` — небезопасный mutable pointer. Для обычных workers с уникальными worktrees `-c` потенциально может обеспечить изоляцию. Непустой ID остаётся обязательным критерием, если runtime должен поддерживать весь существующий `SessionManager` contract, но это `unverified release gate`, а не доказанная поломка всех multi-worker конфигураций.

suggestion: [research.md:347-365] Требование preflight хорошо выведено из позднего `connect()`, но конкретная политика `/quota` перед каждым spawn и глобальный circuit breaker представлена как `CONFIRMED architectural requirement`. Код доказывает credential-validation hole, не единственную архитектуру исправления. Preflight до публикации и громкая terminal classification обязательны; частота `/quota`, breaker scope и новый статус `credential_lost` — пока design proposals и должны быть так обозначены.

## Verdict

Нет blocking findings по заданной шкале: исследование ничего не реализует и не создаёт crash/corruption/security risk.

Вердикт: **решение “Phase 1 остановить, backend сейчас не писать” одобрено**, но отчёт требует смысловой правки перед использованием как окончательного основания: понизить causal claims про точную account-region причину и невозможность Pro bypass с `CONFIRMED/REFUTED` до `most likely / untested`. Registry-vs-entitlement, Jio gaps и независимый exact-resume gate выдерживают проверку.

## Round (2026-08-13T07:48:14Z)

## Re-review status — Round 2

1. Account-region causality — **FIXED**. It is now a document-supported operational blocker, while combined signals/backend bugs remain possible.

2. Buying Pro on the second account — **FIXED**. The claim is properly limited to rejecting it as a supported practical workaround, backed by paid/free matched-region arms and the FAQ.

3. Tier/region check ordering — **FIXED**. The report explicitly says internal ordering is unknown.

4. Successful stream shape — **FIXED**. Terminal error framing is confirmed; successful streaming is `LIKELY / live untested`.

5. Root conversation ID — **FIXED**. It is now an unverified release gate for the full `SessionManager` contract, with unique-worktree `-c` isolation acknowledged.

6. Credential preflight architecture — **FIXED**. Pre-publication detection is the requirement; `/quota`, breaker scope, and `credential_lost` are proposals.

## New findings

None. A few summary bullets retain stronger shorthand such as “до тарифа” and “blocker,” but the detailed findings and confidence table explicitly constrain their meaning; they do not materially distort the verdict.

`git diff -- <reviewed files>` returned empty, so there was no unstaged diff to compare; this review used the current `research.md` contents.

Exact updated line not present in the request:

> «Это вывод о поддерживаемости наших аккаунтов по документированному product gate, не reverse engineering внутреннего порядка server checks.»

## Verdict

**APPROVED.** No blocking findings remain. Phase 1 should stop with the stated verdict: do not implement Antigravity until eligibility and the independent tools/MCP/exact-resume release gates pass.
