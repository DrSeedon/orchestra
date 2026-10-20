# Moves in Manim CE (our `VoiceScene`)

Short recipes for the moves in `explainer-craft`. `VoiceScene` and `make.py` themselves are
described in `video-artifact`. The code is ours, written for Manim CE 0.20.1; check with `--preview-step`.

## A symbol from an object into the formula

```python
bar = Rectangle(width=0.6, height=2.0, fill_color=PINK_, fill_opacity=0.8, stroke_width=0)
q = MathTex("q", color=PINK_).next_to(bar, UP, buff=0.1)
loss = MathTex(r"L", "=", r"-\ln", "q", font_size=60).to_edge(RIGHT)
loss.set_color_by_tex("q", PINK_)          # the symbol has the same colour everywhere
with self.step(3):
    self.play(Create(SurroundingRectangle(bar, color=PINK_)), FadeIn(q), run_time=self.left() * 0.3)
    self.play(Write(loss[:3]), run_time=self.left() * 0.25)
    self.play(TransformFromCopy(q, loss[3]), run_time=self.left() * 0.35)   # q "flies" over
```

Split the formula into parts with `MathTex(r"L", "=", ...)` or `substrings_to_isolate=["q"]`, then
`get_part_by_tex("q")` returns the symbol you need.

## Rebuilding a formula when numbers are substituted

`TransformMatchingTex(old, new)`: matching parts stay in place, only the new ones change.
For your own `VGroup`s use `TransformMatchingShapes`.

## Dim, do not remove

```python
self.play(old_group.animate.set_opacity(0.2), new.animate.set_opacity(1), run_time=self.left() * 0.3)
```
A "ghost" of the next object: add it in advance with `set_opacity(0.1)`.

## A silent beat

A step with `"say": ""` and `"hold": 1.5` is accepted and lasts exactly the hold. On a step with
a phrase, `"hold": 1.5` replaces the default end pause with 1.5 s; an animation with
`run_time=self.left() * k` at the end of the step fills that silence.

## Camera

`VoiceScene` extends `MovingCameraScene`: `self.camera.frame.animate.scale(0.6).move_to(obj)` zooms
in on an object while the title and subtitles stay in place.

## Font

`text()` and `self.text()` from `manim_voice` use the font of the chosen `--theme` (see
`video-artifact`). For a label in the same face as the formulas use
`Tex(r"\text{label}")` (Computer Modern with Cyrillic is already set up in the template) instead of
`text()`. Numbers next to a formula are `MathTex` as well, not a monospace helper.

## What CE does not have and you need not look for

The interactive debugging of ManimGL (`-se`, `checkpoint_paste`) is absent; `--preview-step N`
replaces it. The π characters are the 3B1B author's; we do not copy them; make your own "viewer's
voice" a question label or a simple character of your own.
