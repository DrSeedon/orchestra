# roomsched

roomsched keeps track of our meeting rooms. It reads the rooms file (name,
capacity and opening hours of each room) and the bookings file that the front
desk exports, and builds a day agenda for every room with its busy and free
slots. The front desk prints the agenda each morning.

## Layout

- `roomsched/clock.py` - parses and formats clock times and calendar days
- `roomsched/rooms.py` - loads the rooms file
- `roomsched/bookings.py` - loads bookings files, drops cancelled bookings, picks one room and day
- `roomsched/schedule.py` - checks time ranges and splits a room's day into busy and free slots
- `roomsched/agenda.py` - the agenda command: builds and writes the agenda of all rooms for one day
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
python -m roomsched.agenda ROOMS_CSV BOOKINGS_CSV DAY OUTPUT_CSV
```

The rooms file has the header `name,capacity,opens,closes`; the bookings file
has `id,room,date,start,end,attendees,status`, where status is `confirmed`,
`tentative` or `cancelled`. Times are `HH:MM` and days are `YYYY-MM-DD`. The
command writes one row per slot with the columns `room,start,end,slot,booking`
and exits with status 2 when an input file is invalid.

## Conventions

- Model fixed sets of values, such as booking statuses and slot kinds, as
  `Enum` classes, for example `class Status(Enum): CONFIRMED = "confirmed"`.
  Compare against members, never against bare strings.
- Signal invalid input by raising an exception, for example
  `raise ValueError(f"unknown room {name!r}")`. Functions return only their
  result; do not return `(result, error)` pairs. The command's `main()`
  catches the error, reports it on stderr and returns 2.
- Name functions and methods in camelCase: `def loadRooms(path):`,
  `def activeBookings(bookings):`. Classes use CapWords.
- Write docstrings in Google style, with `Args:`, `Returns:` and `Raises:`
  sections.
- Standard library only. pytest is the only development dependency.
- Inside the package, times are minutes after midnight (`int`) and days are
  ISO strings (`"2026-03-02"`). Convert at the edges with `roomsched/clock.py`.
- Type hints on public functions use built-in generics and `X | None`.
- Tests are plain pytest functions in `tests/test_<module>.py`. They write
  files only under pytest's `tmp_path`.
