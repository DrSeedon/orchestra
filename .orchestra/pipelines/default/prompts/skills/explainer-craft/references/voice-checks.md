# Voice: what to check and how to measure

## Reading check (default voice: ElevenLabs Flash, Sergey)

- No stress marks, RUAccent pass or `<name>.stress.txt`: they belong to the local engines only.
- What must be checked instead is how the text is read. The tool sends no text-normalization option and
  Flash on the Starter tier is not guaranteed to normalize, so test numbers, dates, years, units,
  abbreviations, acronyms and Latin names in the Russian or English you are going to use. Where a
  reading is wrong or case endings matter, write the spoken form in `say` (Russian numbers as words
  with the right case) and keep the digits in the on-screen `sub`.
- Listen to the result (ear-check) and, when a Deepgram key exists, read `recall` and the missing
  words in `<name>.check.json`. A wrong reading is cured by rewriting `say`, not by markers.
- Do not synthesize "to try": generation spends characters. Use `--preview-step` / `--preview-range`
  (no API, no key) for the picture, and test a reading on the shortest phrase that shows it.

## Local engines only: TeraTTS stresses

- The automatic stress is done by RUAccent inside the tool. A manual `+` marks that one word and
  the other words of the phrase are still stressed automatically (`video-artifact` describes the
  stress dictionary and the manual marker).
- Every Tera build writes `<name>.stress.txt` with the marked phrase per line; `--stress-only` writes it
  without synthesis (it refuses to run for ElevenLabs). Read it line by line and look for homographs
  and wrongly stressed words, not only the one you corrected.

## Pauses inside a phrase

Measured by us in V-878 on the local Tera engine (`--rate 1.0`): a comma gives ≈0.36–0.38 s, a full
stop ≈0.70 s, a silent step ≈1.10 s. These are Tera values and history; ElevenLabs Flash has not been
measured here. With any engine the model intonates each sentence whole, so a pause the meaning needs
is an explicit `[sec]` (literal local silence), a step boundary or `hold`. Measure the actual voice
with `pace.py` before relying on a number.

## Guides from 3Blue1Brown (127 videos, medians)

| What | Value |
|---|---|
| Rate | 4.5 syllables/s over all speaking time, 5.4 without pauses |
| Pause after a full stop | 0.63 s, after a comma 0.33 s |
| Pauses ≥ 1 s | 1.9 per minute; 65 % of them after the end of a sentence, before "and / so / now / but" |
| The longest pause in a video | ≈3.7 s |
| Share of time in pauses | 20 % |

## How to measure your own video

`scripts/video_artifact/pace.py` (inline-dependency uv script; heavy decoding goes through
`ssh kesha@localhost`; no API call):

```
uv run --script scripts/video_artifact/pace.py out/<name>.voice.wav --timing out/<name>.timing.json
```

Feed it the voice-only `<name>.voice.wav`: the music bed sits only ≈15 dB under the voice and would
hide the pauses in the MP4. It prints pauses per minute (all, ≥ 0.5 s, ≥ 1 s, ≥ 2 s), their share of
talk time, the median and the longest pause, and with `--timing` vowels per second (Russian vowel
letters of `say`), the counterpart of the syllable guide above.
