"""Public task names: retain local numbers, namespace new VPS tasks with V-."""
import os


def new_task_prefix() -> str:
    prefix = os.environ.get('ORCHESTRA_TASK_PREFIX', '').strip().upper().removesuffix('-')
    if prefix not in {'', 'V'}:
        raise ValueError('ORCHESTRA_TASK_PREFIX must be empty or V-')
    return prefix


def task_ref(task: dict) -> str:
    prefix = str(task['ref_prefix'] or '') if 'ref_prefix' in task.keys() else ''
    number = str(task['par_number'])
    return f'{prefix}-{number}' if prefix else number
