# V-690 — медиа-комплект для README.ru.md

Запрос владельца от 04.10.2026 14:25: русский скриншот и немая GIF, русскоязычный ролик с тем же сценарием и качеством, что V-686, в четырёх голосах Vosk (`speaker 0`, `1`, `3`, `4`). README.ru.md не менять; MP4 для GitHub владелец загружает вручную.

## Стенд и данные

Основа стенда — `git archive HEAD` в `/home/kesha/readme-stand-V690/orchestra`; dashboard-код из текущего worktree не запускался. Стенд использовал отдельную БД и каталог Acme Shop, без реальных CLI-сессий, `.env`, Telegram-моста и автоматического восстановления. `stand.py` проверяет импорт `app` из архивной копии и недоступность `claude`, `codex`, `grok`; стендовый `PATH` содержит только `git`, `sh`, `bash`, `env`, `cat`, `ls`. Порт — 8897. Записано 1106 кадров за 55,5 с страницы. После съёмки сервер остановлен, порт свободен.

Съёмка шла с `orch_lang=ru` и браузерной локалью `ru-RU`. Даты показываются по-русски; браузерный сценарий стенда форматирует цены как `$4,35`, не меняя product JS. Общий форматтер `fmtCost` уже записан как follow-up в `TODO.md` (V-686). Сообщения владельца и оркестратора, карточки, отчёты, ревью и результаты тестов написаны по-русски; пути, команды, API и идентификаторы кода сохранены.

Сценарий: двойное списание после обновления Stripe SDK; параллельная работа; отчёт воркера; проверка diff; 48/48 тестов; мерж без выкладки; возврат средств ждёт разрешения владельца. При съёмке исправлено условие завершения русской карточки `#2`: после мержа она переходит в Done по своему русскому названию.

## Видео и Deepgram

| Vosk | Длительность | Минимум recall | Сдвиг начала звука (макс.) | Запас камеры (мин.) | Telegram | GitHub |
|---|---:|---:|---:|---:|---:|---:|
| `speaker 0 / female_0` | 85,1 с | 0,89 | 0,03 с | 0,156 с | 9 584 134 B | 5 276 966 B |
| `speaker 1 / female_1` | 68,5 с | 0,90 | 0,00 с | 0,135 с | 8 963 250 B | 4 827 598 B |
| `speaker 3 / male_0` | 74,4 с | 0,92 | 0,03 с | 0,155 с | 9 047 132 B | 4 951 521 B |
| `speaker 4 / male_1` | 71,8 с | 1,00 | 0,03 с | 0,147 с | 9 041 329 B | 4 976 942 B |

Deepgram проверил звук каждого итогового MP4. Локальный ключ передавался удалённой сборке только через stdin. После первой проверки упростили две фразы: `speaker 1` пропускал названия моделей (recall 0,77), а `speaker 3` — термин «воркер» и предлог (0,80). Все четыре версии пересобраны с одинаковым сценарием; итоговые показатели приведены в таблице. У `speaker 0` Deepgram поставил первое слово фразы про аналитику на 0,75 с раньше плана, при этом распознавание фразы — 1,00, а начало её звука — +0,03 с; это outlier выравнивания слова, не позднее начало звука.

В каждом голосе камера приходит раньше фразы: минимум на 0,135 с по измеренному Deepgram началу звука. В сцене `CAM_POST=.14`, вступление Vosk при `--rate 1.25` — 0,28 с.

## GIF и скриншот

- Скриншот дашборда: 3200×1880, 525 423 B; русский интерфейс, тестовые сообщения и формат цены `$4,35`.
- GIF: 1000×563, 10 fps, 58,6 с, 586 кадров, 9 211 365 B, `loop=0`. Сцена начинается с русской постановки задачи без номера шага, затем показывает разбор, воркеров, отчёт, тесты, мерж, доску, квоты и аналитику. После измерения граничного кадра начало перенесено за появление текста и камеру; финал плавно возвращается к тому же виду задачи. Контакт GIF просмотрен.
- Контакт-листы всех четырёх MP4 просмотрены: кадры не обрезаны, подписи читаемы, сцены в нужном порядке.

## Проверки и ограничения

- `read_steps` подтвердил 17 русских фраз `say` без латиницы и цифр.
- `bash -n` прошёл для сценариев стенда и сборки медиа.
- `.env` отсутствует в копии стенда; БД отдельная; `.orchestra/projects.yaml` не запускался через dashboard-код worktree и не менялся.
- README.md и README.ru.md не редактировались. В `docs/` добавлены только новые `*.ru.*`; GitHub не открывался, ничего не опубликовано и не загружено. HTML-черновик вставки — `readme-draft.md`.

## Все MP4, GIF и PNG

MP4 для Telegram:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker0-female_0-telegram.mp4`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker1-female_1-telegram.mp4`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker3-male_0-telegram.mp4`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker4-male_1-telegram.mp4`

MP4 для GitHub:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker0-female_0-github.mp4`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker1-female_1-github.mp4`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker3-male_0-github.mp4`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/orchestra-tour-voskspeaker4-male_1-github.mp4`

GIF:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/docs/dashboard-live.ru.gif`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/dashboard-live.ru.gif`

Скриншот:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/docs/dashboard-real.ru.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/media/dashboard-real.ru.png`

Контакт-листы MP4:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/orchestra-tour-voskspeaker0-female_0-contact.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/orchestra-tour-voskspeaker1-female_1-contact.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/orchestra-tour-voskspeaker3-male_0-contact.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/orchestra-tour-voskspeaker4-male_1-contact.png`

Контакт-лист GIF:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/gif-contact.png`

Скриншоты сцен, используемые при сборке ролика:

- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/img/agents.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/img/merge.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/img/plan.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/img/tasks.png`
- `/home/kesha/orchestra/worktrees/home-kesha-orchestra/feat-readme-ru/.orchestra/tasks/V-690/video/img/worker.png`
