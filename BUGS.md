# Orchestra Bug Reports — переехали из этого файла

Этот файл больше НЕ живой. `report_bug` пишет мимо него — в инбокс вне рабочего дерева,
поэтому баг-репорт не пачкает checkout и не блокирует мержи.

## Как посмотреть репорты

- **Дашборд** — баннер «🐛 Новые bug reports» вверху справа, кнопка «Прочитать».
  Появляется сам, когда есть непрочитанное.
- **Ручкой** — `GET /api/report_bug` отдаёт весь инбокс одним Markdown-документом
  (legacy + все репорты). `GET /api/report_bug/status` — только счётчик и версия.

## Где лежит на диске

Корень состояния зависит от того, задан ли `StateDirectory` в systemd-юните:

| Условие | Путь к инбоксу |
|---|---|
| В юните есть `StateDirectory=orchestra` (VPS, `deploy/orchestra.service.template`) | `/var/lib/orchestra/bug-inbox/` |
| `StateDirectory` нет → fallback на XDG (локальная машина) | `$XDG_STATE_HOME/orchestra/bug-inbox/`, по умолчанию `~/.local/state/orchestra/bug-inbox/` |

Проверить конкретную машину: `systemctl cat orchestra | grep StateDirectory`.

Внутри инбокса:
- `legacy.md` — снимок этого файла на момент переезда (341 строка, всё что было открыто на
  01.08.2026). Неизменяемый, читается первым.
- `records/*.md` — по одному файлу на репорт, имя `<UTC-timestamp>-<uuid>.md`.

Историю самого файла хранит Git: `git log -- BUGS.md`, последняя живая запись — `d1429b1`.
