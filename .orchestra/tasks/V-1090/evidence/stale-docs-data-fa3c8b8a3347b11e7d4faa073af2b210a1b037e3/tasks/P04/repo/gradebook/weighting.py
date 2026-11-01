"""Turn raw points into percentages and weighted course percentages."""
from typing import Optional

from gradebook.models import Assessment, Score


def percentFor(score: Score, assessment: Assessment) -> Optional[float]:
    """Return the score as a percentage of the assessment, or None if excused."""
    if score.isExcused():
        return None
    if score.points < 0 or score.points > assessment.max_points:
        raise ValueError(
            f"{score.points} points is outside 0..{assessment.max_points} for {assessment.name}"
        )
    return 100.0 * score.points / assessment.max_points


def normalizeWeights(assessments: list[Assessment]) -> dict[str, float]:
    """Scale the weights so they add up to 1.0."""
    total = sum(assessment.weight for assessment in assessments)
    if total <= 0:
        raise ValueError("assessment weights must add up to more than zero")
    return {assessment.name: assessment.weight / total for assessment in assessments}


def weightedAverage(scores: list[Score], assessments: list[Assessment]) -> Optional[float]:
    """Weighted percentage over the scored assessments.

    Excused assessments are left out and the remaining weights are rescaled.
    Returns None when no assessment counts.
    """
    by_name = {assessment.name: assessment for assessment in assessments}
    counted: list[tuple[Assessment, float]] = []
    for score in scores:
        assessment = by_name.get(score.assessment)
        if assessment is None:
            raise ValueError(f"unknown assessment: {score.assessment}")
        percent = percentFor(score, assessment)
        if percent is not None:
            counted.append((assessment, percent))
    if not counted:
        return None
    weights = normalizeWeights([assessment for assessment, _ in counted])
    return sum(weights[assessment.name] * percent for assessment, percent in counted)
