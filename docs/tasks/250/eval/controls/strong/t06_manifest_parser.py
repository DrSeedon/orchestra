import pytest

from src.manifest import load_manifest


def test_manifest_exposes_endpoint_semantics_and_rejects_bad_port():
    endpoint = load_manifest('{"endpoint":{"host":"db.internal","port":5432}}')
    assert endpoint.host == "db.internal"
    assert endpoint.port == 5432

    with pytest.raises(ValueError, match="invalid endpoint"):
        load_manifest('{"endpoint":{"host":"db.internal","port":70000}}')

