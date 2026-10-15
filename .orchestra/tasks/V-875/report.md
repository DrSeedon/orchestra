# V-875: оценки шагов чеклиста и хронометраж

- Чеклист хранит `step_id` и `estimate_minutes` на шаг; таблица `checklist_step_metrics` копит `actual_seconds` (накопительно, `active_since` для текущего шага), модель и проект.
- Напоминание привязано к оценке текущего шага (fallback 5 минут без оценки).
- `estimate_accuracy_report`: медиана/IQR отношения факт/оценка по моделям; шаги без замера и с нулевой оценкой считаются отдельно.
- UI: оценка и живое время в панели Info (desktop/mobile скриншоты рядом).
- Проверки: tests/test_checklists_v858.py + test_routes_surface.py — 15 passed; browser suite — 201 passed, 7 skipped.
- Python-правки требуют рестарта Orchestra (по команде владельца).
