import pytest

from habitlog.targets import Target, load_targets, parse_target


def test_parse_target():
    assert parse_target(" Evening Walk ", " 3") == Target("evening walk", 3)


@pytest.mark.parametrize("per_week", ["0", "8", "2.5", "", "x"])
def test_parse_target_invalid_count(per_week):
    with pytest.raises(ValueError, match="from 1 to 7"):
        parse_target("run", per_week)


def test_load_targets(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("habit,per_week\nrun,3\nRead,5\n", encoding="utf-8")
    assert load_targets(str(path)) == [Target("read", 5), Target("run", 3)]


def test_load_targets_missing_column(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("habit,times\nrun,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected the columns habit,per_week"):
        load_targets(str(path))


def test_load_targets_twice(tmp_path):
    path = tmp_path / "targets.csv"
    path.write_text("habit,per_week\nrun,3\nRun,4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="targets.csv:3: habit 'run' is listed twice"):
        load_targets(str(path))
