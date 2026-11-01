"""Pick questions for a quiz and render the quiz, the answer sheet and the key."""
import random
from dataclasses import dataclass

from quizgen.bank import LETTERS, Question


@dataclass
class Quiz:
    """A titled list of questions in the order they are asked."""

    title: str
    questions: list[Question]

    def maxScore(self) -> int:
        """Return the score of a sheet with every answer correct."""
        return sum(question.points for question in self.questions)


def pickQuestions(questions: dict[str, Question], count: int, seed: int | None = None) -> list[Question]:
    """Pick count different questions at random.

    The same seed and the same banks always give the same pick. Raises ValueError
    when count is less than 1 or larger than the number of questions.
    """
    if not 1 <= count <= len(questions):
        raise ValueError(f"cannot pick {count} questions from {len(questions)}")
    picked = random.Random(seed).sample(sorted(questions), count)
    return [questions[qid] for qid in picked]


def renderQuiz(quiz: Quiz) -> str:
    """Return the quiz text with numbered questions and lettered choices."""
    lines = [quiz.title, "=" * len(quiz.title), ""]
    for number, question in enumerate(quiz.questions, start=1):
        unit = "point" if question.points == 1 else "points"
        lines.append(f"{number}. [{question.qid}] {question.text} ({question.points} {unit})")
        for letter, choice in zip(LETTERS, question.choices):
            lines.append(f"   {letter}) {choice}")
        lines.append("")
    lines.append(f"Maximum score: {quiz.maxScore()}")
    return "\n".join(lines) + "\n"


def answerSheet(quiz: Quiz) -> str:
    """Return a blank answer sheet with one "id:" line per question.

    Students write the letter of their choice after each colon.
    """
    lines = [f"# {quiz.title}", "# Write one letter after each colon."]
    lines += [f"{question.qid}:" for question in quiz.questions]
    return "\n".join(lines) + "\n"


def answerKey(quiz: Quiz) -> list[tuple[str, str, int]]:
    """Return (question id, answer letter, points) for every question of the quiz."""
    return [(question.qid, question.answer, question.points) for question in quiz.questions]
