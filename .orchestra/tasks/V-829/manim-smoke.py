from manim import Circle, Create
from manim_voice import BLUE_, VoiceScene


class Smoke(VoiceScene):
    STEPS = [{"t": "Smoke render", "say": "A short Manim frame renders."}]

    def construct(self):
        with self.step(0):
            self.play(Create(Circle(color=BLUE_)), run_time=self.left() * 0.4)
