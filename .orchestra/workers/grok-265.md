# grok-265 — личная память

- Фильтр `pytest -k "mcp or identity or canary"` уже зелёный на старых тестах: в именах есть
  `mcp`/`identity`, канарейки там нет. Зелёный прогон названной команды ≠ дыра закрыта.
- Grok 1.0.3 `agent stdio` переписывает `$GROK_HOME/config.toml` сразу после initialize:
  наши `[features]`/`[telemetry]`/`[compat.*]` оставляет, дописывает `[cli]`/`[ui]`/`[marketplace]`,
  комментарии снимает. Наблюдение #264 «пропали features/telemetry» на 1.0.3 не воспроизвелось.
- Мутация под `set -e`: падение мутанта обрывает `mv .bak` — откат писать так, чтобы pytest
  не был в том же `&&`-хвосте, что restore.
