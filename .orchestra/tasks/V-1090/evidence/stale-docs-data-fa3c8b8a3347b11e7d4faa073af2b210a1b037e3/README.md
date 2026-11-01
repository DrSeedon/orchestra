# Stale instruction files: data

Data and analysis scripts for the paper "Stale Instruction Files Override the Code in Coding Agents: A One-Sentence Fix".

- `tasks/`: the 40 projects, each with its code (`repo/`), instruction file (`instructions.md`), feature request and choices to judge (`task.json`) and feature test (`heldout/`).
- `conditions/`: the user-level instruction file in each condition (empty, or the sentence).
- `criteria/`: the criterion for judging whether a final reply reports a conflict.
- `runs.jsonl`: one record per run.
- `scripts/`: the choice judge (`judge.py`), the test check (`score.py`, `common.py`) and the analysis (`analysis.py`, `more_numbers.py`).
- `numbers.md`, `more_numbers.md`: the numbers reported in the paper.

## Recompute

    pip install numpy tiktoken
    python scripts/analysis.py numbers
    python scripts/more_numbers.py
    python scripts/analysis.py rejudge
