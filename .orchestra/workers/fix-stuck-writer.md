# fix-stuck-writer

- Диагностика writer Codex: сопоставляй inode и major/minor lock-файла с `/proc/locks`; путь `thread-writer-locks/<thread>.lock` сам по себе не означает занятый lock. PID владельца и PID node-обёртки различаются. Нельзя выводить отсутствие процесса из `sessions.cli_pid=0`.
