# flagstore

flagstore is the feature-flag service behind our web apps. It keeps flag
definitions in memory, answers "is this flag on for this user?" with stable
percentage rollouts, and records when each flag was last evaluated. Settings
come from built-in defaults, and any of them can be overridden in a JSON
settings file.

## Layout

- `flagstore/settings.py` - settings defaults and loading overrides from JSON
- `flagstore/flags.py` - flag records and conversion to and from JSON objects
- `flagstore/store.py` - the in-memory store, evaluation times, flag files
- `flagstore/evaluate.py` - flag evaluation and rollout bucketing
- `tests/` - pytest tests, one module per source module

## Setup

Python 3.10 or newer. There is nothing to install apart from pytest.

## Running tests

```
python -m pytest -q
```

Run the command from the repository root.

## Conventions

- Settings are typed fields, each with a default, on the `Settings` dataclass
  in `flagstore/settings.py`. Code reads a setting as an attribute
  (`settings.max_flags`), never by string key. A new setting is a new field.
- A fixed set of values (flag states, groups, kinds) is an `enum.Enum`
  subclass, e.g. `class FlagState(str, Enum)`. Compare against members, not
  raw strings.
- Write optional types as `Optional[X]` from `typing`, e.g.
  `def last_evaluated(self, name: str) -> Optional[datetime]`.
- Every public function and method has a reST docstring with field lists:
  `:param name:`, `:returns:` and `:raises ValueError:` where relevant.
- All functions are fully type-annotated.
- Times are timezone-aware UTC `datetime` values.
- Standard library only.
- Tests must not touch the network. They write files only under pytest's
  `tmp_path`.
