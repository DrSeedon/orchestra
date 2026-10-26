from hostsfile.cli import main


def make_hosts(tmp_path):
    path = tmp_path / "hosts"
    path.write_text("127.0.0.1 localhost\n10.0.0.5 build\n", encoding="utf-8")
    return path


def test_show_lists_entries(tmp_path, capsys):
    path = make_hosts(tmp_path)
    assert main(["show", str(path), "BUILD"]) == 0
    assert capsys.readouterr().out == "2: 10.0.0.5\n"


def test_show_unknown_name(tmp_path):
    assert main(["show", str(make_hosts(tmp_path)), "web"]) == 1


def test_add_writes_file(tmp_path):
    path = make_hosts(tmp_path)
    assert main(["add", str(path), "10.0.0.6", "web", "--comment", "web box"]) == 0
    assert path.read_text(encoding="utf-8").splitlines()[-1] == "10.0.0.6        web  # web box"


def test_remove_writes_file(tmp_path):
    path = make_hosts(tmp_path)
    assert main(["remove", str(path), "build"]) == 0
    assert path.read_text(encoding="utf-8") == "127.0.0.1       localhost\n"


def test_bad_request_exits_2(tmp_path, capsys):
    path = make_hosts(tmp_path)
    assert main(["add", str(path), "10.0.0.300", "web"]) == 2
    assert "not an IP address" in capsys.readouterr().err


def test_missing_file_exits_2(tmp_path):
    assert main(["show", str(tmp_path / "nope"), "web"]) == 2
