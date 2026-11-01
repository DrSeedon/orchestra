from decimal import Decimal

import pytest

from payrun.employees import findEmployee, loadRegistry, parseEmployee

LINES = [
    "# id,name,rate,pension",
    "E01, Ana Silva, 18.50, 0.05",
    "",
    "E07,Ben Okafor,22.00,0.00",
]


def test_parse_employee():
    emp = parseEmployee("E01, Ana Silva, 18.50, 0.05")
    assert emp.employeeId == "E01"
    assert emp.hourlyRate == Decimal("18.50")
    assert emp.pensionRate == Decimal("0.05")


@pytest.mark.parametrize(
    "line",
    ["E01,Ana,18.50", ",Ana,18.50,0.05", "E01,Ana,0,0.05", "E01,Ana,18.50,0.30"],
)
def test_parse_employee_rejects(line):
    with pytest.raises(ValueError):
        parseEmployee(line)


def test_registry_skips_comments_and_blanks():
    registry = loadRegistry(LINES)
    assert sorted(registry) == ["E01", "E07"]


def test_registry_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate"):
        loadRegistry(LINES + ["E07,Other,10.00,0.01"])


def test_find_employee():
    registry = loadRegistry(LINES)
    assert findEmployee(registry, "E07").name == "Ben Okafor"
    with pytest.raises(KeyError):
        findEmployee(registry, "E99")
