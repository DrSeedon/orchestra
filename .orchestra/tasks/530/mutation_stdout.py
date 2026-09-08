"""Replay the removed stdout classifier in memory; never edit production files."""

import inspect
import textwrap

import pytest
from app import bg_jobs

source = textwrap.dedent(inspect.getsource(bg_jobs.BgJobManager._run_exec))
anchor = "validation_error = review_result_error(artifact)"
assert source.count(anchor) == 1
mutant = source.replace(
    anchor,
    'validation_error = "legacy stdout classifier" if "bwrap:" in full_output else review_result_error(artifact)',
)
namespace = dict(vars(bg_jobs))
exec(compile(mutant, "<530-stdout-mutation>", "exec"), namespace)
bg_jobs.BgJobManager._run_exec = namespace["_run_exec"]
raise SystemExit(pytest.main([
    "-q",
    "tests/test_bg_jobs.py::TestRunExecOutcome::test_t2_exit_zero_stdout_failure_phrase_is_not_rejected",
]))
