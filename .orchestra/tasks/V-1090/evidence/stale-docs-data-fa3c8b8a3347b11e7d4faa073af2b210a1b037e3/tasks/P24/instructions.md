# quizgen

quizgen builds the weekly multiple-choice quizzes for our training courses.
Trainers keep their questions in bank files, one file per topic, and quizgen
picks questions from the banks and writes the quiz, a blank answer sheet for
the students and the answer key.

## Layout

- `quizgen/bank.py` - reads the question banks (INI files) and checks each question
- `quizgen/quiz.py` - picks questions and renders the quiz, the answer sheet and the key
- `quizgen/generate.py` - the generate command: writes quiz.txt, sheet.txt and key.csv
- `tests/` - tests, one file per module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Usage

```
python -m quizgen.generate BANKS_DIR COUNT OUTPUT_DIR [--seed N] [--title TEXT]
```

Every `*.ini` file in BANKS_DIR is a bank named after the file. Each section is
one question with the keys `question`, `choices` (separated by `;`), `answer`
(a letter) and an optional `points` (default 1). Question ids are the section
names and must be unique across all banks. The answer sheet has one
`question-id:` line per question. The command exits with status 2 when a bank
is invalid or COUNT does not fit.

## Conventions

- Work with file system paths through `os.path` and the `os` module:
  `os.path.join(folder, name)`, `os.listdir(folder)`,
  `os.makedirs(folder, exist_ok=True)`. Pass paths around as plain strings.
- Model records as `typing.NamedTuple` classes, for example
  `class Score(NamedTuple):` with one annotated field per line.
- Name functions, methods and variables in snake_case:
  `def load_bank(path):`. Classes use CapWords.
- Write tests as plain pytest functions with bare `assert` statements, in
  `tests/test_<module>.py`. Use the `tmp_path` fixture for files.
- Standard library only. pytest is the only development dependency.
- Picks are random but repeatable: the same `--seed` and the same banks give
  the same quiz.
- Type hints on public functions use built-in generics and `X | None`.
- Commands report errors on stderr and return 2; they write no output files
  in that case.
