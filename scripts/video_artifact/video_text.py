"""Text transformations shared by video captions and Russian speech synthesis."""
from __future__ import annotations

import re


class UnsupportedVoskSymbol(ValueError):
    def __init__(self, symbol: str):
        self.symbol = symbol
        super().__init__(symbol)


_VOSK_TRANSLATION = str.maketrans({
    **dict.fromkeys("«»„‟‹›‘’‚‛“”‟❛❜❝❞", '"'),
    "'": '"',
    **dict.fromkeys("‐‑‒–—―−﹘﹣－", " - "),
    "…": "...",
    "\u00a0": " ",
    "\u202f": " ",
    "\u2009": " ",
})
_VOSK_PUNCTUATION = set('+.,?!;:-"()')


def caption_text(step: dict) -> str:
    if step.get("sub") is not None:
        return step["sub"]
    return step["say"].replace("+", "")


def normalize_vosk_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text.translate(_VOSK_TRANSLATION)).strip()
    for symbol in text:
        if symbol not in _VOSK_PUNCTUATION and not ("А" <= symbol <= "я" or symbol in "Ёё") and symbol != " ":
            raise UnsupportedVoskSymbol(symbol)
    return text
