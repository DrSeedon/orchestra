from manim import *
from manim_voice import GOLD_, VoiceScene


class Long(VoiceScene):
    STEPS = [
        {"t": "Длинный субтитр", "say": "Проверяем перенос субтитра.",
         "sub": "Это очень длинный субтитр на русском языке, который должен переноситься по реальной ширине шрифта CMU Serif и не выходить за правый край кадра ни при каких условиях"},
    ]

    def construct(self):
        with self.step(0):
            self.play(Indicate(self.text("CMU Serif", 40, GOLD_)), run_time=self.left() * 0.5)
