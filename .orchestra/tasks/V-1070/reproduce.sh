#!/bin/bash
set -eu
cd "$(dirname "$0")/../../.."
export PATH="$HOME/.local/share/orchestra/tools/uv/0.11.28/bin:$PATH"
task_dir="$PWD/.orchestra/tasks/V-1070"
mkdir -p "$task_dir/tmp"
export TMPDIR="$task_dir/tmp"
export PYTHONDONTWRITEBYTECODE=1
# collect.py needs public network access, but makes no model requests. Run it
# separately if refreshing sources is intended. The experiments below are offline.
uv run --frozen python -c 'import app; print("app:", app.__file__)'
uv pip install --python .venv/bin/python --target "$task_dir/deps" -r "$task_dir/requirements-research.txt"
nice -n 15 uv run --frozen python "$task_dir/experiment.py"
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 nice -n 15 uv run --frozen python "$task_dir/rapid_experiment.py"
uv run --frozen python "$task_dir/boundary_probe.py"
nice -n 15 uv run --frozen python -m pytest tests/test_harness_vision.py -q --basetemp="$task_dir/tmp/reproduce-pytest" -o cache_dir="$task_dir/tmp/reproduce-cache"
