"""Сцена Manim, озвученная по шагам: тот же договор, что у html-motion в make.py.

    from manim import *
    from manim_voice import VoiceScene, BLUE_, GOLD_

    class Demo(VoiceScene):
        STEPS = [
            {"t": "Вопрос", "say": "Фраза словами.", "sub": "Подпись с цифрами: 40"},
            {"t": "Итог", "say": "Последняя фраза.", "hold": 1.5},
        ]

        def construct(self):
            with self.step(0):
                self.play(Create(circle), run_time=self.left() * 0.6)
            with self.step(1):
                ...

Длительность шага задаёт озвучка: make.py синтезирует фразы и передаёт длительности через
EXPLAINER_VOICE. Внутри `with self.step(i)` анимации занимают сколько угодно, но не больше
шага: остаток добирается паузой, перебор останавливает сборку. `self.left()` — сколько
секунд осталось в шаге; длительности анимаций задавай долями шага, а не секундами, тогда
темп ролика меняется одним ключом. Заголовок `t` и субтитр `sub ?? say` рисует сцена сама.
Без EXPLAINER_VOICE (просмотр `manim -ql`) длительность шага оценивается по длине фразы.
MathTex/Tex работают с кириллицей: шаблон LaTeX и путь к TinyTeX ставит этот модуль.
"""
from __future__ import annotations

import json
import os
import textwrap
from contextlib import contextmanager
from pathlib import Path

import manimpango
from manim import DOWN, LEFT, UL, UP, Scene, TexTemplate, Text, VGroup, config

FONTS = Path(__file__).resolve().parent / "fonts"
# Свой TinyTeX рядом с Manim (SKILL explainer-video); нет его — latex берётся из системного PATH.
TEX_BIN = Path(os.environ.get("ORCHESTRA_MANIM_HOME", Path.home() / ".local/share/orchestra-manim")) / "tex/bin/x86_64-linux"
if TEX_BIN.is_dir():
    os.environ["PATH"] = f"{TEX_BIN}:{os.environ['PATH']}"
# Шаблон Manim по умолчанию — babel english без кириллицы: «\text{кеш}» в MathTex падает.
config.tex_template = TexTemplate(preamble="\n".join((
    r"\usepackage[T2A]{fontenc}", r"\usepackage[utf8]{inputenc}", r"\usepackage[english,russian]{babel}",
    r"\usepackage{amsmath}", r"\usepackage{amssymb}")))
BG, PANEL, LINE, MUTED = "#0b0e14", "#151a24", "#2a3142", "#8b93a7"
BLUE_, GREEN_, RED_, GOLD_, FG = "#58c4dd", "#83c167", "#fc6255", "#f0ac5f", "#e6e6e6"
FONT, MONO = "Manrope", "JetBrains Mono"

for ttf in ("Manrope.ttf", "JetBrainsMono.ttf"):
    manimpango.register_font(str(FONTS / ttf))
config.background_color = BG


def text(s: str, size: float = 30, color: str = FG, weight: str = "NORMAL", font: str = FONT, **kw) -> Text:
    """Text с нашим шрифтом. Размер 30 ≈ 24 px в кадре 1080p; мельче 24 с телефона не читается."""
    return Text(s, font=font, font_size=size, color=color, weight=weight, **kw)


class VoiceScene(Scene):
    STEPS: list[dict] = []
    CAPTION_CHARS = 66  # строка субтитра при размере 26 на ширину кадра

    def setup(self):
        voice = json.loads(os.environ.get("EXPLAINER_VOICE", "null"))
        if voice:
            self.durations, self.pre, self.post = voice["d"], voice["pre"], voice["post"]
        else:
            self.durations = [0.35 + len(s["say"]) / 15 + s.get("hold", 0.55) for s in self.STEPS]
            self.pre, self.post = 0.3, 1.0
        if len(self.durations) != len(self.STEPS):
            raise ValueError("число длительностей озвучки не совпадает с STEPS")
        self.starts = [self.pre + sum(self.durations[:i]) for i in range(len(self.durations))]
        self.cur = -1
        self.chrome = VGroup()

    def left(self) -> float:
        """Секунд до конца текущего шага (не меньше одного кадра)."""
        end = self.starts[self.cur] + self.durations[self.cur]
        return max(end - self.time, 1 / config.frame_rate)

    def _chrome(self, step: dict) -> VGroup:
        title = text(step["t"], 34, "#ffffff", "BOLD").to_corner(UL, buff=0.45)
        lines = textwrap.wrap(step.get("sub") or step["say"], self.CAPTION_CHARS)
        caption = VGroup(*(text(line, 26, "#d5d8df") for line in lines))
        caption.arrange(DOWN, aligned_edge=LEFT, buff=0.14).to_edge(DOWN, buff=0.38).to_edge(LEFT, buff=0.6)
        return VGroup(title, caption)

    @contextmanager
    def step(self, i: int):
        if i != self.cur + 1:
            raise ValueError(f"шаги идут по порядку: ожидался {self.cur + 1}, получен {i}")
        # Ожидание короче кадра Manim всё равно растягивает до кадра (и предупреждает); набегающий
        # сдвиг меньше кадра снимает следующий шаг, потому что starts — абсолютные.
        if self.starts[i] - self.time >= 1 / config.frame_rate:
            self.wait(self.starts[i] - self.time)
        self.cur = i
        self.remove(self.chrome)
        self.chrome = self._chrome(self.STEPS[i])
        self.add(self.chrome)
        yield
        end = self.starts[i] + self.durations[i]
        over = self.time - end
        if over > 1.5 / config.frame_rate:
            raise RuntimeError(f"шаг {i + 1} «{self.STEPS[i]['t']}»: анимации длиннее фразы на {over:.2f} с — "
                               "задавай run_time через self.left()")
        if end - self.time >= 1 / config.frame_rate:
            self.wait(end - self.time)

    def tear_down(self):
        self.wait(self.post)
