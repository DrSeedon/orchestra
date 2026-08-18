Memory: reusable
- Для батчевых gate-ов с общим wall-clock-бюджетом не резать бюджет «по частям наперед»; вычислять `timeout = remaining_budget / batches_left` перед каждым запуском.
- Прогонять более мелкий (partial) батч первым помогает убирать ложные таймауты на `N % MAX_TEST_FILES` хвостах.
