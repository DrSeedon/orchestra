# more numbers

Computed from runs.jsonl by scripts/more_numbers.py.

## Rewrites (Section 5.4)

- Claude Code, without the sentence: 0 of 80 runs
- Claude Code, with the sentence: 0 of 80 runs
- Codex CLI, without the sentence: 20 of 80 runs
- Codex CLI, with the sentence: 0 of 80 runs
- Codex CLI without the sentence: tests failed in 17 of 20 rewrites; median 198 lines removed from a median of 9 files; 12 projects
- largest number of removed lines in a run that is not a rewrite: 18

## What each run did (Figure 6)

- Claude Code, without the sentence: followed the code, reported the conflict 2; followed the file, did not report the conflict 1; followed the file, reported the conflict 71; no majority, reported the conflict 6
- Codex CLI, without the sentence: followed the file, did not report the conflict 60; rewrote existing code, tests failed 17; rewrote existing code, tests passed 3
- Claude Code, with the sentence: followed the code, reported the conflict 80
- Codex CLI, with the sentence: followed the code, reported the conflict 79; no majority, reported the conflict 1

## Difference in the share of choices that follow the code (Section 5.3)

- both agents: 87.2 percentage points, 95% interval [83.6, 90.9]
- Claude Code: 86.9 percentage points, 95% interval [81.1, 92.2]
- Codex CLI: 87.5 percentage points, 95% interval [83.6, 91.2]

## Projects per kind of choice (Figure 4)

- CONFIG: 11 projects (file asks for config dataclass: 6; file asks for config dict: 5)
- DOCSTR: 11 projects (file asks for Google docstring: 5; file asks for reST docstring: 6)
- ENUM: 11 projects (file asks for Enum: 5; file asks for string constants: 6)
- ERR: 11 projects (file asks for raise: 5; file asks for return (value, error): 6)
- EXC: 11 projects (file asks for builtin exception: 6; file asks for custom exception class: 5)
- FMT: 12 projects (file asks for f-string: 6; file asks for str.format: 6)
- GENERIC: 11 projects (file asks for list: 5; file asks for typing.List: 6)
- IMPORT: 11 projects (file asks for absolute import: 5; file asks for relative import: 6)
- LOG: 12 projects (file asks for logging: 6; file asks for print: 6)
- MONEY: 11 projects (file asks for Decimal: 5; file asks for integer cents: 6)
- NAME: 11 projects (file asks for camelCase: 5; file asks for snake_case: 6)
- OPT: 12 projects (file asks for X | None: 6; file asks for typing.Optional: 6)
- PATH: 12 projects (file asks for os.path: 6; file asks for pathlib: 6)
- REC: 11 projects (file asks for dataclass: 5; file asks for namedtuple: 6)
- TFILE: 11 projects (file asks for *_test.py: 6; file asks for test_*.py: 5)
- TSTYLE: 11 projects (file asks for pytest functions: 6; file asks for unittest classes: 5)
