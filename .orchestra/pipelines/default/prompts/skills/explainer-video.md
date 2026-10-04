---
name: explainer-video
description: "Объясняющий ролик MP4 30–90 с в духе 3Blue1Brown: анимированная схема html-motion или график/анимация Manim и закадровая озвучка — русская (Vosk) или английская (Kokoro), локально, синхронные по фразам; проверка распознаванием и отправка в Telegram видео."
---

# Explainer Video

Ролик — это сцена, озвученная по шагам: `html-motion` (схемы) или Manim (графики и
математика в движении, раздел ниже). Для html-motion правила сцены, каркас плеера и
`STEPS` берутся из скилла `html-motion` (загрузи его); здесь только то, что добавляет звук
и кадр 16:9. Цифры и факты — из источника (отчёт, данные, код), как в любом артефакте.

**Озвучка задаёт время.** У каждого шага есть фраза `say`; инструмент сначала синтезирует
все фразы, потом ставит длительность шага = вступление + фраза + пауза (0.35 и 0.55 с,
делённые на темп `--rate`, по умолчанию 1.15; `hold: секунды`
вместо 0.55 у последнего шага — дать досмотреть). `d` в шагах не пиши: он заменяется.
Смена состояния в начале шага совпадает с началом фразы по построению. Внутри шага фраза
занимает почти всё окно, поэтому `w: {id: [a, b]}` ≈ доля фразы: объект, о котором
говорят в середине фразы, — `[.4, .6]`. Нужен второй точный акцент — раздели фразу на два
шага, а не подбирай окна.

- **Сцена:** каркас `html-motion` целиком, `<svg id="stage" viewBox="0 0 1200 520">`.
  Сразу после массива `STEPS` обязательна строка
  `STEPS.forEach(s => s.x ??= s.sub ?? s.say); window.voice?.(STEPS);` — без неё
  инструмент останавливается. Подпись шага в ролике — субтитры (лента Telegram играет без
  звука): `say`, а если в нём транслитерация или числа словами — `sub` с тем же текстом
  в экранном виде («Together», «7 680»); `t` — короткий заголовок шага.
- `along` с окном `w` задай ещё и атрибутом в разметке (`<circle along="путь">`): до начала
  окна каркас берёт исходное значение, и без атрибута падает на `getPointAtLength`.
- **Кадр и стиль** ставит инструмент: тёмный фон `#0b0e14`, без кнопок, шрифты Manrope и
  JetBrains Mono, 1920×1080. Текст SVG без `fill` светлый. Палитра: панель `#151a24`,
  линии `#2a3142`, приглушённый `#8b93a7`, синий `#58c4dd`, зелёный `#83c167`, красный
  `#fc6255`, золотой `#f0ac5f`. Шрифт в сцене не меньше 15 — ролик смотрят с телефона.
- **Как у 3Blue1Brown:** один шаг — одна мысль; объекты не исчезают со сменой кадра, а
  достраиваются и перекрашиваются; число появляется, когда его произносят; выделяй цветом и
  рамкой, а не новым абзацем; последний кадр — итог, который можно прочитать без звука.
  Повторяющееся (сетка, ряд столбцов) строй JS-циклом до `STEPS`, а шаги — генерируй.
- **Фраза `say`:** только кириллица и знаки препинания. Цифры и латиница роняют синтез
  (инструмент отказывает заранее): пиши словами («семь тысяч шестьсот восемьдесят»,
  «Дип Инфра», «опен роутер»), на экране оставляй цифры и оригинальные названия.
  1–2 предложения, 2–6 с в темпе 1.15, весь ролик 30–90 с. Без канцелярита: так, как сказал бы вслух.
- **Ролик на английском:** `make.py … --lang en` — озвучка Kokoro-82M вместо Vosk, проверка
  Deepgram с `language=en`. В `say` английский как есть: цифры, названия и `#2` Kokoro читает
  сам, отказ только на кириллицу. Голос `--voice af_heart` (по умолчанию, женский) или
  `am_michael` (мужской); на пробной фразе все пять опробованных голосов Deepgram распознал
  дословно (V-686). Темп `--rate 1.1` звучит естественнее 1.25.

## Второй движок: Manim

Manim — библиотека, на которой 3Blue1Brown рисует свои ролики. Сам Грант работает на своей
ветке ManimGL; у нас Community Edition (ManimCE 0.20.1, MIT): она стабильнее и документирована
(docs.manim.community). Сцена — Python-класс, кадры считает Cairo, видео пишет сам Manim.

**Что выбирать.** html-motion — схемы, диаграммы потоков, таблицы, текст и всё, что
уже есть как HTML-артефакт; правится быстро, кадр снимается в любой момент. Manim —
математика и данные в движении: оси и графики функций (`Axes`, `plot`), кривые, которые
рисуются (`Create`), числа, которые бегут (`ValueTracker` + `always_redraw`), превращение
одной фигуры в другую (`Transform`), полярные и радиальные диаграммы, формулы LaTeX
с подстановкой чисел. Если хочется
«как у 3b1b» — плавного морфинга и растущих графиков — это Manim.

**Сцена** — файл `.py` с одним классом-наследником `VoiceScene` из
`scripts/explainer_video/manim_voice.py` (лежит рядом с `make.py`). Договор тот же, что у
html-motion: `STEPS` с `t`/`say`/`sub`/`hold`, правила для `say` те же. Каждый шаг —
блок `with self.step(i):`, внутри обычные `self.play(...)`. Длительности анимаций задавай
долями оставшегося шага: `run_time=self.left() * 0.4`, тогда синхрон с фразой и смена
темпа получаются сами; перебор шага останавливает сборку с понятной ошибкой. Заголовок и
субтитры рисует `VoiceScene`; стиль — константы и `text()` оттуда же (`BLUE_`, `GOLD_`,
`PANEL`, шрифты Manrope/JetBrains Mono). Минимальный пример:

```python
from manim import *
from manim_voice import BLUE_, GOLD_, VoiceScene, text

class Growth(VoiceScene):
    STEPS = [
        {"t": "Рост", "say": "Квадрат растёт быстрее прямой.", "sub": "x² растёт быстрее x"},
        {"t": "Итог", "say": "После единицы парабола уходит вверх.", "hold": 1.5},
    ]

    def construct(self):
        ax = Axes(x_range=[0, 3, 1], y_range=[0, 9, 3], x_length=7, y_length=4.5)
        with self.step(0):
            self.play(Create(ax), run_time=self.left() * 0.3)
            self.play(Create(ax.plot(lambda x: x, color=BLUE_)),
                      Create(ax.plot(lambda x: x * x, color=GOLD_)), run_time=self.left() * 0.6)
        with self.step(1):
            self.play(Indicate(text("x > 1", 30).next_to(ax, UP)), run_time=self.left() * 0.5)
```

Сборка та же командой `make.py scene.py --out <папка>` (движок выбирается по
расширению). Черновой просмотр без озвучки — `manim -ql scene.py Класс` с
`PYTHONPATH=/home/kesha/orchestra/scripts/explainer_video`: 480p за ~1 мин.

**Формулы — LaTeX.** `MathTex` (математика) и `Tex` (текст с `$…$`) рендерятся TeX'ом и
выглядят как в учебнике; `manim_voice` сам добавляет в PATH наш TinyTeX и ставит шаблон с
кириллицей, так что `\text{запись}` в формуле и русский `Tex` работают. Формулу режь на
части — тогда их можно красить, подписывать скобкой и превращать при подстановке чисел:

```python
f = MathTex(r"\Delta q", r"\approx", r"0{,}6", r"\cdot", r"W", font_size=64)
f[4].set_color(GOLD_)                                   # часть по индексу
note = Brace(f[2:5], DOWN)                               # скобка под «0,6·W»
g = MathTex(r"\Delta q", r"\approx", r"0{,}6", r"\cdot", r"0{,}362")
self.play(TransformMatchingTex(f, g), run_time=self.left() * 0.4)  # W → число, остальное на месте
```

Десятичная запятая — `0{,}6` (без скобок TeX ставит пробел после запятой). Первая формула
в сборке компилируется ~1–2 с, дальше кеш `media/Tex`. Ошибка `latex error converting to dvi`
— смотри строку `!` в указанном `.log`: обычно недостающий пакет (`tlmgr install <пакет>`, см.
«Окружение») или неэкранированный `%`/`&` в `Tex`. Пример с формулой — `.orchestra/tasks/V-685/compact55.py`.
Кадр 14.2×8 единиц, центр (0, 0); снизу ~1 единицу занимают субтитры, сверху слева —
заголовок: держи объекты в y ∈ [−2.6, 3].

## Сборка

Вне cgroup платформы (Chromium + модель TTS ~2 ГБ памяти), ключ Deepgram — через stdin,
чтобы он не попал в командную строку:

```
printf '%s\n' "$DEEPGRAM_API_KEY" | ssh -o BatchMode=yes kesha@localhost \
  'read -r K; cd <рабочая папка> && DEEPGRAM_API_KEY=$K uv run --frozen --project /home/kesha/orchestra \
   python /home/kesha/orchestra/scripts/explainer_video/make.py scene.html --out <папка>'
```

Всегда через `bg_create(type="run")`: ролик 69 с собирался 9.5 мин (загрузка модели ~2 мин,
запись кадров в 6 параллельных Chromium, `--jobs`; в один поток было 25 мин). Фразы
кэшируются в `<папка>/.tts-cache`: правка сцены без правки `say` модель не грузит.
`--stills` — без видео: тайминг фраз и контакт-лист, удобно для правки сцены;
`--check-only` — только проверка готового MP4. `--speaker` 1 (по умолчанию, выбран владельцем 04.10 на выборе голосов V-690), 0–2 —
женские, 3 и 4 — мужские. `--rate` — темп: 1.15 по умолчанию (владелец 03.10: 1.5 слишком быстро; 04.10: 1.25 тоже многовато; речь синтезируется
быстрее, паузы между фразами сокращаются так же; распознаваемость при 1.25–1.5 та же, что при 1.0 — замер V-684), 1.0 — медленно.

Результат: `<имя>.mp4`, `<имя>.timing.json`, `<имя>-contact.png` (кадр конца каждого
шага), `<имя>.check.json` (Deepgram nova-2: что распознано в каждой фразе и сдвиг её
начала от плана).

## Проверка до отправки

- Открой контакт-лист и посмотри каждый кадр: ничего не обрезано и не наслоено, итог шага
  виден, текст читается. Сомнительный момент — `frames/<имя>/stepNN.png` в полном размере.
- `check.json`, сборка печатает его кратко. `onset_offset_max_abs_s` — где в итоговом MP4
  на самом деле начинается звук фразы относительно плана; должно быть ≤ 0.1 с. `offset_s` —
  начало первого распознанного слова: ±0.3 с норма, а одиночный большой минус после паузы —
  артефакт Deepgram (растягивает первое слово в тишину), если звук начался вовремя.
  `recall` — доля слов фразы, найденных в распознанном (по `say` или по `sub`: Deepgram
  пишет числа цифрами, названия латиницей). Ниже 0.85 или пропало название, ключевое
  слово — синтез невнятный: перефразируй (в V-681 «у Тугезера повтор» слышалось как
  «утугие зероповторы», «Оговорка:» в начале фразы пропадала). Пропуск числа, записанного
  иначе («два» → «2»), проблемой не считается. Интонацию распознавание не оценивает.
- Отправка: `send_file(path_to_mp4)` — MP4 уходит видео, которое играет прямо в ленте.

## Окружение (уже стоит на VPS; восстановить, если пропало)

`~/.local/share/orchestra-tts/`: `venv` (`uv venv --python 3.12 venv && uv pip install
--python venv/bin/python vosk-tts`) и модель `vosk-model-tts-ru-0.9-multi` (Apache 2.0,
782 МБ zip с alphacephei.com/vosk/models). Пути меняются переменными `ORCHESTRA_TTS_HOME`,
`ORCHESTRA_TTS_PYTHON`, `ORCHESTRA_TTS_MODEL`. Silero и Piper отвергнуты по лицензиям
(NC), облачный TTS — платный: подробности в `.orchestra/tasks/V-681/report.md`.

Английский голос — `~/.local/share/orchestra-tts/en/` (`ORCHESTRA_TTS_EN_HOME`): `venv` с
`kokoro-onnx` (MIT) и `soundfile`, рядом `kokoro-v1.0.onnx` (310 МБ) и `voices-v1.0.bin`
(28 МБ, веса Kokoro-82M — Apache 2.0) из релиза `model-files-v1.0` репозитория
thewh1teagle/kokoro-onnx. Ставится ~1 мин:

```
D=~/.local/share/orchestra-tts/en; mkdir -p $D && cd $D && uv venv --python 3.12 venv
uv pip install --python venv/bin/python kokoro-onnx soundfile
for f in kokoro-v1.0.onnx voices-v1.0.bin; do curl -sSfL --retry 5 -o $f \
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/$f; done
```

`~/.local/share/orchestra-manim/`: micromamba в `bin/`, окружение `env/` с Python 3.12 и
ManimCE 0.20.1 из conda-forge (вместе с Cairo, Pango и ffmpeg — apt и root не нужны).
Путь меняется переменной `ORCHESTRA_MANIM_HOME`. Если у тебя его нет — поставь так же:

```
mkdir -p ~/.local/share/orchestra-manim/bin && cd ~/.local/share/orchestra-manim
curl -sSfL https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C . bin/micromamba
MAMBA_ROOT_PREFIX=$PWD/mamba ./bin/micromamba create -y -p $PWD/env -c conda-forge python=3.12 manim=0.20.1
./env/bin/manim --version
```

Ставится ~2 мин, ~0.5 ГБ. На macOS/Windows вместо `linux-64` — свой билд micromamba
(mamba.readthedocs.io), остальное то же.

LaTeX для `MathTex`/`Tex` — TinyTeX (TeX Live 2026, 220 МБ) в
`~/.local/share/orchestra-manim/tex/`, без apt и root; `manim_voice` берёт его по
`ORCHESTRA_MANIM_HOME`, а если папки нет — `latex` из системного PATH (на VPS есть и
системный TeX Live 2023 из apt, он тоже работает). Если у тебя нет ни того, ни другого:

```
cd ~/.local/share/orchestra-manim
curl -sSfL --retry 5 --retry-all-errors -o /tmp/tinytex.tar.xz \
  https://github.com/rstudio/tinytex-releases/releases/download/v2026.10/TinyTeX-1-linux-x86_64-v2026.10.tar.xz
mkdir tex-unpack && tar -xJf /tmp/tinytex.tar.xz -C tex-unpack && mv tex-unpack/.TinyTeX tex && rmdir tex-unpack
tex/bin/x86_64-linux/tlmgr install standalone preview dvisvgm babel-english babel-russian cyrillic lh \
  doublestroke setspace rsfs relsize ragged2e microtype wasysym physics jknapltx wasy mathastext
```

~1 мин. Свежая версия — releases rstudio/tinytex-releases; GitHub отсюда иногда отвечает 503,
отсюда `--retry`. Нужен ещё пакет — `tex/bin/x86_64-linux/tlmgr install <имя>`. Скрипт
установки с логом — `.orchestra/tasks/V-685/install-tex.sh`.
