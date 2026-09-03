import json

from src.manifest import example_manifest


def test_example_shape_today():
    assert json.loads(example_manifest()) == {
        "endpoint": {"host": "api.example", "port": 443}
    }

