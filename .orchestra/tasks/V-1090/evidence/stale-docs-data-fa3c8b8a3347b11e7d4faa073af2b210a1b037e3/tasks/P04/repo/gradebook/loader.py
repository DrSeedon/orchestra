"""Read a course from its JSON export."""
import json
from typing import Any, Optional

from gradebook.course import Course
from gradebook.models import Assessment, Student


def parseAssessment(data: dict[str, Any]) -> Assessment:
    """Build an assessment from its JSON object (name, weight, max)."""
    return Assessment(str(data["name"]), float(data["weight"]), float(data["max"]))


def parseStudent(data: dict[str, Any]) -> Student:
    """Build a student from its JSON object (id, name and an email that may be missing)."""
    email: Optional[str] = data.get("email")
    return Student(str(data["id"]), str(data["name"]), email)


def parsePoints(value: Any) -> Optional[float]:
    """Points of a score entry; null marks an excused assessment."""
    if value is None:
        return None
    return float(value)


def courseFromData(data: dict[str, Any]) -> Course:
    """Build a course with its students and scores from the parsed export."""
    course = Course(str(data["code"]), [parseAssessment(item) for item in data.get("assessments", [])])
    for item in data.get("students", []):
        course.addStudent(parseStudent(item))
    for item in data.get("scores", []):
        course.recordScore(str(item["student"]), str(item["assessment"]), parsePoints(item.get("points")))
    return course


def loadCourse(path: str) -> Course:
    """Read a course export file.

    Raises OSError when the file cannot be read, and ValueError or KeyError
    when its content is not a valid course.
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"not a course export: {path}")
    return courseFromData(data)
