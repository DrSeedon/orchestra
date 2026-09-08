"""Portable task references; origin belongs to the task, not its current host."""
from dataclasses import dataclass
import re
import os
import hashlib


@dataclass(frozen=True)
class TaskRef:
    origin: str
    number: int

    def __post_init__(self):
        if self.origin not in {'', 'V'}:
            raise ValueError('task origin must be empty or V')
        if type(self.number) is not int or not 0 < self.number < 2**63:
            raise ValueError('task number must be a positive SQLite integer')

    @property
    def key(self) -> str:
        return f'V-{self.number}' if self.origin else str(self.number)

    @property
    def display(self) -> str:
        return self.key if self.origin else f'#{self.number}'


def parse_task_ref(value: str) -> TaskRef:
    match = re.fullmatch(r'#?(?:(V)-)?([0-9]+)', str(value).strip().upper())
    if not match:
        raise ValueError(f'invalid task reference: {value!r}')
    return TaskRef(match.group(1) or '', int(match.group(2)))


def new_task_prefix() -> str:
    prefix = os.environ.get('ORCHESTRA_TASK_PREFIX', '').strip().upper().removesuffix('-')
    if prefix not in {'', 'V'}:
        raise ValueError('ORCHESTRA_TASK_PREFIX must be empty or V-')
    return prefix


def task_ref(task: dict) -> str:
    prefix = str(task['ref_prefix'] or '') if 'ref_prefix' in task.keys() else ''
    number = str(task['par_number'])
    return f'{prefix}-{number}' if prefix else number


def project_key(value: str) -> str:
    if re.fullmatch(r'[a-z0-9][a-z0-9._-]*', value):
        return value
    base = re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')
    if not base or len(base) > 48:
        base = 'project'
    return f'{base}-{hashlib.sha256(value.encode()).hexdigest()[:12]}'
