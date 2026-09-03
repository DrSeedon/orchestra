import pytest

from src.manifest import Endpoint, load_manifest


def test_load_manifest_returns_endpoint_and_ignores_extra_metadata():
    assert load_manifest(
        '{"endpoint":{"host":"api.example","port":8443},"name":"api"}'
    ) == Endpoint(host="api.example", port=8443)


@pytest.mark.parametrize("port", [0, 65536])
def test_load_manifest_rejects_out_of_range_port(port):
    with pytest.raises(ValueError):
        load_manifest(f'{{"endpoint":{{"host":"api.example","port":{port}}}}}')
