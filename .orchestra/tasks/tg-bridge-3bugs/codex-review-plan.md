# Codex review — PLAN (GPT-5.5)

## Verdict: APPROVE with fixes (все применены)

- `_result_images_enabled` opt-in (TG_RESULT_IMAGES=true) vs `_diff_images_enabled` opt-out
  (TG_DIFF_IMAGES=false) — **корректно**. Result/Read/Grep images = explicit opt-in,
  Edit/Write diffs = on by default. Флуд-контрол переписывать не нужно для этого MVP-фикса.

## Blocking (применено)
- `_tg_send_safe` warning должен использовать `except Exception as e2:` — иначе краш при
  повторном фейле ретрая. ✅ применено.

## Suggestions (применено)
- Обновлять `_last_send` после успешного флуд-ретрая, иначе следующий send уйдёт сразу →
  новый флуд. ✅ применено.
- `send_file_to_tg`: использовать `topics.get(sender)` (truthy-проверка) вместо `sender in topics` —
  если `topics[sender]` = None/0/stale, должно падать в fallback `_find_orch_for_scope`, а не
  возвращать ошибку «no TG topic». ✅ применено (`sender_thread = topics.get(sender)`).
- PIL-проверка: импортить точные модули `from PIL import Image, ImageDraw, ImageFont` (как в
  app.diff_image), а не только `import PIL` — точнее ловит битую установку. ✅ применено.
- Тесты на cached `_pil_available`: env-gate тесты `_diff_images_enabled` начнут зависеть от
  наличия Pillow — сбросить/замокать `_pil_available`; добавить тест на single-warning caching
  и на отсутствие PIL. ✅ применено (фикстура сбрасывает _pil_available, TestCheckPil,
  test_false_when_pil_missing).

## Question
- Mirror файлов в топик sender при routing по sender: план говорит да, внутренне консистентно.
  Если у воркер-топиков нет mirror — тихий no-op. Приемлемо (mirror опционален). Принято как есть.
