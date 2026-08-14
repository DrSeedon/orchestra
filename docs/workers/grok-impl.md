# grok-impl — личная память

- Приёмка веера «N детей → 1 пробуждение» зелёная и при потерянном тексте: `record_terminal`
  вызывали без `report_path`, `summary` убивался `del summary`. Оракул должен идти через
  прод-пути (`send_message` / `fire_auto_report`) и читать файл из манифеста, не звать
  примитив с уже подставленным путём.
- Живая колонка `fan_members.report_path` может существовать и быть NULL у всех строк —
  наличие схемы ≠ запись. Сначала `SELECT COUNT(*) WHERE report_path IS NOT NULL`.
- `send_message` родителю через веер снова может потерять текст, пока этот фикс не в
  живом процессе: DONE дублируй коротко, длинное — в файл.
- Веер терминален только по `message_kind` ∈ {done,failed,timeout,killed} или по концу
  хода. Факт вызова `send_message` — не сигнал. Мутация одного `is_terminal_report`
  выжила: `record_terminal(None)` и так отвергает state — ломать надо гейт в
  `sessions.py` вместе с хардкодом `"done"`.
