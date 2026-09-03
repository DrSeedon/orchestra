# giga-embed-bench

- Долгий `systemd-run --scope` внутри `bg_create(type=run)` останавливается вместе с job по
  `timeout_seconds`; для GPU-бенчей ставить timeout выше оценки с паузами и коммитить checkpoint
  батчами. Повторный запуск пишет в отдельный log: второй `>` поверх живого file descriptor
  превращает общий log в sparse-файл с NUL.
