import pytest

from envcheck.envfile import parse_line, read_env_file
from envcheck.errors import EnvParseError


def test_parse_line_handles_comments_export_and_quotes():
    assert parse_line("# comment", 1) is None
    assert parse_line("   ", 2) is None
    assert parse_line("PORT=8080", 3) == ("PORT", "8080")
    assert parse_line("export NAME = shop ", 4) == ("NAME", "shop")
    assert parse_line('URL="postgres://db/app"', 5) == ("URL", "postgres://db/app")
    assert parse_line("GREETING='hi # there'", 6) == ("GREETING", "hi # there")
    assert parse_line("DEBUG=yes # for now", 7) == ("DEBUG", "yes")
    assert parse_line("EMPTY=", 8) == ("EMPTY", "")


@pytest.mark.parametrize("line", ["no equals sign", "1PORT=80", "=value"])
def test_parse_line_rejects_bad_lines(line):
    with pytest.raises(EnvParseError, match="line 3"):
        parse_line(line, 3)


def test_read_env_file_keeps_the_last_value(tmp_path):
    path = tmp_path / "app.env"
    path.write_text("A=1\n\n# note\nB=2\nA=3\n", encoding="utf-8")
    assert read_env_file(str(path)) == {"A": "3", "B": "2"}


def test_read_env_file_names_the_file(tmp_path):
    path = tmp_path / "bad.env"
    path.write_text("A=1\noops\n", encoding="utf-8")
    with pytest.raises(EnvParseError, match="bad.env: line 2"):
        read_env_file(str(path))
