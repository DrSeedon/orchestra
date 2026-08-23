import pytest

from src.manifest import Endpoint, load_manifest


def test_load_manifest_returns_requested_endpoint_with_extra_metadata():
    manifest = '{"endpoint":{"host":"deploy.example","port":8443},"metadata":{"region":"test"}}'

    assert load_manifest(manifest) == Endpoint(host="deploy.example", port=8443)


@pytest.mark.parametrize("port", [0, 65536])
def test_load_manifest_rejects_out_of_range_port(port):
    manifest = f'{{"endpoint":{{"host":"deploy.example","port":{port}}}}}'

    with pytest.raises(ValueError):
        load_manifest(manifest)
