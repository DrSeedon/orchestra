"""A course: its students, assessments and recorded scores."""
from typing import Optional

from gradebook.models import Assessment, Score, Student
from gradebook.weighting import weightedAverage


class Course:
    def __init__(self, code: str, assessments: Optional[list[Assessment]] = None) -> None:
        self.code = code
        self.assessments: list[Assessment] = list(assessments or [])
        self._students: dict[str, Student] = {}
        self._scores: dict[tuple[str, str], Score] = {}

    @property
    def students(self) -> list[Student]:
        return sorted(self._students.values(), key=lambda student: student.student_id)

    def addStudent(self, student: Student) -> None:
        if student.student_id in self._students:
            raise ValueError(f"duplicate student id: {student.student_id}")
        self._students[student.student_id] = student

    def addAssessment(self, assessment: Assessment) -> None:
        if any(existing.name == assessment.name for existing in self.assessments):
            raise ValueError(f"duplicate assessment: {assessment.name}")
        self.assessments.append(assessment)

    def recordScore(self, student_id: str, assessment: str, points: Optional[float]) -> Score:
        """Store (or replace) a score. Use points=None for an excused assessment."""
        if student_id not in self._students:
            raise KeyError(f"unknown student: {student_id}")
        if not any(existing.name == assessment for existing in self.assessments):
            raise KeyError(f"unknown assessment: {assessment}")
        score = Score(student_id, assessment, points)
        self._scores[(student_id, assessment)] = score
        return score

    def scoresFor(self, student_id: str) -> list[Score]:
        return [score for (sid, _), score in self._scores.items() if sid == student_id]

    def finalPercent(self, student_id: str) -> Optional[float]:
        """Weighted course percentage, or None when the student has no counted scores."""
        return weightedAverage(self.scoresFor(student_id), self.assessments)

    def findStudent(self, name: str) -> Optional[Student]:
        """Case-insensitive lookup by full name."""
        wanted = name.strip().lower()
        for student in self._students.values():
            if student.name.lower() == wanted:
                return student
        return None
