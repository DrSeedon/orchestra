from envcheck.rules import check_values, is_bool, is_int, is_url

SCHEMA = {
    "DATABASE_URL": {"type": "url", "required": True},
    "PORT": {"type": "int", "required": True},
    "DEBUG": {"type": "bool", "required": False},
    "APP_NAME": {"type": "str", "required": True},
}


def test_type_checks():
    assert is_int("8080") and is_int("-1") and not is_int("80a") and not is_int("")
    assert is_bool("Yes") and is_bool("off") and not is_bool("maybe")
    assert is_url("postgres://db/app") and not is_url("db/app")


def test_check_values_finds_missing_and_invalid():
    values = {"DATABASE_URL": "postgres://db/app", "PORT": "80a", "DEBUG": "maybe", "EXTRA": "1"}
    result = check_values(values, SCHEMA, {"allow_empty": False})
    assert result == {"missing": ["APP_NAME"], "invalid": ["DEBUG", "PORT"]}


def test_empty_values_depend_on_allow_empty():
    values = {"DATABASE_URL": "postgres://db/app", "PORT": "1", "APP_NAME": "", "DEBUG": ""}
    assert check_values(values, SCHEMA, {"allow_empty": False}) == {"missing": ["APP_NAME"], "invalid": []}
    assert check_values(values, SCHEMA, {"allow_empty": True}) == {"missing": [], "invalid": []}
