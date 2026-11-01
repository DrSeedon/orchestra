import pytest

from gradebook.models import Assessment, Score
from gradebook.weighting import normalizeWeights, percentFor, weightedAverage

HOMEWORK = Assessment("homework", 0.2, 50)
MIDTERM = Assessment("midterm", 0.3, 100)
FINAL = Assessment("final", 0.5, 120)
ALL = [HOMEWORK, MIDTERM, FINAL]


def testPercentFor():
    assert percentFor(Score("s1", "homework", 40), HOMEWORK) == 80.0


def testPercentForExcused():
    assert percentFor(Score("s1", "homework", None), HOMEWORK) is None


def testPercentForRejectsTooManyPoints():
    with pytest.raises(ValueError, match="outside 0..50"):
        percentFor(Score("s1", "homework", 51), HOMEWORK)


def testNormalizeWeights():
    weights = normalizeWeights([Assessment("a", 1, 10), Assessment("b", 3, 10)])
    assert weights == {"a": 0.25, "b": 0.75}


def testNormalizeWeightsRejectsZero():
    with pytest.raises(ValueError):
        normalizeWeights([Assessment("a", 0, 10)])


def testWeightedAverage():
    scores = [Score("s1", "homework", 50), Score("s1", "midterm", 80), Score("s1", "final", 90)]
    assert weightedAverage(scores, ALL) == pytest.approx(0.2 * 100 + 0.3 * 80 + 0.5 * 75)


def testWeightedAverageRescalesWithoutExcused():
    scores = [Score("s1", "midterm", 60), Score("s1", "final", None)]
    assert weightedAverage(scores, ALL) == pytest.approx(60.0)


def testWeightedAverageNothingCounted():
    assert weightedAverage([Score("s1", "final", None)], ALL) is None
    assert weightedAverage([], ALL) is None


def testWeightedAverageUnknownAssessment():
    with pytest.raises(ValueError, match="unknown assessment: quiz"):
        weightedAverage([Score("s1", "quiz", 3)], ALL)
