from envcheck.check import main

SCHEMA = "DATABASE_URL url\nPORT int\nDEBUG bool optional\n"


def make_files(tmp_path, env_text):
    (tmp_path / "app.schema").write_text(SCHEMA, encoding="utf-8")
    settings = tmp_path / "envcheck.ini"
    settings.write_text("[envcheck]\nschema = app.schema\n", encoding="utf-8")
    env = tmp_path / "app.env"
    env.write_text(env_text, encoding="utf-8")
    return str(settings), str(env)


def test_check_passes(tmp_path, capsys):
    settings, env = make_files(tmp_path, "DATABASE_URL=postgres://db/app\nPORT=5432\n")
    assert main([settings, env]) == 0
    assert capsys.readouterr().out == "ok\n"


def test_check_reports_problems(tmp_path, capsys):
    settings, env = make_files(tmp_path, "PORT=5432x\nDEBUG=yes\n")
    assert main([settings, env]) == 1
    assert capsys.readouterr().out.splitlines() == ["missing: DATABASE_URL", "invalid: PORT"]


def test_check_rejects_a_bad_env_file(tmp_path, capsys):
    settings, env = make_files(tmp_path, "PORT 5432\n")
    assert main([settings, env]) == 2
    assert "app.env: line 1" in capsys.readouterr().err
