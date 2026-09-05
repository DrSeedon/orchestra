<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Вот и приехал legacy-кейс — старые записи, как обычно, оплатили совместимость своим здоровьем 🧨

## Summary

В diff найдено одно blocking-замечание: восстановление handoff с legacy `packet_json` без `integrity` теперь ломается на подтверждении.

## Findings (blocking/suggestion/question)

### [P1] Сохранять legacy hash-контракт при подтверждении

**File:** `app/db.py:2508-2511` | **Confidence:** 0.99

Для legacy ledger-пакета без `integrity` `_stage_runtime_handoff_target` всё равно строит delivery-пакет и сохраняет его новый hash (`app/session.py:3872-3875`). Но здесь ветка пересчёта пропускается, поэтому `expected_candidate_sha256` остаётся равным legacy `handoff["packet_sha256"]`. В результате `attempt["candidate_sha256"]` не совпадает с ожидаемым hash, и `confirm_runtime_handoff` отвергает восстановление на стадиях `packet_delta` и `fallback_packet`, хотя staging и capability уже успешно завершены.

## Verdict

**Overall Correctness:** ❌ Incorrect | **Confidence:** 0.99

Новый hash-контракт согласован для современных пакетов, но несовместим с сохранёнными legacy handoff-записями без `integrity`; это блокирует идемпотентное восстановление и подтверждение таких операций.

Проверка целевых тестов не завершилась из-за отсутствующего локального `dotenv`; сам committed diff проверен командой из запроса. Старый handoff, конечно, решил стать археологическим артефактом именно в момент восстановления.

## Round (2026-09-05T11:53:38Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

P1 — **FIXED**. В новой дельте hash для `packet_delta` и `fallback_packet` пересчитывается одинаково на staging и confirm; `native_resume` сохранён отдельно.

## Findings (blocking/suggestion/question)

ACK — `expected_candidate_sha256 = packet["integrity"]["canonical_sha256"]`

Повреждённый или нечитаемый `packet_json` в `confirm_runtime_handoff` приводит к исключению до изменений состояния; транзакция откатывается, подтверждение не выполняется.

## Verdict

Новых замечаний нет. Контракт hash между staging → ingress canary → capability → confirm согласован для всех трёх режимов. Legacy-путь закрыт — на этот раз старый пакет не пришлось приносить в жертву богам SQLite.
