import pytest
from app.task_refs import TaskRef, parse_task_ref


@pytest.mark.parametrize('text,origin,number,display', [
    ('123', '', 123, '#123'), ('#123', '', 123, '#123'),
    ('V-123', 'V', 123, 'V-123'), ('#V-123', 'V', 123, 'V-123'),
])
def test_task_reference_keeps_origin(text, origin, number, display):
    ref = parse_task_ref(text)
    assert ref == TaskRef(origin, number)
    assert ref.display == display
    assert parse_task_ref(ref.key) == ref


@pytest.mark.parametrize('text', ['0', 'V-0', '-1', 'V--1', 'other-12', '../12', '', 'V-1 extra'])
def test_invalid_task_reference_is_rejected(text):
    with pytest.raises(ValueError):
        parse_task_ref(text)
