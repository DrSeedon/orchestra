from manim import *
class P(Scene):
    def construct(self):
        a = MathTex(r"\text{price} = \sum_i w_i \cdot \frac{x_i}{10^6}")
        tpl = TexTemplate(preamble=r"""\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[english,russian]{babel}
\usepackage{amsmath}
\usepackage{amssymb}""")
        b = Tex(r"Запись кеша: $0{,}6$ п.п. за миллион", tex_template=tpl).next_to(a, DOWN)
        c = MathTex(r"\text{кеш}", tex_template=tpl).next_to(b, DOWN)
        self.add(a, b, c)
