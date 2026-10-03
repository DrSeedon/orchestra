"""«Оркестра не спит»: сутки как циферблат — когда пишет владелец и когда работают агенты.

Данные: data/orchestra.db, logs, окно 2026-09-03T08:02:54Z (первое сообщение с origin='user')
… 2026-10-03T00:00Z, час — по Красноярску (UTC+7). Владелец: type='user_message' AND
origin='user' (3 988). Агенты: type='tool' (90 726). Запросы — в report.md.
"""
from manim import *
from manim_voice import BLUE_, FG, GOLD_, LINE, MUTED, PANEL, VoiceScene, text

OWNER = [32, 1, 4, 1, 4, 12, 6, 18, 39, 129, 182, 262, 359, 330, 315, 377, 379, 354, 333, 198, 202, 190, 145, 116]
AGENTS = [1499, 798, 497, 358, 266, 202, 115, 1134, 1246, 2318, 3781, 5397, 7719, 8312, 6802, 6137, 7406,
          7368, 7020, 3900, 5357, 5201, 4389, 3504]
NIGHT = range(1, 7)  # 1:00–6:59
C = LEFT * 3.3 + UP * 0.15
R0, R1 = 0.6, 2.2  # пустой центр и внешний край столбцов
SLOT = TAU / 24


def angle(h: float) -> float:
    """Час h → угол: полночь сверху, по часовой стрелке."""
    return PI / 2 - SLOT * h


def fmt(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


class NightShift(VoiceScene):
    STEPS = [
        {"t": "Сутки Оркестры", "say": "Вот сутки Оркестры, как циферблат на двадцать четыре часа. Время красноярское."},
        {"t": "Владелец", "say": "Стрелка проходит месяц сообщений владельца. Почти четыре тысячи, больше всего с трёх до пяти дня.",
         "sub": "Стрелка проходит месяц сообщений владельца: 3 988, больше всего с 15 до 17."},
        {"t": "Ночь", "say": "А с часу ночи до семи утра за весь месяц всего двадцать восемь сообщений. Человек спит.",
         "sub": "А с 1:00 до 7:00 за весь месяц всего 28 сообщений. Человек спит."},
        {"t": "Агенты", "say": "Теперь агенты. За тот же месяц они вызвали инструменты девяносто тысяч раз.",
         "sub": "Теперь агенты. За тот же месяц они вызвали инструменты 90 726 раз."},
        {"t": "Днём вместе", "say": "Каждая кривая в своём масштабе. Днём они идут почти вместе: агенты работают, пока владелец пишет."},
        {"t": "Ночная смена", "say": "А ночью золотая не падает к нулю. Две тысячи вызовов, по восемьдесят на каждое ночное сообщение.",
         "sub": "А ночью золотая не падает к нулю: 2 236 вызовов, по 80 на каждое ночное сообщение."},
        {"t": "Итог", "say": "Днём на одно сообщение приходится двадцать два вызова, ночью восемьдесят. Оркестра работает, пока владелец спит.",
         "sub": "Днём на одно сообщение приходится 22 вызова, ночью 80. Оркестра работает, пока владелец спит.",
         "hold": 2.0},
    ]

    def bars(self, data, color, side, grown):
        """Столбец часа h — сектор в своей половине слота; grown(h) ∈ [0, 1] — насколько вырос."""
        peak = max(data)
        out = VGroup()
        for h, v in enumerate(data):
            f = grown(h)
            if f <= 0:
                continue
            width = SLOT * 0.42
            start = angle(h) - (SLOT * 0.04 if side == 0 else SLOT * 0.5)
            out.add(AnnularSector(inner_radius=R0, outer_radius=R0 + (R1 - R0) * v / peak * f + 0.02,
                                  angle=-width, start_angle=start, color=color, fill_opacity=0.9,
                                  stroke_width=0).move_arc_center_to(C))
        return out

    def construct(self):
        # ---- 1. циферблат
        with self.step(0):
            rings = VGroup(*(Circle(radius=r, color=LINE, stroke_width=2).move_to(C) for r in (R0, R1)))
            ticks, labels = VGroup(), VGroup()
            for h in range(24):
                a = angle(h)
                d = np.array([np.cos(a), np.sin(a), 0])
                major = h % 6 == 0
                ticks.add(Line(C + d * R1, C + d * (R1 + (0.18 if major else 0.09)),
                               color=FG if major else MUTED, stroke_width=3 if major else 2))
                if h % 3 == 0:
                    labels.add(text(f"{h}:00", 22 if major else 19, FG if major else MUTED, font="JetBrains Mono")
                               .move_to(C + d * (R1 + 0.5)))
            self.play(Create(rings), run_time=self.left() * 0.35)
            self.play(LaggedStart(*(GrowFromCenter(t) for t in ticks), lag_ratio=0.05),
                      FadeIn(labels, shift=0.1 * UP), run_time=self.left() * 0.6)

        # ---- 2. стрелка рисует владельца
        panel_x = RIGHT * 0.9
        own_label = text("Владелец, сообщений", 26, BLUE_).move_to(panel_x + UP * 2.7, aligned_edge=LEFT)
        hours = ValueTracker(0)
        hand = always_redraw(lambda: Line(C, C + R1 * np.array([np.cos(angle(hours.get_value())),
                                                                 np.sin(angle(hours.get_value())), 0]),
                                          color=FG, stroke_width=3))
        own_bars = always_redraw(lambda: self.bars(OWNER, BLUE_, 0, lambda h: min(max(hours.get_value() - h, 0), 1)))
        own_count = always_redraw(lambda: text(fmt(self.cum(OWNER, hours.get_value())), 56, BLUE_, "BOLD",
                                               font="JetBrains Mono").next_to(own_label, DOWN, aligned_edge=LEFT))
        with self.step(1):
            self.add(own_bars, hand)
            self.play(FadeIn(own_label), FadeIn(own_count), run_time=self.left() * 0.1)
            self.play(hours.animate.set_value(24), run_time=self.left() * 0.85, rate_func=linear)
        own_bars.clear_updaters()
        own_count.clear_updaters()
        self.remove(hand)

        # ---- 3. ночь
        night = AnnularSector(inner_radius=R0 - 0.05, outer_radius=R1 + 0.05, angle=-SLOT * 6,
                              start_angle=angle(1), color=PANEL, fill_opacity=1, stroke_width=0).move_arc_center_to(C)
        night_edge = VGroup(*(Line(C + R0 * d, C + R1 * d, color=MUTED, stroke_width=2) for d in
                              (np.array([np.cos(angle(x)), np.sin(angle(x)), 0]) for x in (1, 7))))
        moon = text("ночь", 22, MUTED).move_to(C + RIGHT * 1.1 + UP * 1.75)  # над малыми ночными столбцами
        night_own = text("28", 34, BLUE_, "BOLD", font="JetBrains Mono").next_to(moon, DOWN, buff=0.15)
        with self.step(2):
            self.bring_to_back(night)
            self.play(FadeIn(night), Create(night_edge), run_time=self.left() * 0.3)
            self.play(Write(moon), run_time=self.left() * 0.2)
            self.play(FadeIn(night_own, scale=1.4), run_time=self.left() * 0.3)

        # ---- 4. агенты
        ag_label = text("Агенты, вызовов", 26, GOLD_).move_to(panel_x + UP * 0.7, aligned_edge=LEFT)
        hours.set_value(0)
        ag_bars = always_redraw(lambda: self.bars(AGENTS, GOLD_, 1, lambda h: min(max(hours.get_value() - h, 0), 1)))
        ag_count = always_redraw(lambda: text(fmt(self.cum(AGENTS, hours.get_value())), 56, GOLD_, "BOLD",
                                              font="JetBrains Mono").next_to(ag_label, DOWN, aligned_edge=LEFT))
        with self.step(3):
            self.add(ag_bars, hand)
            self.play(FadeIn(ag_label), FadeIn(ag_count), run_time=self.left() * 0.1)
            self.play(hours.animate.set_value(24), run_time=self.left() * 0.8, rate_func=linear)
        ag_bars.clear_updaters()
        ag_count.clear_updaters()
        self.remove(hand)

        # ---- 5. днём вместе: обводим дневной сектор 9–19
        day = Arc(radius=R1 + 0.12, start_angle=angle(9), angle=-SLOT * 10, color=FG, stroke_width=5).shift(C)
        day_tag = text("9:00–19:00", 20, FG, font="JetBrains Mono").move_to(
            C + (R1 + 0.95) * np.array([np.cos(angle(16)), np.sin(angle(16)), 0]))
        scale_note = text("каждая кривая — в долях своего пика", 22, MUTED).move_to(panel_x + DOWN * 0.9, aligned_edge=LEFT)
        with self.step(4):
            self.play(FadeIn(scale_note), run_time=self.left() * 0.25)
            self.play(Create(day), FadeIn(day_tag), run_time=self.left() * 0.4)
            self.play(Indicate(VGroup(*own_bars[9:19]), color=BLUE_, scale_factor=1.04),
                      Indicate(VGroup(*ag_bars[9:19]), color=GOLD_, scale_factor=1.04), run_time=self.left() * 0.8)

        # ---- 6. ночная смена
        night_ag = text("2 236", 30, GOLD_, "BOLD", font="JetBrains Mono").next_to(night_own, DOWN, buff=0.12)
        with self.step(5):
            self.play(FadeOut(day), FadeOut(day_tag), run_time=self.left() * 0.15)
            self.play(Indicate(VGroup(*ag_bars[1:7]), color=GOLD_, scale_factor=1.15), run_time=self.left() * 0.35)
            self.play(FadeIn(night_ag, shift=0.2 * UP), run_time=self.left() * 0.4)

        # ---- 7. итог: две пропорции
        def ratio(label, value, y, color):
            row = VGroup(text(label, 28, FG), text("1 :", 40, BLUE_, "BOLD", font="JetBrains Mono"),
                         text(value, 40, color, "BOLD", font="JetBrains Mono"))
            row[1].next_to(row[0], RIGHT, buff=0.4)
            row[2].next_to(row[1], RIGHT, buff=0.12)
            return row.move_to(panel_x + y, aligned_edge=LEFT)
        day_row = ratio("днём ", "22", DOWN * 1.2, GOLD_)
        night_row = ratio("ночью", "80", DOWN * 1.9, GOLD_)
        with self.step(6):
            self.play(FadeOut(scale_note), run_time=self.left() * 0.1)
            self.play(FadeIn(day_row, shift=0.2 * LEFT), run_time=self.left() * 0.25)
            self.play(FadeIn(night_row, shift=0.2 * LEFT), run_time=self.left() * 0.25)
            self.play(Circumscribe(night_row[2], color=GOLD_), run_time=self.left() * 0.5)

    @staticmethod
    def cum(data, hours):
        whole = int(hours)
        return sum(data[:whole]) + (data[whole] * (hours - whole) if whole < 24 else 0)
