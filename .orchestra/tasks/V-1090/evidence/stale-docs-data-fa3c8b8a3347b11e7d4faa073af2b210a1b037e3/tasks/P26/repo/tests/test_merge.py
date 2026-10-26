import logging

from mailmerge.merge import build_message, build_messages, missing_fields

BODY = "Dear {{name}}, see you in {{city}}.\n"


def test_missing_fields():
    assert missing_fields(BODY, ["email", "name"]) == ["city"]
    assert missing_fields(BODY, ["email", "name"], {"city": "Oslo"}) == []


def test_build_message():
    recipient = {"email": "ann@example.com", "name": "Ann", "city": "Oslo"}
    assert build_message("Hello {{name}}", BODY, recipient) == {
        "to": "ann@example.com",
        "subject": "Hello Ann",
        "body": "Dear Ann, see you in Oslo.\n",
    }


def test_build_messages_skips_recipients_with_missing_values(caplog):
    recipients = [
        {"email": "ann@example.com", "name": "Ann", "city": ""},
        {"email": "bo@example.com", "name": "", "city": "Rome"},
    ]
    with caplog.at_level(logging.INFO):
        messages = build_messages("Hi", BODY, recipients, {"city": "Oslo"})
    assert [m["to"] for m in messages] == ["ann@example.com"]
    assert messages[0]["body"] == "Dear Ann, see you in Oslo.\n"
    assert "bo@example.com: no value for field 'name', recipient skipped" in caplog.text
    assert "built 1 of 2 messages" in caplog.text
