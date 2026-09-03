from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    key: str
    enabled: bool = True
    healthy: bool = True


class Gateway:
    def __init__(self, routes: list[Route], selected: str, active_connections: int):
        self.routes = routes
        self.selected = selected
        self.active_connections = active_connections

    def cards(self) -> list[dict]:
        return [
            {"key": route.key, "enabled": route.enabled, "healthy": route.healthy}
            for route in self.routes
        ]

    def switch(self, key: str) -> dict:
        route = next((route for route in self.routes if route.key == key), None)
        if route is None or not route.enabled or not route.healthy:
            return {"ok": False, "error": "route unavailable"}
        dropped = self.active_connections
        self.active_connections = 0
        self.selected = key
        return {"ok": True, "selected": key, "dropped_connections": dropped}


def default_gateway() -> Gateway:
    return Gateway(
        [
            Route("contabo"),
            Route("direct"),
            Route("hiddify", healthy=False),
        ],
        selected="contabo",
        active_connections=4,
    )

