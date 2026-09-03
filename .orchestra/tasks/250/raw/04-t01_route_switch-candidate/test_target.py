"""Focused regression tests for gateway route switching."""

from src.gateway import default_gateway


def test_switch_rejects_unavailable_route_without_changing_state():
    gateway = default_gateway()

    result = gateway.switch("hiddify")

    assert result == {"ok": False, "error": "route unavailable"}
    assert gateway.selected == "contabo"
    assert gateway.active_connections == 4


def test_switch_selects_healthy_route_and_drops_connections():
    gateway = default_gateway()

    result = gateway.switch("direct")

    assert result == {"ok": True, "selected": "direct", "dropped_connections": 4}
    assert gateway.selected == "direct"
    assert gateway.active_connections == 0
