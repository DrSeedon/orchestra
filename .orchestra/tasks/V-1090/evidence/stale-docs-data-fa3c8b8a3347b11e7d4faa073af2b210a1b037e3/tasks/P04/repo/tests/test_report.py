import json

import pytest

from gradebook.course import Course
from gradebook.models import Assessment, Student
from gradebook.report import ReportRow, buildReport, classAverage, formatPercent, formatReport, main


def makeCourse():
    course = Course("CS101", [Assessment("exam", 1.0, 100)])
    course.addStudent(Student("s2", "Alan Turing"))
    course.addStudent(Student("s1", "Ada Lovelace"))
    course.addStudent(Student("s3", "Grace Hopper"))
    course.recordScore("s1", "exam", 95)
    course.recordScore("s2", "exam", 72.5)
    course.recordScore("s3", "exam", None)
    return course


def testBuildReport():
    rows = buildReport(makeCourse())
    assert rows == [
        ReportRow("s1", "Ada Lovelace", 95.0, "A"),
        ReportRow("s2", "Alan Turing", 72.5, "C"),
        ReportRow("s3", "Grace Hopper", None, None),
    ]


def testClassAverageSkipsMissing():
    assert classAverage(buildReport(makeCourse())) == pytest.approx(83.75)
    assert classAverage([]) is None


def testFormatPercent():
    assert formatPercent(83.75) == "83.8"
    assert formatPercent(None) == "-"


def testFormatReport():
    lines = formatReport(buildReport(makeCourse())).splitlines()
    assert lines[0].split() == ["ID", "Name", "Pct", "Grade"]
    assert lines[1].split() == ["s1", "Ada", "Lovelace", "95.0", "A"]
    assert lines[3].split() == ["s3", "Grace", "Hopper", "-", "-"]
    assert lines[-1] == "Class average: 83.8"


def testMainWritesReport(tmp_path):
    export = {
        "code": "CS101",
        "assessments": [{"name": "exam", "weight": 1, "max": 100}],
        "students": [{"id": "s1", "name": "Ada Lovelace"}],
        "scores": [{"student": "s1", "assessment": "exam", "points": 88}],
    }
    source = tmp_path / "course.json"
    source.write_text(json.dumps(export), encoding="utf-8")
    output = tmp_path / "report.txt"
    assert main([str(source), str(output)]) == 0
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[1].split() == ["s1", "Ada", "Lovelace", "88.0", "B"]
    assert lines[-1] == "Class average: 88.0"


def testMainMissingCourse(tmp_path):
    output = tmp_path / "report.txt"
    assert main([str(tmp_path / "missing.json"), str(output)]) == 2
    assert not output.exists()
