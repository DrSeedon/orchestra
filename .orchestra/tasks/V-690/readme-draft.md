# Черновик медиа-блока для README.ru.md — не применён

Вставить после вводного описания Orchestra, перед «Быстрым стартом». Существующий абзац с `docs/dashboard.png` заменить этим блоком.

```html
<p align="center">
  <img src="docs/dashboard-live.ru.gif" alt="Дашборд Orchestra: постановка задачи, разбор, работа воркеров, отчёт, проверка, тесты и мерж; доска задач и история квот" width="100%">
  <br>
  <em>Работа команды в реальном времени: от постановки задачи до мержа, доски задач и квот</em>
</p>

<p align="center">
  <strong>🎬 Видео-тур с озвучкой на русском:</strong>
</p>
```

После выбора голоса владелец перетаскивает соответствующий `*-github.mp4` в редактор README на github.com. GitHub вставит ссылку `https://github.com/user-attachments/assets/<UUID>`; её нужно поставить отдельным абзацем здесь:

```markdown
https://github.com/user-attachments/assets/ВСТАВИТЬ-ССЫЛКУ-ОТ-GITHUB
```

После ссылки вставить скриншот:

```html
<p align="center">
  <img src="docs/dashboard-real.ru.png" alt="Дашборд Orchestra на русском: сообщения оркестратора, воркеры, задачи, статусы и квоты" width="100%">
  <br>
  <em>Дашборд на русском языке с демонстрационными данными</em>
</p>
```

## Файлы для выбора и переноса

- `media/dashboard-live.ru.gif` → `docs/dashboard-live.ru.gif`
- `media/dashboard-real.ru.png` → `docs/dashboard-real.ru.png`
- Выбранный `media/orchestra-tour-<голос>-github.mp4` владелец загружает через GitHub; видео не коммитится в README и не публикуется агентом.

Голоса для сравнения: `speaker0-female_0`, `speaker1-female_1`, `speaker3-male_0`, `speaker4-male_1`. Для Telegram рядом лежит полный файл `*-telegram.mp4`.
