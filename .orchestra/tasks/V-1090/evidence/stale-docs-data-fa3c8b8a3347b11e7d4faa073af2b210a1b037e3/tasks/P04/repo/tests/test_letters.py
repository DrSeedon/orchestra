import pytest

from gradebook.letters import gradePoints, letterFor, validateScale


@pytest.mark.parametrize(
    "percent, letter",
    [(100.0, "A"), (90.0, "A"), (89.9, "B"), (70.0, "C"), (60.5, "D"), (0.0, "F")],
)
def testLetterForDefaultScale(percent, letter):
    assert letterFor(percent) == letter


def testLetterForCustomScale():
    scale = ((50.0, "Pass"), (0.0, "Fail"))
    assert letterFor(49.0, scale) == "Fail"
    assert letterFor(50.0, scale) == "Pass"


def testLetterForRejectsOutOfRange():
    with pytest.raises(ValueError):
        letterFor(101.0)


def testValidateScale():
    validateScale(((75.0, "Pass"), (0.0, "Fail")))
    with pytest.raises(ValueError, match="end at 0"):
        validateScale(((75.0, "Pass"), (10.0, "Fail")))
    with pytest.raises(ValueError, match="descend"):
        validateScale(((50.0, "B"), (60.0, "A"), (0.0, "F")))


def testGradePoints():
    assert gradePoints("b") == 3.0
    assert gradePoints("Pass") is None
