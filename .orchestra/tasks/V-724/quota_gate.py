"""Claude weekly quota gate: current rule and an eight-hour daytime lead."""
from manim import *
import numpy as np

from manim_voice import BG, BLUE_, FG, GOLD_, GREEN_, LINE, MUTED, PANEL, RED_, VoiceScene, text

RESET_HOUR = 14
WEEK_HOURS = 168
HARD_STOP = 99.0
CURRENT_START = 10.0
CURRENT_END = 1.0
DAY_AHEAD_HOURS = 8.0

X0, X1 = -5.25, 5.05
Y0, Y1 = -1.58, 2.30


def px(hour: float) -> float:
    return X0 + (X1 - X0) * hour / WEEK_HOURS


def py(percent: float) -> float:
    return Y0 + (Y1 - Y0) * percent / 100.0


def base_limit(hour: float) -> float:
    progress = max(0.0, min(1.0, hour / WEEK_HOURS))
    tolerance = CURRENT_START + (CURRENT_END - CURRENT_START) * progress
    return min(HARD_STOP, 100.0 * progress + tolerance)


def local_hour(hour: float) -> float:
    return (RESET_HOUR + hour) % 24.0


def nearest_night_limit(hour: float) -> float:
    local = local_hour(hour)
    delta = (8.0 - local) % 24.0
    if delta < 0.01:
        delta = 24.0
    return base_limit(min(WEEK_HOURS, hour + delta))


def daytime_lead_limit(hour: float) -> float:
    local = local_hour(hour)
    if 8.0 <= local < 24.0:
        target = hour + DAY_AHEAD_HOURS
    else:
        previous_day_23 = hour - (local + 1.0)
        target = previous_day_23 + DAY_AHEAD_HOURS
    return base_limit(min(WEEK_HOURS, target))


def polyline(function, start: float, end: float, *, color, width=4, dashed=False, samples=180):
    points = [np.array([px(t), py(function(t)), 0.0]) for t in np.linspace(start, end, samples)]
    path = VMobject().set_points_as_corners(points).set_stroke(color=color, width=width)
    return DashedVMobject(path, num_dashes=44) if dashed else path


class QuotaGateExplanation(VoiceScene):
    STEPS = [
        {"t": "Неделя квоты", "say": "Каждый вторник в четырнадцать по Красноярску сбрасывается недельная квота.",
         "sub": "Сброс недельной квоты — ВТ 14:00 по Красноярску. График: одна неделя."},
        {"t": "Что означает линия", "say": "Линия — сколько недельного лимита агенты уже могут израсходовать.",
         "sub": "Линия = сколько лимита уже разрешено потратить воркерам."},
        {"t": "Ровный рост", "say": "Сейчас предел растёт круглые сутки: плюс полпроцента в час.",
         "sub": "Сейчас: +0,54 п.п. в час, днём и ночью."},
        {"t": "Кого задерживает гейт", "say": "Выше линии агенты ждут; оркестраторы проходят её.",
         "sub": "Выше линии воркеры ждут; оркестраторы проходят."},
        {"t": "Общий стоп", "say": "На девяноста девяти процентах стоп для всех.",
         "sub": "99% — общий hard stop."},
        {"t": "Эта неделя: утро", "say": "В понедельник в десять: расход семьдесят восемь, линия — почти восемьдесят шесть.",
         "sub": "ПН 10:00 — расход 78%, линия 85,83%."},
        {"t": "Эта неделя: вечер", "say": "В одиннадцать — семьдесят девять. К вечеру — девяносто три, уже выше линии.",
         "sub": "ПН 11:00 — 79%. В 18:58 — 93%, выше линии 90,69%."},
        {"t": "Ночь почти плоская", "say": "Ночью расход почти не рос: за три недели — пять целых семь десятых процента.",
         "sub": "00:00–08:00 — 5,7% расхода и 4,5% ходов за 3 недели."},
        {"t": "Вариант в лоб", "say": "Полный ночной шаг даст девяносто семь целых семьдесят пять сотых процента.",
         "sub": "Конец ближайшей ночи: 97,75%."},
        {"t": "Почти hard stop", "say": "До общего стопа останется один целый двадцать пять сотых пункта.",
         "sub": "До hard stop 99% остаётся 1,25 п.п."},
        {"t": "Риск раннего исчерпания", "say": "В двух циклах расход достиг девяноста девяти за сорок один и двадцать три часа до сброса.",
         "sub": "До сброса оставалось 41,06 ч; 23,44 ч; в третьем — 0,55 ч."},
        {"t": "Компромисс: восемь часов", "say": "Компромисс — восемь часов запаса: плюс четыре целых тридцать три сотых пункта. Ночью — пауза.",
         "sub": "Компромисс: +4,33 п.п. днём; ночная пауза."},
        {"t": "Что получится", "say": "В десять — девяносто целых семнадцать сотых процента. В одиннадцать — девяносто целых семьдесят одна сотая процента.",
         "sub": "10:00 — 90,17% (+4,33). 11:00 — 90,71% (+4,33)."},
        {"t": "Решение", "say": "Какой вариант: почти девяносто восемь процентов или плюс четыре пункта?",
         "sub": "Какой вариант выбрать?", "hold": 1.8},
    ]

    def construct(self):
        width = X1 - X0
        height = Y1 - Y0

        frame = Rectangle(width=width, height=height, stroke_width=0, fill_color=BG, fill_opacity=0)
        frame.move_to([(X0 + X1) / 2, (Y0 + Y1) / 2, 0])
        night_bands = VGroup()
        for start in np.arange(10.0, WEEK_HOURS, 24.0):
            end = min(WEEK_HOURS, start + 8.0)
            band = Rectangle(width=(X1 - X0) * (end - start) / WEEK_HOURS,
                             height=height, stroke_width=0,
                             fill_color=FG, fill_opacity=0.045)
            band.move_to([(px(start) + px(end)) / 2, (Y0 + Y1) / 2, 0])
            night_bands.add(band)

        grid = VGroup()
        y_ticks = VGroup()
        for percent in (0, 20, 40, 60, 80, 100):
            grid.add(Line([X0, py(percent), 0], [X1, py(percent), 0],
                          color=LINE, stroke_width=1.5))
            y_ticks.add(text(f"{percent}%", 17, MUTED).move_to([X0 - 0.42, py(percent), 0]))
        x_ticks = VGroup()
        labels = ("Вт 14", "Ср", "Чт", "Пт", "Сб", "Вс", "Пн", "Вт 14")
        for day, label in enumerate(labels):
            hour = day * 24
            tick = Line([px(hour), Y0, 0], [px(hour), Y0 - 0.08, 0],
                        color=MUTED, stroke_width=1.5)
            tick_label = text(label, 17, MUTED).move_to([px(hour), Y0 - 0.31, 0])
            x_ticks.add(VGroup(tick, tick_label))
        y_axis = Line([X0, Y0, 0], [X0, Y1, 0], color=MUTED, stroke_width=2)
        x_axis = Line([X0, Y0, 0], [X1, Y0, 0], color=MUTED, stroke_width=2)
        y_label = text("% недельного лимита", 19, MUTED).rotate(PI / 2).move_to([X0 - 0.9, 0.3, 0])
        x_label = text("дни до ближайшего сброса", 18, MUTED).move_to([(X0 + X1) / 2, Y0 - 0.67, 0])
        axes = VGroup(y_axis, x_axis, grid, y_ticks, x_ticks, y_label, x_label)

        hard_stop = Line([X0, py(HARD_STOP), 0], [X1, py(HARD_STOP), 0],
                         color=RED_, stroke_width=3)
        hard_label = text("99% — СТОП ВСЕМ", 17, RED_, "BOLD", font="JetBrains Mono").move_to([X0 + 1.5, py(99) + 0.27, 0])
        current_line = polyline(base_limit, 0, WEEK_HOURS, color=BLUE_, width=5)
        current_label = text("СЕЙЧАС", 17, BLUE_, "BOLD", font="JetBrains Mono").move_to([px(88), py(base_limit(88)) + 0.22, 0])

        with self.step(0):
            self.add(frame)
            self.play(FadeIn(night_bands), Create(axes), run_time=self.left() * 0.55)
            self.play(Create(hard_stop), FadeIn(hard_label), run_time=self.left() * 0.25)
            self.play(Create(current_line), FadeIn(current_label), run_time=self.left() * 0.65)

        with self.step(1):
            note = text("разрешённый расход воркеров", 23, BLUE_).move_to([0.0, 1.05, 0])
            self.play(FadeIn(note, shift=0.1 * UP), run_time=self.left() * 0.25)
            marker = Dot([px(0), py(base_limit(0)), 0], radius=0.075, color=FG)
            self.add(marker)
            self.play(marker.animate.move_to([px(150), py(base_limit(150)), 0]),
                      run_time=self.left() * 0.6, rate_func=linear)
            self.play(FadeOut(marker), FadeOut(note), run_time=self.left() * 0.15)

        with self.step(2):
            per_hour = text("+0,54 п.п. / час", 21, BLUE_, "BOLD", font="JetBrains Mono").move_to([0.1, 1.05, 0])
            day_night = text("линия растёт даже в тихие часы", 22, MUTED).next_to(per_hour, DOWN, buff=0.18)
            self.play(FadeIn(per_hour), FadeIn(day_night), run_time=self.left() * 0.35)
            pulse = VGroup(*[
                Line([px(h), py(base_limit(h)), 0], [px(h + 8), py(base_limit(h + 8)), 0],
                     color=GOLD_, stroke_width=8)
                for h in (10, 34, 58, 82, 106, 130)
            ])
            self.play(FadeIn(pulse), run_time=self.left() * 0.3)
            self.play(FadeOut(pulse), FadeOut(per_hour), FadeOut(day_night), run_time=self.left() * 0.18)

        with self.step(3):
            workers = RoundedRectangle(width=4.1, height=0.72, corner_radius=0.12,
                                       stroke_color=GOLD_, fill_color=PANEL, fill_opacity=1)
            workers.move_to([-2.5, 1.15, 0])
            workers_text = text("воркеры: выше линии ждут", 21, GOLD_).move_to(workers)
            orch = RoundedRectangle(width=4.0, height=0.72, corner_radius=0.12,
                                    stroke_color=GREEN_, fill_color=PANEL, fill_opacity=1)
            orch.move_to([2.5, 1.15, 0])
            orch_text = text("оркестраторы: линия не гейтит", 18, GREEN_).move_to(orch)
            self.play(FadeIn(workers), FadeIn(workers_text), FadeIn(orch), FadeIn(orch_text),
                      run_time=self.left() * 0.38)
            self.play(FadeOut(workers), FadeOut(workers_text), FadeOut(orch), FadeOut(orch_text),
                      run_time=self.left() * 0.2)

        with self.step(4):
            stop_flash = SurroundingRectangle(hard_label, color=RED_, buff=0.12, stroke_width=4)
            self.play(Create(stop_flash), run_time=self.left() * 0.22)
            self.play(Indicate(hard_stop, color=RED_, scale_factor=1.02), run_time=self.left() * 0.48)
            self.play(FadeOut(stop_flash), run_time=self.left() * 0.15)

        sample_10 = Dot([px(140), py(78), 0], radius=0.085, color=BLUE_)
        sample_11 = Dot([px(141), py(79), 0], radius=0.085, color=BLUE_)
        sample_evening = Dot([px(148.967), py(93), 0], radius=0.09, color=FG)
        sample_cluster = VGroup(sample_10, sample_11)
        cluster_note = VGroup(
            text("ПН 10:00   78% / 85,83%", 16, BLUE_, "BOLD", font="JetBrains Mono"),
            text("ПН 11:00   79% / 86,38%", 16, BLUE_, "BOLD", font="JetBrains Mono"),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).move_to([-2.9, 1.0, 0])
        evening_note = text("18:58  93% > 90,69%", 17, RED_, "BOLD", font="JetBrains Mono").move_to([1.4, 2.02, 0])
        evening_leader = Line([2.65, 1.9, 0], [px(148.967), py(93), 0], color=RED_, stroke_width=2)
        sample_connector = DashedVMobject(
            VMobject().set_points_as_corners([
                np.array([px(140), py(78), 0]),
                np.array([px(141), py(79), 0]),
                np.array([px(148.967), py(93), 0]),
            ]).set_stroke(color=BLUE_, width=3), num_dashes=24)
        gap = Line([px(148.967), py(90.694), 0], [px(148.967), py(93), 0],
                   color=RED_, stroke_width=4)

        with self.step(5):
            self.play(FadeIn(sample_cluster), FadeIn(cluster_note), run_time=self.left() * 0.28)
            self.play(FadeIn(sample_connector), FadeIn(sample_evening), run_time=self.left() * 0.3)
            self.play(Create(gap), FadeIn(evening_note), Create(evening_leader), run_time=self.left() * 0.28)

        with self.step(6):
            self.play(Indicate(sample_evening, color=RED_, scale_factor=1.25),
                      Indicate(gap, color=RED_), run_time=self.left() * 0.42)

        with self.step(7):
            night_stat = VGroup(
                text("00:00–08:00", 18, MUTED),
                text("5,7% расхода", 25, GOLD_, "BOLD", font="JetBrains Mono"),
                text("доля за три недели", 16, MUTED),
            ).arrange(DOWN, aligned_edge=LEFT, buff=0.1)
            night_stat.move_to([-2.65, -0.62, 0])
            night_panel = RoundedRectangle(width=3.25, height=1.35, corner_radius=0.12,
                                            stroke_color=GOLD_, stroke_width=2,
                                            fill_color=PANEL, fill_opacity=0.96).move_to(night_stat)
            self.play(Indicate(sample_connector, color=BLUE_, scale_factor=1.02),
                      run_time=self.left() * 0.25)
            self.play(FadeIn(night_panel), FadeIn(night_stat, shift=0.15 * UP), run_time=self.left() * 0.33)

        full_night = polyline(nearest_night_limit, 138, 168, color=GOLD_, width=5, dashed=True, samples=60)
        full_night_label = text("К КОНЦУ НОЧИ: 97,75%", 17, GOLD_, "BOLD", font="JetBrains Mono").move_to([-1.6, 1.68, 0])
        full_gap = Line([px(140), py(base_limit(140)), 0],
                        [px(140), py(nearest_night_limit(140)), 0], color=GOLD_, stroke_width=4)
        with self.step(8):
            self.play(Create(full_night), FadeIn(full_night_label), run_time=self.left() * 0.55)
            self.play(Create(full_gap), run_time=self.left() * 0.25)
            self.play(Indicate(full_night, color=GOLD_), run_time=self.left() * 0.3)

        with self.step(9):
            self.play(FadeOut(night_panel), FadeOut(night_stat), run_time=self.left() * 0.15)
            near_stop = text("1,25 п.п. до 99%", 22, RED_, "BOLD", font="JetBrains Mono").move_to([0.65, 0.35, 0])
            self.play(FadeIn(near_stop), run_time=self.left() * 0.25)
            self.play(Indicate(hard_label, color=RED_), run_time=self.left() * 0.35)

        with self.step(10):
            self.play(FadeOut(near_stop), run_time=self.left() * 0.12)
            early = VGroup(
                text("99% ДО СБРОСА", 19, RED_, "BOLD", font="JetBrains Mono"),
                text("41,06 ч  ·  23,44 ч  ·  0,55 ч", 21, FG),
                text("три наблюдавшихся цикла", 16, MUTED),
            ).arrange(DOWN, aligned_edge=LEFT, buff=0.12).move_to([3.1, -0.62, 0])
            early_panel = RoundedRectangle(width=4.45, height=1.5, corner_radius=0.12,
                                           stroke_color=RED_, stroke_width=2,
                                           fill_color=PANEL, fill_opacity=0.96).move_to(early)
            self.play(FadeIn(early_panel), FadeIn(early, shift=0.1 * UP), run_time=self.left() * 0.35)

        compromise = polyline(daytime_lead_limit, 138, 168, color=GREEN_, width=5, samples=100)
        comp_mark_10 = Dot([px(140), py(90.166), 0], radius=0.075, color=GREEN_)
        comp_mark_11 = Dot([px(141), py(90.708), 0], radius=0.075, color=GREEN_)
        with self.step(11):
            self.play(FadeOut(early_panel), FadeOut(early), run_time=self.left() * 0.12)
            self.play(Create(compromise), run_time=self.left() * 0.58)
            self.play(FadeIn(comp_mark_10), FadeIn(comp_mark_11), run_time=self.left() * 0.2)
            self.play(Indicate(compromise, color=GREEN_), run_time=self.left() * 0.24)

        with self.step(12):
            values = text("10:00 90,17%   ·   11:00 90,71%", 19, GREEN_, "BOLD", font="JetBrains Mono")
            values.move_to([0.0, -2.57, 0])
            self.play(FadeIn(values, shift=0.1 * UP), run_time=self.left() * 0.28)

        with self.step(13):
            self.play(FadeOut(values), FadeOut(cluster_note),
                      FadeOut(evening_note), FadeOut(evening_leader), run_time=self.left() * 0.18)
            current_choice = RoundedRectangle(width=4.3, height=1.05, corner_radius=0.12,
                                              stroke_color=GOLD_, fill_color=PANEL, fill_opacity=1)
            current_choice.move_to([-2.35, 0.95, 0])
            current_text = VGroup(
                text("Почти 98%", 27, GOLD_, "BOLD"),
                text("полный ночной шаг", 17, MUTED),
            ).arrange(DOWN, buff=0.1).move_to(current_choice)
            bounded_choice = RoundedRectangle(width=4.3, height=1.05, corner_radius=0.12,
                                              stroke_color=GREEN_, fill_color=PANEL, fill_opacity=1)
            bounded_choice.move_to([2.35, 0.95, 0])
            bounded_text = VGroup(
                text("+4,33 п.п.", 27, GREEN_, "BOLD"),
                text("дневной шаг", 17, MUTED),
            ).arrange(DOWN, buff=0.1).move_to(bounded_choice)
            self.play(FadeIn(current_choice), FadeIn(current_text),
                      FadeIn(bounded_choice), FadeIn(bounded_text),
                      run_time=self.left() * 0.35)
            self.play(Indicate(bounded_choice, color=GREEN_), run_time=self.left() * 0.3)
