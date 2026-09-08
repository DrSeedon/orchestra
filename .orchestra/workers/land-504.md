# Рабочие заметки

- `bg_create(type="run")` может не наследовать `XDG_RUNTIME_DIR` и `DBUS_SESSION_BUS_ADDRESS`, хотя обычный exec их видит. Для `systemd-run --user --scope` сначала прочитать значения в exec и проверить socket, затем передать их в background command явно.
- У `scripts/check_kb_contract.py` параметр `--diff` принимает файл unified diff, не Markdown-тему. Передача темы печатает OK при нуле разобранных добавлений. Сохранять настоящий git diff и проверять, что `parse_changed_lines` увидел все новые строки; `--root .orchestra/kb` всё равно обязателен.
