import pytest

from mailmerge.__main__ import main, parse_defaults


def test_parse_defaults():
    assert parse_defaults(["City=Oslo", "name = friend"]) == {"city": "Oslo", "name": "friend"}
    with pytest.raises(ValueError, match="expected FIELD=VALUE"):
        parse_defaults(["city"])


def test_main_writes_outbox(write_file, tmp_path):
    template = write_file("t.txt", "Dear {{name}}, see you in {{city}}.\n")
    people = write_file("people.csv", "email,name,city\nann@example.com,Ann,\nbo@example.com,Bo,Rome\n")
    outbox = tmp_path / "outbox.txt"
    code = main([str(template), str(people), str(outbox), "--subject", "Hi {{name}}",
                 "--default", "city=Oslo"])
    assert code == 0
    text = outbox.read_text(encoding="utf-8")
    assert "To: ann@example.com\nSubject: Hi Ann\n\nDear Ann, see you in Oslo.\n" in text
    assert "Dear Bo, see you in Rome." in text


def test_main_missing_template(write_file, tmp_path):
    people = write_file("people.csv", "email\nann@example.com\n")
    code = main([str(tmp_path / "none.txt"), str(people), str(tmp_path / "outbox.txt")])
    assert code == 2
    assert not (tmp_path / "outbox.txt").exists()
