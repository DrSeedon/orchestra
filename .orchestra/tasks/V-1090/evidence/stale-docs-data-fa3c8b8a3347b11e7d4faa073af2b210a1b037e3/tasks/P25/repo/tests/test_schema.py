import pytest

from envcheck.errors import SchemaError
from envcheck.schema import load_schema


def write(tmp_path, text):
    path = tmp_path / "app.schema"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_schema(tmp_path):
    path = write(tmp_path, "# app\nPORT int\nDEBUG bool optional  # dev only\n\nAPP_NAME str required\n")
    assert load_schema(path) == {
        "PORT": {"type": "int", "required": True},
        "DEBUG": {"type": "bool", "required": False},
        "APP_NAME": {"type": "str", "required": True},
    }


@pytest.mark.parametrize("line", ["PORT", "PORT number", "PORT int maybe", "PORT int required extra"])
def test_load_schema_rejects_bad_lines(tmp_path, line):
    path = write(tmp_path, "APP_NAME str\n" + line + "\n")
    with pytest.raises(SchemaError, match="app.schema:2:"):
        load_schema(path)


def test_load_schema_rejects_a_repeated_name(tmp_path):
    path = write(tmp_path, "PORT int\nPORT str\n")
    with pytest.raises(SchemaError, match="twice"):
        load_schema(path)
