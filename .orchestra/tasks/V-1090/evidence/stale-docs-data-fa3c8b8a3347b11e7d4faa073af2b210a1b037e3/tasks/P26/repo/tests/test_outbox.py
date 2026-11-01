import pytest

from mailmerge.outbox import SEPARATOR, message_text, write_outbox

MESSAGES = [
    {"to": "ann@example.com", "subject": "Hi Ann", "body": "Line one\n\n"},
    {"to": "bo@example.com", "subject": "Hi Bo", "body": "Line two"},
]


def test_message_text():
    assert message_text(MESSAGES[0]) == "To: ann@example.com\nSubject: Hi Ann\n\nLine one\n"


def test_write_outbox_creates_folder(tmp_path):
    target = write_outbox(MESSAGES, tmp_path / "out" / "outbox.txt")
    assert target == tmp_path / "out" / "outbox.txt"
    text = target.read_text(encoding="utf-8")
    assert text.split(SEPARATOR + "\n") == [
        "To: ann@example.com\nSubject: Hi Ann\n\nLine one\n",
        "To: bo@example.com\nSubject: Hi Bo\n\nLine two\n",
    ]


def test_write_outbox_rejects_empty_list(tmp_path):
    with pytest.raises(ValueError):
        write_outbox([], tmp_path / "outbox.txt")
