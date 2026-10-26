# jobqueue

jobqueue is a small job queue used by our batch scripts. Callers submit named
jobs with a payload, a worker runs them with registered handler functions, and
failed jobs are retried until they run out of attempts. Every job moves through
a fixed set of states with checked transitions. Between runs the scripts keep
the queue in a JSON file.

## Layout

- `jobqueue/states.py` - job states and allowed transitions
- `jobqueue/queue.py` - the `Job` record and the in-memory `JobQueue`
- `jobqueue/worker.py` - running jobs with handler functions
- `jobqueue/storage.py` - saving a queue to a JSON file and loading it back
- `tests/` - one test module per source module

A queue file holds the jobs in submission order:

```
{"jobs": [{"id": "job-1", "name": "email", "state": "pending", "deadline": null, ...}]}
```

## Setup

Python 3.10 or newer. Install pytest to run the tests; the package itself
needs only the standard library.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root. pytest is the test runner.

## Conventions

- A fixed set of string values is a group of module-level string constants
  with a common prefix, plus a tuple of all valid values, e.g.
  `STATE_PENDING = "pending"` and `ALL_STATES = (STATE_PENDING, ...)`.
  Do not use `enum`.
- Raise the package's own exception classes, all derived from one
  `JobQueueError` base class, e.g. `raise JobNotFoundError(job_id)`. Do not
  raise bare `ValueError`, `KeyError` or `RuntimeError` from the package.
- Annotate values that may be missing as `X | None`, e.g.
  `deadline: float | None = None`. Do not use `typing.Optional`.
- Tests are `unittest.TestCase` classes that use the `self.assert*` methods
  (`assertEqual`, `assertIsNone`, `assertRaises`).
- The queue is single-threaded; do not add locks or threads.
- Times are `time.time()` floats in seconds.
- Every public function and method has a one-line docstring.
- Standard library only.
