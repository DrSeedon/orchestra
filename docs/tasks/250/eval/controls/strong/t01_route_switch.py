from src.gateway import default_gateway


def test_switch_outcomes_and_route_collection_are_alive():
    gateway = default_gateway()
    keys = {card["key"] for card in gateway.cards()}
    assert {"contabo", "direct", "hiddify"} <= keys

    refused = gateway.switch("hiddify")
    assert refused == {"ok": False, "error": "route unavailable"}
    assert gateway.selected == "contabo"
    assert gateway.active_connections == 4

    switched = gateway.switch("direct")
    assert switched == {"ok": True, "selected": "direct", "dropped_connections": 4}
    assert gateway.selected == "direct"
    assert gateway.active_connections == 0

