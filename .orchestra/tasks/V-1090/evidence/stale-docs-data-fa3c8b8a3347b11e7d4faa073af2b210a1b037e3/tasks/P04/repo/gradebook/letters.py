"""Letter grades and grade points."""
from typing import Optional

Scale = tuple[tuple[float, str], ...]

DEFAULT_SCALE: Scale = ((90.0, "A"), (80.0, "B"), (70.0, "C"), (60.0, "D"), (0.0, "F"))
GRADE_POINTS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0}


def validateScale(scale: Scale) -> None:
    """Check that thresholds strictly descend and the last one is 0."""
    thresholds = [threshold for threshold, _ in scale]
    if not thresholds or thresholds[-1] != 0.0:
        raise ValueError("a grade scale must end at 0")
    if any(high <= low for high, low in zip(thresholds, thresholds[1:])):
        raise ValueError("grade scale thresholds must strictly descend")


def letterFor(percent: float, scale: Optional[Scale] = None) -> str:
    """Return the letter for a percentage (0-100) on the given scale."""
    scale = scale or DEFAULT_SCALE
    if not 0.0 <= percent <= 100.0:
        raise ValueError(f"percent out of range: {percent}")
    for threshold, letter in scale:
        if percent >= threshold:
            return letter
    raise ValueError(f"no letter for {percent}")


def gradePoints(letter: str) -> Optional[float]:
    """Grade points for a letter, or None for a letter that carries no points."""
    return GRADE_POINTS.get(letter.upper())
