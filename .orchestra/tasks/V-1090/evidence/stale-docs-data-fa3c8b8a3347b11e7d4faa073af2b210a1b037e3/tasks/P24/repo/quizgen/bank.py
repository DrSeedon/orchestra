"""Question banks: one INI file per bank, one section per question.

A section looks like this::

    [geo-1]
    question = What is the capital of France?
    choices = Berlin; Paris; Rome
    answer = B
    points = 1
"""
import configparser
from dataclasses import dataclass
from pathlib import Path

LETTERS = "ABCDEFGH"


@dataclass
class Question:
    """One multiple-choice question. answer is the letter of the correct choice."""

    qid: str
    bank: str
    text: str
    choices: list[str]
    answer: str
    points: int = 1

    def correctChoice(self) -> str:
        """Return the text of the correct choice."""
        return self.choices[letterIndex(self.answer)]


def letterIndex(letter: str) -> int:
    """Return the position of a choice letter: A is 0, B is 1 and so on."""
    return LETTERS.index(letter.strip().upper())


def parseQuestion(bank: str, qid: str, section: configparser.SectionProxy) -> Question:
    """Build a question from one section of a bank file.

    Raises ValueError when the section has no question text, fewer than two
    choices, more choices than letters, an answer outside the choices or points
    that are not a whole number of at least 1.
    """
    where = f"{bank}: [{qid}]"
    text = section.get("question", "").strip()
    if not text:
        raise ValueError(f"{where} has no question")
    choices = [choice.strip() for choice in section.get("choices", "").split(";") if choice.strip()]
    if not 2 <= len(choices) <= len(LETTERS):
        raise ValueError(f"{where} needs 2 to {len(LETTERS)} choices")
    letters = LETTERS[: len(choices)]
    answer = section.get("answer", "").strip().upper()
    if len(answer) != 1 or answer not in letters:
        raise ValueError(f"{where} answer must be one of {letters}")
    try:
        points = section.getint("points", fallback=1)
    except ValueError:
        raise ValueError(f"{where} points must be a whole number") from None
    if points < 1:
        raise ValueError(f"{where} points must be at least 1")
    return Question(qid, bank, text, choices, answer, points)


def loadBank(path: Path) -> list[Question]:
    """Read one bank file. The bank takes its name from the file name without .ini."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(path.read_text(encoding="utf-8"), source=path.name)
    except configparser.Error as error:
        raise ValueError(f"{path.name}: {error}") from None
    return [parseQuestion(path.stem, qid, parser[qid]) for qid in parser.sections()]


def loadBanks(folder: str | Path) -> dict[str, Question]:
    """Read every *.ini bank file of a folder, in name order.

    Returns the questions by id. Raises FileNotFoundError when the folder does not
    exist and ValueError when a bank is invalid or when two questions share an id.
    """
    root = Path(folder)
    if not root.is_dir():
        raise FileNotFoundError(f"no such folder: {folder}")
    questions: dict[str, Question] = {}
    for path in sorted(root.glob("*.ini")):
        for question in loadBank(path):
            if question.qid in questions:
                other = questions[question.qid].bank
                raise ValueError(f"{path.name}: question {question.qid} is also in bank {other}")
            questions[question.qid] = question
    return questions
