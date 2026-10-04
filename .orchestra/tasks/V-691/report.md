# V-691 — explainer-video на ноутбуке

Настройка выполнена на `maxim-911aird` (`maxim`) через обратный SSH-туннель. Проектный
checkout остался на `main` `8155e9d1`; установлены инструменты вне репозитория, приложение
не менялось.

## Установка

- `/mnt/data/Apps/orchestra-video/orchestra-manim`: micromamba, Python 3.12, ManimCE 0.20.1,
  TinyTeX / TeX Live 2026 с пакетами из V-685; `MathTex` с `\text{сжатия}` и `\text{мин}`
  отрендерился.
- `/mnt/data/Apps/orchestra-video/orchestra-tts`: Python 3.12, `vosk-tts` 0.3.61 и модель
  Vosk `vosk-model-tts-ru-0.9-multi`; `/en`: `kokoro-onnx` 0.6.1, Kokoro-82M `af_heart`.
- `/mnt/data/Apps/orchestra-video/playwright`: изолированный Playwright 1.61.0;
  `/mnt/data/Apps/orchestra-video/ms-playwright`: Chromium Headless Shell 149.0.7827.55.
  Разделение нужно для Ubuntu 26.04: Playwright 1.60.0 из checkout не поддерживает эту ОС.
  Рецепт `explainer-video.md` дополнен проверенным вариантом без изменения lockfile.
- Крупные данные и uv-кэш лежат на `/mnt/data`; `~/.local/share/orchestra-manim` и
  `~/.local/share/orchestra-tts` указывают на установленные каталоги. Установка занимает
  4.0 GiB суммарно: Manim 1.9G, TTS 1.4G, Playwright 138M, Chromium 646M, uv-кэш 333M.
  Сборочные файлы V-691 на ноутбуке занимают 73M; после установки на `/` осталось 18G,
  на `/mnt/data` — 103G.

Vosk-модель уже была на VPS. Прямая загрузка на ноутбук с alphacephei за час принесла 93 KiB
и зависла; завершённую модель перенёс `rsync --partial --append-verify` через туннель.
Пакеты TinyTeX поставлены через `https://mirror.ctan.org/systems/texlive/tlnet` после
ошибки контрольной суммы зеркала по умолчанию.

## Пробные ролики

| Движок | Файл | Длительность | Размер | Контакт-лист |
|---|---|---:|---:|---|
| HTML + Vosk ru | `video/cache-ttl.mp4` | 55.9 с | 3.0 MB | просмотрен: `review/ru-html.png` |
| HTML + Kokoro en, `af_heart` | `video/english-smoke.mp4` | 32.4 с | 1.1 MB | просмотрен: `review/en-html.png` |
| Manim + TinyTeX, Vosk ru | `video/compact55.mp4` | 60.4 с | 4.1 MB | просмотрен: `review/manim-latex.png` |

Все три MP4 — 1920×1080, 30 fps; собраны на ноутбуке и скопированы в `video/` этой задачи.
Deepgram-ключа в SSH-окружении нет, поэтому проверка распознаванием пропущена; recall и
сдвиг начала речи не измерялись.

## Повторение

Сначала, на VPS, подготовить каталог и передать локальную модель Vosk на ноутбук:

```sh
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222 maxim@127.0.0.1 'mkdir -p /mnt/data/Apps/orchestra-video/orchestra-tts/vosk-model-tts-ru-0.9-multi'
rsync -a --partial --append-verify -e 'ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222' /home/kesha/.local/share/orchestra-tts/vosk-model-tts-ru-0.9-multi/ maxim@127.0.0.1:/mnt/data/Apps/orchestra-video/orchestra-tts/vosk-model-tts-ru-0.9-multi/
scp -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -P 2222 .orchestra/tasks/V-691/setup-laptop.sh maxim@127.0.0.1:/mnt/data/Apps/orchestra-video/setup-laptop.sh
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222 maxim@127.0.0.1 'systemd-run --user --scope -p MemoryMax=2G -- nice -n 15 bash /mnt/data/Apps/orchestra-video/setup-laptop.sh'
```

Передать три сцены на ноутбук, затем собрать их там:

```sh
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222 maxim@127.0.0.1 'mkdir -p /mnt/data/Projects/Python/orchestra/.orchestra/tasks/V-691/scenes'
scp -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -P 2222 .orchestra/tasks/V-691/scenes/cache-ttl.html .orchestra/tasks/V-691/scenes/english-smoke.html .orchestra/tasks/V-691/scenes/compact55.py maxim@127.0.0.1:/mnt/data/Projects/Python/orchestra/.orchestra/tasks/V-691/scenes/
ssh -i /home/kesha/.ssh/tunnel_laptop -o IdentitiesOnly=yes -o BatchMode=yes -p 2222 maxim@127.0.0.1 'systemd-run --user --scope -p MemoryMax=2G -- nice -n 15 bash -s' <<'LAPTOP'
cd /mnt/data/Projects/Python/orchestra
export PLAYWRIGHT_BROWSERS_PATH=/mnt/data/Apps/orchestra-video/ms-playwright
PY=/mnt/data/Apps/orchestra-video/playwright/bin/python
$PY scripts/explainer_video/make.py .orchestra/tasks/V-691/scenes/cache-ttl.html --out .orchestra/tasks/V-691/video/ru-html --rate 1.25 --speaker 3 --jobs 3
$PY scripts/explainer_video/make.py .orchestra/tasks/V-691/scenes/english-smoke.html --out .orchestra/tasks/V-691/video/en-html --lang en --voice af_heart --rate 1.1 --jobs 3
$PY scripts/explainer_video/make.py .orchestra/tasks/V-691/scenes/compact55.py --out .orchestra/tasks/V-691/video/manim-latex --rate 1.25 --speaker 3
LAPTOP
```
