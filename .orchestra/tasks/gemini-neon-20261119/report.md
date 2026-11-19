# Волна 5 — Gemini 4 Neon в Orchestra

- Code: `4c22c7dde8cad42dc8ce3cef314a5a1ae1bdda17`. Base `759b32c41` уже включает указанный `0eede9924`.
- Tested app: `/home/kesha/orchestra-worktrees/gemini-neon-20261119/app`. Live app: `/home/kesha/orchestra/app`.
- 507 изолированных тестов прошли, два предупреждения websockets. Instruction contract и git diff check прошли.
- Live catalog и серверный допуск: 22/22 (16 Gemini, 6 Claude), 6 алиасов Neon. Для Neon задано окно 1M и API-эквивалент $3 / $0.15 / $15 за миллион input/cache/output. Оба фиксированных профиля оркестратора не наследуют общий effort из манифеста.
- Neon и Orchestrator (Neon) входят в Gemini Models. Orchestrator (Argon) перенесён в квотную полосу Argon со всеми существующими правилами допуска. Канонический Argon ID g1-pro остался доступен.
- Рестарт при нуле активных ходов. Оба сервиса active, PID Telegram прежний, `restart_cut_turns=0`. Три чужих изменённых файла сохранены побайтово.
- Один ход через боевой ACP на `antigravity/gemini-4-neon-high`: точный ответ `NEON_SMOKE_OK` за 8.8 с, `end_turn`, вызовов инструментов 0. Временный воркер удалён из активных сессий штатным API.
- `live.json` фиксирует результаты запуска. Внешние оценки из паспорта взяты из [публикации Google](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-neon/) и [карты модели](https://deepmind.google/models/model-cards/gemini-4-neon/). Живой ход проверяет интеграцию, локальные сравнительные оценки не измерялись.
