import pytest

from gradebook.course import Course
from gradebook.models import Assessment, Student


def makeCourse():
    course = Course("CS101", [Assessment("midterm", 0.4, 100), Assessment("final", 0.6, 100)])
    course.addStudent(Student("s1", "Ada Lovelace"))
    course.addStudent(Student("s2", "Alan Turing", "alan@example.edu"))
    return course


def testAddStudentRejectsDuplicates():
    course = makeCourse()
    with pytest.raises(ValueError, match="duplicate student id: s1"):
        course.addStudent(Student("s1", "Someone Else"))


def testAddAssessmentRejectsDuplicates():
    with pytest.raises(ValueError):
        makeCourse().addAssessment(Assessment("final", 1.0, 50))


def testRecordScoreReplacesEarlierScore():
    course = makeCourse()
    course.recordScore("s1", "midterm", 50)
    course.recordScore("s1", "midterm", 70)
    assert [score.points for score in course.scoresFor("s1")] == [70]


def testRecordScoreUnknownStudentOrAssessment():
    course = makeCourse()
    with pytest.raises(KeyError):
        course.recordScore("s9", "midterm", 50)
    with pytest.raises(KeyError):
        course.recordScore("s1", "quiz", 5)


def testFinalPercent():
    course = makeCourse()
    course.recordScore("s1", "midterm", 80)
    course.recordScore("s1", "final", 90)
    assert course.finalPercent("s1") == pytest.approx(86.0)
    assert course.finalPercent("s2") is None


def testFindStudent():
    course = makeCourse()
    assert course.findStudent("  alan turing ").student_id == "s2"
    assert course.findStudent("Grace Hopper") is None


def testStudentsSortedById():
    course = makeCourse()
    course.addStudent(Student("s0", "Grace Hopper"))
    assert [student.student_id for student in course.students] == ["s0", "s1", "s2"]
