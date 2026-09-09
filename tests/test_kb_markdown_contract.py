from pathlib import Path

from scripts.check_kb_contract import check


def test_plain_multiline_notes_and_arbitrary_headings_are_allowed(tmp_path):
    (tmp_path / 'topic.md').write_text(
        '# Тема\n\n## Когда возникает ошибка\n\n'
        'Можно заменить прежний вывод новым.\nПродолжение на следующей строке.\n'
        'Нет обязательных статусов, ключей, квитанций или источника в той же строке.\n'
    )
    assert check(tmp_path) == []


def test_missing_source_is_reported_with_file_and_line(tmp_path):
    (tmp_path / 'topic.md').write_text('# Тема\n[Проверка](missing.md)\n')
    errors = check(tmp_path)
    assert len(errors) == 1
    assert 'topic.md:2:' in errors[0] and 'missing.md' in errors[0]


def test_relative_and_encoded_links_can_point_to_task_evidence(tmp_path):
    kb = tmp_path / 'kb'
    kb.mkdir()
    (tmp_path / 'task report.md').write_text('evidence')
    (kb / 'topic.md').write_text(
        '[source](../task%20report.md#result)\n'
        '[source](<../task report.md>)\n'
    )
    assert check(kb) == []


def test_examples_and_external_links_are_not_local_file_claims(tmp_path):
    (tmp_path / 'topic.md').write_text(
        '[site](https://example.test/never-fetched)\n[section](#heading)\n'
        '`[example](missing.md)`\n```markdown\n[example](missing.md)\n```\n'
    )
    assert check(tmp_path) == []


def test_nonexistent_kb_does_not_pass_silently(tmp_path):
    assert check(tmp_path / 'missing')


def test_repository_kb_links_open():
    assert check(Path(__file__).resolve().parents[1] / '.orchestra/kb') == []
