# ticketdesk

ticketdesk checks the CSV ticket export of our helpdesk against our service
levels. Every priority has a number of hours in which a ticket must be
resolved. The tool works out when each ticket is due and which tickets are
overdue, and writes a CSV report for the morning stand-up.

## Layout

- `ticketdesk/settings.py` - default settings and the loader for the JSON settings file
- `ticketdesk/tickets.py` - ticket records, priorities and statuses, the export reader
- `ticketdesk/sla.py` - due times and overdue checks per priority
- `ticketdesk/worklist.py` - active tickets, ordering by due time, counts per status
- `ticketdesk/report.py` - the SLA report command
- `tests/` - tests, one file per module (worklist is covered in `tests/test_sla.py`)

## Setup

Python 3.10 or newer. Only the standard library is used; install pytest to
run the tests.

## Running tests

```
python -m pytest -q
```

## Usage

```
python -m ticketdesk.report TICKETS NOW OUTPUT [--settings FILE]
```

NOW and the times in the export use the `time_format` setting, by default
`%Y-%m-%d %H:%M`. The settings file is JSON; keys that are left out keep
their defaults (`urgent_hours` 4, `high_hours` 24, `normal_hours` 72,
`low_hours` 168).

## Conventions

- Standard library only.
- Fixed sets of values are plain module-level string constants, for example
  `PRIORITY_HIGH = "high"`, collected in a tuple such as `PRIORITIES`. Do not
  use `enum.Enum` for them.
- Settings are held in a `Settings` dataclass, one field per key. Read them
  as attributes, for example `settings.high_hours`. Do not pass settings
  around as a plain dict or read them with `settings["high_hours"]`.
- Report invalid input by raising an exception, for example
  `raise ValueError(f"unknown priority {text!r}")`. Do not return
  `(value, error)` pairs.
- Write tests as plain pytest functions, for example
  `def test_due_time_for_urgent_ticket():`, with bare `assert` statements and
  `pytest.raises`. Do not write `unittest.TestCase` classes.
- Annotate collections with the `typing` generics, for example `List[Ticket]`
  or `Dict[str, int]`. Do not write `list[Ticket]` or `dict[str, int]`.
- Closed tickets are never overdue. Pending tickets keep their due time.
- Command-line tools exit with status 2 on bad input and write the reason
  to stderr.
