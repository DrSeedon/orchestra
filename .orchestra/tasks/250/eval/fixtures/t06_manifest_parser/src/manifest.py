import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int


def load_manifest(text: str) -> Endpoint:
    payload = json.loads(text)
    endpoint = payload["endpoint"]
    host = str(endpoint["host"])
    port = int(endpoint["port"])
    if not host or not 1 <= port <= 65535:
        raise ValueError("invalid endpoint")
    return Endpoint(host=host, port=port)


def example_manifest() -> str:
    return '{"endpoint":{"host":"api.example","port":443}}'

