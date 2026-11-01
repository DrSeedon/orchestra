"""Generate a quiz from the question banks.

Run as ``python -m quizgen.generate BANKS_DIR COUNT OUTPUT_DIR [--seed N] [--title TEXT]``.
It writes quiz.txt, sheet.txt and key.csv into OUTPUT_DIR.
"""
import argparse
import csv
import sys
from pathlib import Path

from quizgen.bank import loadBanks
from quizgen.quiz import Quiz, answerKey, answerSheet, pickQuestions, renderQuiz

KEY_COLUMNS = ("question", "answer", "points")


def writeQuiz(quiz: Quiz, folder: Path) -> list[Path]:
    """Write quiz.txt, sheet.txt and key.csv into folder and return their paths.

    The folder is created when it does not exist.
    """
    folder.mkdir(parents=True, exist_ok=True)
    quizFile = folder / "quiz.txt"
    sheetFile = folder / "sheet.txt"
    keyFile = folder / "key.csv"
    quizFile.write_text(renderQuiz(quiz), encoding="utf-8")
    sheetFile.write_text(answerSheet(quiz), encoding="utf-8")
    with keyFile.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(KEY_COLUMNS)
        writer.writerows(answerKey(quiz))
    return [quizFile, sheetFile, keyFile]


def parseArgs(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command line of the generate command."""
    parser = argparse.ArgumentParser(prog="python -m quizgen.generate")
    parser.add_argument("banks", help="folder with the *.ini question banks")
    parser.add_argument("count", type=int, help="number of questions to pick")
    parser.add_argument("output", help="folder for quiz.txt, sheet.txt and key.csv")
    parser.add_argument("--seed", type=int, help="seed for a repeatable pick")
    parser.add_argument("--title", default="Quiz", help="title printed on the quiz")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the generate command and return its exit status."""
    args = parseArgs(argv)
    try:
        questions = loadBanks(args.banks)
        picked = pickQuestions(questions, args.count, args.seed)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for path in writeQuiz(Quiz(args.title, picked), Path(args.output)):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
