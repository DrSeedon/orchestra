from datetime import date

import pytest

from rentroll.tenants import Tenant, load_tenants, tenants_by_unit


def test_load_tenants_keeps_file_order(sample_files):
    tenants_path, _ = sample_files
    tenants = load_tenants(tenants_path)
    assert [tenant.unit for tenant in tenants] == ["2A", "1A", "1B"]
    assert tenants[1] == Tenant(unit="1A", name="Ana Ruiz", rent=125050, since=date(2024, 3, 1))
    assert tenants[2].rent == 98000


def test_tenants_by_unit(sample_files):
    tenants = load_tenants(sample_files[0])
    assert tenants_by_unit(tenants)["1B"].name == "Ben Cole"


def test_missing_column(write_file):
    path = write_file("t.csv", "unit,name,rent\n1A,Ana,100\n")
    with pytest.raises(ValueError, match="missing columns since"):
        load_tenants(path)


def test_repeated_unit(write_file):
    path = write_file("t.csv", "unit,name,rent,since\n1A,Ana,100,2024-01-01\n1A,Bo,90,2024-01-01\n")
    with pytest.raises(ValueError, match="line 3: unit 1A is listed twice"):
        load_tenants(path)


@pytest.mark.parametrize("row", ["1A,Ana,abc,2024-01-01", "1A,Ana,0,2024-01-01", "1A,Ana,100,soon"])
def test_bad_rows(write_file, row):
    path = write_file("t.csv", "unit,name,rent,since\n" + row + "\n")
    with pytest.raises(ValueError, match="line 2"):
        load_tenants(path)
