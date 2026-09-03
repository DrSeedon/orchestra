# bench-effort

- Codex app-server возвращает фактический `serviceTier=default` для Standard и
  `serviceTier=priority` для Fast. В бенчмарке валидировать wire-response до первого платного
  хода, а не сопоставлять его с названием запрошенного режима.
- Изолированный вызов Codex app-server обходит Orchestra `turn_usage`. Для таких замеров считать
  local API-equivalent `$` из provider token telemetry той же формулой, что текущий код, и не
  смешивать эту оценку с provider credits или subscription quota без отдельной калибровки.
