"""«Почему агент сжимается на 55-й минуте»: кеш Claude, формула подписки и компакт по простою.

Факты: app/session.py — PRECOMPACT_DELAY_SECONDS = 55 мин, CLAUDE_CACHE_WINDOW_SECONDS = 60 мин;
.orchestra/kb/models-and-quotas.md (V-605/V-660) — запись кеша 0,604 п.п. недели за 1 млн,
чтение ≈ 0. Числа — compact_stats.py по data/orchestra.db: 70 компактов Claude 20.09–03.10,
медиана 362 тыс. → 84 тыс. токенов, без сжатия 14,8 п.п., со сжатием 6,6 + ~0,5 (пересказ) ≈ 7,1.
"""
from manim import *
from manim_voice import BLUE_, FG, GOLD_, GREEN_, LINE, MUTED, PANEL, RED_, VoiceScene, text

PRE, POST = 362, 84          # тыс. токенов, медианы
X0, TL = -6.0, 11.0          # начало и длина шкалы времени
T_MAX = 150                  # минут на шкале
BAR_Y, LINE_Y, F_Y = 2.15, 0.35, -1.55
BAR_UNIT = 7.2 / PRE         # единиц кадра на тыс. токенов


def tx(minutes: float) -> float:
    return X0 + TL * minutes / T_MAX


def mono(s, size=30, color=FG, weight="BOLD"):
    return text(s, size, color, weight, font="JetBrains Mono")


class Compact55(VoiceScene):
    STEPS = [
        {"t": "Память агента",
         "say": "У агента в памяти длинный разговор, обычно триста шестьдесят две тысячи токенов. Каждый ход модель перечитывает его целиком.",
         "sub": "У агента в памяти длинный разговор, обычно 362 тысячи токенов. Каждый ход модель перечитывает его целиком."},
        {"t": "Кеш живёт час",
         "say": "Чтобы это было дёшево, разговор лежит в кеше. Кеш живёт час после последнего хода."},
        {"t": "Формула подписки",
         "say": "По нашим замерам чтение из кеша почти бесплатно. Платим за запись: шесть десятых процента недельного лимита за миллион токенов.",
         "sub": "По нашим замерам чтение из кеша почти бесплатно. Платим за запись: 0,6 % недельного лимита за 1 млн токенов."},
        {"t": "Кеш остыл",
         "say": "Владелец вернулся через два часа. Кеш уже остыл, и весь разговор записывается заново.",
         "sub": "Владелец вернулся через 2 часа. Кеш уже остыл, и весь разговор записывается заново."},
        {"t": "Цена возврата",
         "say": "Одно такое возвращение съедает примерно две десятых процента недельного лимита.",
         "sub": "Одно такое возвращение съедает ≈ 0,22 % недельного лимита."},
        {"t": "Пятьдесят пятая минута",
         "say": "Поэтому на пятьдесят пятой минуте тишины, пока кеш ещё горячий, Оркестра сжимает разговор в пересказ. Он в четыре раза короче.",
         "sub": "Поэтому на 55-й минуте тишины, пока кеш ещё горячий, Оркестра сжимает разговор в пересказ: 84 тысячи токенов."},
        {"t": "Две короткие записи",
         "say": "Пересказ пишется сейчас и ещё раз после возвращения. Но две короткие записи дешевле одной длинной.",
         "sub": "Пересказ пишется сейчас и ещё раз после возвращения. Но две короткие записи дешевле одной длинной."},
        {"t": "Две недели",
         "say": "За две недели так сжались семьдесят разговоров. Без сжатия их возвраты стоили бы пятнадцать процентов недельного лимита, а вышло около семи.",
         "sub": "За две недели так сжались 70 разговоров. Без сжатия их возвраты стоили бы 14,8 % недельного лимита, а вышло ≈ 7,1 %."},
        {"t": "Итог",
         "say": "Сжатие за пять минут до остывания кеша вдвое бережёт лимит. Цена за это: агент помнит пересказ, а не каждое слово.",
         "sub": "Сжатие за 5 минут до остывания кеша вдвое бережёт лимит. Цена: агент помнит пересказ, а не каждое слово.",
         "hold": 2.0},
    ]

    def construct(self):
        # ---- 1. разговор — полоса из блоков
        n_blocks = 18
        w = PRE * BAR_UNIT / n_blocks
        blocks = VGroup(*(Rectangle(width=w * 0.9, height=0.55, stroke_width=0, fill_color=BLUE_, fill_opacity=0.85)
                          .move_to([X0 + w * (i + 0.5), BAR_Y, 0]) for i in range(n_blocks)))
        bar_label = text("разговор агента", 26, MUTED).move_to([X0, BAR_Y + 0.6, 0], aligned_edge=LEFT)
        size = mono("362 тыс. токенов", 30, BLUE_).next_to(blocks, RIGHT, buff=0.3)
        with self.step(0):
            self.play(FadeIn(bar_label), run_time=self.left() * 0.1)
            self.play(LaggedStart(*(GrowFromEdge(b, LEFT) for b in blocks), lag_ratio=0.08), run_time=self.left() * 0.4)
            self.play(FadeIn(size, shift=0.2 * LEFT), run_time=self.left() * 0.15)
            reader = Rectangle(width=0.18, height=0.75, stroke_width=0, fill_color=FG, fill_opacity=0.6).move_to([X0, BAR_Y, 0])
            self.add(reader)
            self.play(reader.animate.move_to([X0 + PRE * BAR_UNIT, BAR_Y, 0]), run_time=self.left() * 0.8, rate_func=linear)
            self.remove(reader)

        # ---- 2. шкала времени и горячая зона кеша
        axis = Line([tx(0), LINE_Y, 0], [tx(T_MAX), LINE_Y, 0], color=MUTED, stroke_width=3)
        ticks = VGroup()
        for m in range(0, T_MAX + 1, 30):
            ticks.add(Line([tx(m), LINE_Y - 0.08, 0], [tx(m), LINE_Y + 0.08, 0], color=MUTED, stroke_width=2))
            ticks.add(mono(f"{m}" + (" мин" if m == T_MAX else ""), 20, MUTED, "NORMAL").move_to([tx(m), LINE_Y - 0.35, 0]))
        hot = Rectangle(width=tx(60) - tx(0), height=0.5, stroke_width=0, fill_color=GOLD_, fill_opacity=0.35)
        hot.move_to([(tx(0) + tx(60)) / 2, LINE_Y + 0.3, 0])
        hot_lbl = text("кеш горячий", 24, GOLD_).move_to(hot)
        cold_lbl = text("кеш остыл", 24, MUTED).move_to([(tx(60) + tx(T_MAX)) / 2, LINE_Y + 0.3, 0])
        with self.step(1):
            self.play(Create(axis), FadeIn(ticks), run_time=self.left() * 0.3)
            self.play(GrowFromEdge(hot, LEFT), run_time=self.left() * 0.35)
            self.play(FadeIn(hot_lbl), FadeIn(cold_lbl), run_time=self.left() * 0.3)

        # ---- 3. формула
        formula = MathTex(r"\Delta q", r"\approx", r"0{,}6", r"\cdot", r"W", r"+", r"0", r"\cdot", r"R",
                          font_size=64).move_to([0, F_Y, 0])
        formula[4].set_color(GOLD_)
        formula[8].set_color(BLUE_)
        w_brace = Brace(formula[2:5], DOWN, buff=0.12, color=GOLD_)
        w_note = text("запись, млн токенов", 22, GOLD_).next_to(w_brace, DOWN, buff=0.08, aligned_edge=RIGHT)
        r_brace = Brace(formula[6:9], DOWN, buff=0.12, color=BLUE_)
        r_note = text("чтение ≈ даром", 22, BLUE_).next_to(r_brace, DOWN, buff=0.08, aligned_edge=LEFT)
        q_note = text("% недельного лимита", 22, MUTED).next_to(formula[0], LEFT, buff=0.35)
        with self.step(2):
            self.play(Write(formula), run_time=self.left() * 0.3)
            self.play(FadeIn(q_note), GrowFromCenter(r_brace), FadeIn(r_note), run_time=self.left() * 0.2)
            self.play(GrowFromCenter(w_brace), FadeIn(w_note), run_time=self.left() * 0.2)
            self.play(Indicate(formula[2:5], color=GOLD_), run_time=self.left() * 0.8)

        # ---- 4. возврат через два часа
        clock = ValueTracker(0)
        dot = always_redraw(lambda: Dot([tx(clock.get_value()), LINE_Y, 0], radius=0.11, color=FG))
        back = text("вернулся", 22, FG).move_to([tx(121), LINE_Y + 0.95, 0])
        with self.step(3):
            self.add(dot)
            self.play(clock.animate.set_value(121), run_time=self.left() * 0.45, rate_func=linear)
            self.play(FadeIn(back, shift=0.15 * DOWN), run_time=self.left() * 0.1)
            self.play(blocks.animate.set_fill(RED_), run_time=self.left() * 0.3)
            self.play(LaggedStart(*(Indicate(b, color=RED_, scale_factor=1.15) for b in blocks), lag_ratio=0.05),
                      run_time=self.left() * 0.9)
        dot.clear_updaters()

        # ---- 5. цена: подставили числа
        cost_old = MathTex(r"\Delta q", r"\approx", r"0{,}6", r"\cdot", r"0{,}362", r"\approx", r"0{,}22\,\%",
                           font_size=64).move_to([0, F_Y, 0])
        cost_old[4].set_color(RED_)
        cost_old[6].set_color(RED_)
        with self.step(4):
            self.play(FadeOut(VGroup(w_brace, w_note, r_brace, r_note, q_note)), run_time=self.left() * 0.15)
            self.play(TransformMatchingTex(formula, cost_old), run_time=self.left() * 0.45)
            self.play(Circumscribe(cost_old[6], color=RED_), run_time=self.left() * 0.7)

        # ---- 6. 55-я минута: сжатие
        mark = Line([tx(55), LINE_Y - 0.15, 0], [tx(55), LINE_Y + 0.75, 0], color=GREEN_, stroke_width=5)
        mark_lbl = mono("55", 24, GREEN_).next_to(mark, UP, buff=0.08)
        short = Rectangle(width=POST * BAR_UNIT, height=0.55, stroke_width=0, fill_color=GREEN_, fill_opacity=0.9)
        short.move_to([X0 + POST * BAR_UNIT / 2, BAR_Y, 0])
        size_new = mono("84 тыс.", 30, GREEN_).next_to(short, RIGHT, buff=0.3)
        bar_label_new = text("пересказ", 26, GREEN_).move_to(bar_label, aligned_edge=LEFT)
        with self.step(5):
            self.play(FadeOut(back), dot.animate.move_to([tx(55), LINE_Y, 0]), run_time=self.left() * 0.15)
            self.play(Create(mark), FadeIn(mark_lbl), run_time=self.left() * 0.15)
            self.play(Indicate(hot, color=GOLD_, scale_factor=1.05), run_time=self.left() * 0.2)
            self.play(ReplacementTransform(blocks, short), ReplacementTransform(size, size_new),
                      ReplacementTransform(bar_label, bar_label_new), run_time=self.left() * 0.5)

        # ---- 7. две короткие записи против одной длинной
        cost_new = MathTex(r"2", r"\cdot", r"0{,}6", r"\cdot", r"0{,}084", r"\approx", r"0{,}10\,\%", font_size=56)
        cost_new[4].set_color(GREEN_)
        cost_new[6].set_color(GREEN_)
        vs = MathTex(r"<", font_size=64)
        cost_right = MathTex(r"0{,}6", r"\cdot", r"0{,}362", r"\approx", r"0{,}22\,\%", font_size=56)
        cost_right[2].set_color(RED_)
        cost_right[4].set_color(RED_)
        VGroup(cost_new, vs, cost_right).arrange(RIGHT, buff=0.45).move_to([0, F_Y, 0])
        with self.step(6):
            self.play(TransformMatchingTex(cost_old, cost_right), run_time=self.left() * 0.25)
            self.play(Write(cost_new), run_time=self.left() * 0.35)
            self.play(FadeIn(vs, scale=1.5), run_time=self.left() * 0.15)
            self.play(Circumscribe(cost_new[6], color=GREEN_), run_time=self.left() * 0.8)

        # ---- 8. две недели: столбцы
        old_pp, new_pp = 14.8, 7.1
        unit = 8.0 / old_pp
        def row(label, value, y, color):
            lbl = text(label, 26, FG).move_to([X0, y, 0], aligned_edge=LEFT)
            bar = Rectangle(width=value * unit, height=0.6, stroke_width=0, fill_color=color, fill_opacity=0.9)
            bar.move_to([X0 + 3.0 + value * unit / 2, y, 0])
            num = mono(f"{value:.1f} %".replace(".", ","), 30, color).next_to(bar, RIGHT, buff=0.25)
            return lbl, bar, num
        r1 = row("без сжатия", old_pp, 1.0, RED_)
        r2 = row("со сжатием", new_pp, -0.1, GREEN_)
        head = text("70 сжатий, 20.09–03.10, % недельного лимита", 24, MUTED).move_to([X0, 1.9, 0], aligned_edge=LEFT)
        with self.step(7):
            self.play(FadeOut(VGroup(axis, ticks, hot, hot_lbl, cold_lbl, dot, mark, mark_lbl, short, size_new,
                                     bar_label_new, cost_new, cost_right, vs)), run_time=self.left() * 0.15)
            self.play(FadeIn(head), FadeIn(r1[0]), GrowFromEdge(r1[1], LEFT), run_time=self.left() * 0.3)
            self.play(FadeIn(r1[2]), run_time=self.left() * 0.1)
            self.play(FadeIn(r2[0]), GrowFromEdge(r2[1], LEFT), run_time=self.left() * 0.4)
            self.play(FadeIn(r2[2]), run_time=self.left() * 0.6)

        # ---- 9. итог
        rule = MathTex(r"t_{\text{сжатия}}", r"=", r"60", r"-", r"5", r"=", r"55\ \text{мин}", font_size=60).move_to([0, -1.55, 0])
        rule[2].set_color(GOLD_)
        rule[6].set_color(GREEN_)
        ttl = text("жизнь кеша", 20, GOLD_).next_to(rule[2], DOWN, buff=0.2, aligned_edge=RIGHT)
        margin = text("запас", 20, MUTED).next_to(rule[4], DOWN, buff=0.2, aligned_edge=LEFT)
        with self.step(8):
            self.play(Write(rule), run_time=self.left() * 0.3)
            self.play(FadeIn(ttl), FadeIn(margin), run_time=self.left() * 0.15)
            self.play(Circumscribe(rule[6], color=GREEN_), run_time=self.left() * 0.35)
