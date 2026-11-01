"""Record types for the gradebook."""
from typing import NamedTuple, Optional


class Student(NamedTuple):
    student_id: str
    name: str
    email: Optional[str] = None


class Assessment(NamedTuple):
    name: str
    weight: float
    max_points: float


class Score(NamedTuple):
    student_id: str
    assessment: str
    points: Optional[float]

    def isExcused(self) -> bool:
        """An excused score (points is None) does not count toward the grade."""
        return self.points is None
