---
name: explainer-craft
description: "Script, storyboard and pre-build check for an explainer video so the viewer understands, not just sees. Complements video-artifact (which builds the video: voice, frame, sound). Use BEFORE writing STEPS, for any request to make an explainer or science-popular video, a 3Blue1Brown-style video, a video from a lecture, or to redo a video the viewer did not understand. Russian triggers: сделай ролик, объясняющее видео, сценарий ролика, раскадровка, ролик непонятный, зритель не понял."
---

# Explainer video: script → storyboard → check

The build technique (voice, `STEPS`, `VoiceScene`, `make.py`, sound checks) is in `video-artifact`;
read it for anything about the tool. This skill answers a different question: **what** to show and
say, in what order and at what pace, so that the viewer understands. The rules come from
measurements of 127 3Blue1Brown videos and of our own video on lecture 1 "Neural networks": its
part 2 was understandable, part 3 was not. The numbers below are guides from those measurements,
not laws.

## 1. Selection: one idea, one video

Start with selection, not with text.

- Write the central question of the video in one sentence. A question, not a topic: "why can't a
  network just guess the probability and must be punished with a logarithm?", not "cross-entropy".
- Count the new terms. The 3B1B guide is **≈0.3 new terms per minute**, at most 0.5 even in the
  best videos. Our unclear part 3 carried ≈2.7 per minute: nine topics in five minutes. More than
  one new term per 1–2 minutes: cut topics or split into videos.
- A topic that does not answer the central question goes to a separate video or to a "think about
  it" at the end. Survey lists (frameworks, kinds of functions) are not a topic.
- For a lecture summary, pick the 2–3 ideas that cannot be understood from a slide and develop
  them. Everything else is one closing card "what else was in the lecture" with no voiced definitions.

## 2. Script: a chain of "defect → fix"

Every new concept appears as the answer to a problem the viewer has already seen.

| Bad (agenda) | Good (necessity) |
|---|---|
| "Now the output layer." | "A sigmoid answers for one class. We have three: cat, dog, bird. What now?" |
| "Now we need an error." | "The network said 'cat: 66 %'. Is that good or bad? We need a number that says how much." |
| "Cross-entropy is minus the logarithm of the probability of the right class." | "Will any decreasing function do? Let us try several and see that only the logarithm has the property we need." |

Rules:
1. **The question before the tool.** Each block opens with a question or a defect of the previous
   block. A "now X" transition without a reason is acceptable about once per 10 minutes (3B1B: 0.08
   per minute; our part 3: almost 1 per minute).
2. **The example before the rule.** First a concrete case with concrete numbers, then notation, then
   the general formula. A notation is introduced as the name of what is already on screen.
3. **The simplest case.** First a deliberately simplified version (one neuron per layer, two
   outcomes, one input); generalize afterwards in one phrase, "almost nothing changes, only indices".
4. **One example for the whole topic.** Do not change the example in each block. One object lives
   through the video and changes, so the viewer spends no attention on a new picture.
5. **The meaning of a symbol before the calculation.** Before computing ∂z/∂x, say and show what it
   is: "shift x by 0.01: how far does z move?". Check with a number before the formula, not after.
6. **Warn about the misconception.** Where the viewer will probably think wrongly, say it in their
   words and take it apart (3B1B: ≈0.2 times per minute).
7. **Repeat the main conclusion 2–4 times** in different words: when it appears, when it is used,
   at the end.
8. **No more than two numbers in a row by voice.** Three or more go on screen, and the voice says
   only what to compare them with ("the first became six times larger than the rest").
9. **"Why this and not otherwise"** for every formula the video introduces. If the answer does not
   fit, do not introduce the formula; show its behaviour.
10. **From the viewer's seat.** Walk through `STEPS` in order and, for every `say` phrase and every
    object in the frame, ask: what has the viewer already seen and heard by this second, and is this
    clear from that alone? If understanding relies on knowledge the video has not yet given (from the
    lecture, the author's head, a neighbouring step), rewrite the phrase or show the missing piece first.
    Example: "the output error equals p minus y", but `y` never appeared in the video, only in the
    lecture. First a step: "write the right answer as a column: one for the cat, zeros for the rest;
    this is y", and the `y` column stands next to the `p` column; only then the difference.

Block template (2–4 min per idea): `defect or question → concrete example with numbers →
observation on screen → name and notation → general form → "why so" → repeat the conclusion →
the defect that leads to the next block`.

## 3. Storyboard: visual language

- **Colour is scarce.** 3B1B keeps 72–89 % of the frame on a plain black ground and saturated colour
  at 1–8 %. Our default `paper` theme is a light ground, but the principle holds: colour is a signal,
  not decoration.
- **Colour = meaning, for the whole video.** Make a "quantity → colour" table before the first scene
  and keep it: if p is green, it is green on the bar, in the formula, in the label and in running
  text. One colour never means two objects in one video.
- **One typeface.** Text in the same face as the formulas (CMU Serif / Computer Modern) where the
  scene allows it; numbers inside formulas go through `MathTex`, not monospace next to the formula.
- **Labels of 1–5 words.** A theorem or a definition is not a paragraph on screen: the object and a
  short label are on screen, the voice says the wording. The sentence subtitles at the bottom
  (`sub`/`say`, our format for Telegram without sound) already are text; do not duplicate them with
  another line in the scene.
- **A symbol is born from an object.** The label at the object (`q` at the bar) in the same colour,
  then a copy of that label flies into the formula (`TransformFromCopy(label, eq[k])`). The formula is
  assembled from parts already shown, not shown whole (a whole-formula `Write` only for short ones).
- **Dim, do not remove.** What is no longer the main thing goes to 15–25 % opacity (`set_opacity`)
  instead of `FadeOut`. The next object can stand beside it in advance as a ghost.
- **Emphasis** is a frame, an underline, recolouring one symbol; not a new line of text.
- **A through object.** Avoid `FadeOut` of everything between blocks. If the scene must change,
  carry at least one object from the old scene into the new (the network, an axis, a bar): a bridge
  for the eye.
- **Our characters, not theirs.** The π creatures are the 3B1B author's; make the "viewer's voice"
  your own character or a question label.

Recipes for these moves in our Manim CE: `references/manim-ce.md`. The 9:16 variant of the frame
(`--format vertical`) needs its own layout, see `video-artifact`.

## 4. Voice and pauses

Target numbers (medians of 127 3B1B videos):

| | Target |
|---|---|
| Rate | ≈4.5 syllables/s over all speaking time (5.4 without pauses) |
| Pause after a full stop | ≈0.6 s, after a turn 1–2 s |
| Pause after a comma, dash or colon | ≈0.3 s |
| Pauses ≥ 1 s | ≈2 per minute; ≥ 2 s about 0.4 per minute; 65 % of the long ones follow the end of a sentence, before "and / so / now / but" |
| Time spent in pauses | ≈20 % |
| Motion on screen during long pauses | in about half of them |

How to get this in the current tool (the specifics are in `video-artifact`):
- `--rate 1.0` is the default and stays (owner decision, 16.10.2026); check by ear before changing it.
- Tera intonates commas, colons and dashes itself, because each sentence is synthesized whole;
  the tool cuts only at sentence ends and at an explicit `[sec]`. Do not try to force a pause with
  punctuation. A pause the meaning needs is an explicit `[0.6]` in `say`, a step boundary, or `hold`.
- **One sentence, one step** when the pause after it must be longer than the default end pause.
- **`hold` on any step**: after a question, before the answer, after a formula appears. Use
  `hold: 1.2–2.0` and have something happen on screen meanwhile (a symbol flies, a formula assembles,
  an object is recoloured). A silent beat is `say: ""` with a positive `hold`.
- Stress: a manual `+` marks one word; the other words of the phrase are still stressed
  automatically. Details and the check in `references/voice-checks.md`.

Measure the result on the voice-only track:
`uv run --script /home/kesha/orchestra/scripts/video_artifact/pace.py out/<name>.voice.wav --timing out/<name>.timing.json`
prints pauses per minute (all, ≥ 0.5 s, ≥ 1 s, ≥ 2 s), their share of talk time and vowels per second;
compare it with the table above.

## 5. Check before building (checklist)

Go through `STEPS` before `--timing-only`; each item is yes/no.

**Selection**
- [ ] The central question is written in one sentence and is voiced in the first 30–60 s.
- [ ] New terms ≤ 1 per 1.5–2 min of length; the extra ones are moved out.

**Script**
- [ ] The first phrase of every block is a question or a defect, not "Now X".
- [ ] Every formula is preceded by a concrete example with numbers.
- [ ] The simplest case comes before the general one.
- [ ] One through example; a new example only with an explanation of why.
- [ ] No `say` has three or more numbers in a row.
- [ ] The main conclusion is voiced ≥ 2 times; there is a "why so and not otherwise".
- [ ] At least one voiced misconception per video.
- [ ] Walked "from the viewer's seat": every phrase and every object is clear from what the video
      has already shown and said by that second.

**Storyboard**
- [ ] A colour table exists and no colour means two things.
- [ ] Labels in the scene are ≤ 5 words; definitions are not set as paragraphs.
- [ ] Every notation appears at its object and is carried into the formula.
- [ ] No `FadeOut` of everything between blocks without carrying an object over.

**Voice**
- [ ] `--stress-only`: in phrases with a manual `+`, the automatic stresses of the other words are checked too.
- [ ] After questions, before answers and after formulas there is a `hold` ≥ 1 s with animation in it.
- [ ] Pauses the meaning needs are explicit (`[sec]`, a step boundary or `hold`), not punctuation hopes.
- [ ] Rate: `--rate 1.0` or a deliberately different value.

**After the build** (in addition to the `video-artifact` checks): watch the video with sound from
start to end and answer: which question does each block answer? A block with no answer is superfluous.
Run `pace.py` and compare with the table in section 4.

The agent chain "author → tester → proofreader" does not catch the error "knowledge the viewer has
not yet received": all of them know the material in advance. A final viewing through the viewer's
eyes is mandatory.
