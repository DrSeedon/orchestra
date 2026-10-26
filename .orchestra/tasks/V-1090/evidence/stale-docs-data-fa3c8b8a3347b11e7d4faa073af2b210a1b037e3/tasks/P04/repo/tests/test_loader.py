import json

import pytest

from gradebook.loader import courseFromData, loadCourse, parseAssessment, parseStudent
from gradebook.models import Assessment, Student

EXPORT = {
    "code": "CS101",
    "assessments": [{"name": "midterm", "weight": 0.4, "max": 50}, {"name": "final", "weight": 0.6, "max": 100}],
    "students": [{"id": "s2", "name": "Alan Turing", "email": "alan@example.edu"}, {"id": "s1", "name": "Ada Lovelace"}],
    "scores": [
        {"student": "s1", "assessment": "midterm", "points": 40},
        {"student": "s1", "assessment": "final", "points": 90},
        {"student": "s2", "assessment": "final", "points": None},
    ],
}


def testParseAssessment():
    assert parseAssessment({"name": "quiz", "weight": 1, "max": 10}) == Assessment("quiz", 1.0, 10.0)


def testParseStudentWithoutEmail():
    assert parseStudent({"id": "s1", "name": "Ada Lovelace"}) == Student("s1", "Ada Lovelace", None)


def testCourseFromData():
    course = courseFromData(EXPORT)
    assert course.code == "CS101"
    assert [student.student_id for student in course.students] == ["s1", "s2"]
    assert course.finalPercent("s1") == pytest.approx(0.4 * 80 + 0.6 * 90)
    assert course.finalPercent("s2") is None


def testCourseFromDataUnknownStudent():
    data = dict(EXPORT, scores=[{"student": "s9", "assessment": "final", "points": 1}])
    with pytest.raises(KeyError):
        courseFromData(data)


def testLoadCourse(tmp_path):
    path = tmp_path / "course.json"
    path.write_text(json.dumps(EXPORT), encoding="utf-8")
    assert loadCourse(str(path)).students[1].email == "alan@example.edu"


def testLoadCourseRejectsOtherContent(tmp_path):
    path = tmp_path / "course.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        loadCourse(str(path))
