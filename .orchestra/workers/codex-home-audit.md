# Личная память

- В disposable CodexBackend-пробах переносить `app.backend_codex._CODEX_HOME_ROOT` внутри исследовательского процесса: `CODEX_HOME` меняет базовый источник, но managed root остаётся `~/.orchestra/codex-home`. Фиктивный ORCHESTRA_SESSION_ID сам по себе не изолирует файлы от живого парка; использовать собственный игнорируемый data-каталог worktree.
