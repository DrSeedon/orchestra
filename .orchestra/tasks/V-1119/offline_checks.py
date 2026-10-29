"""Reject network connections during task checks; normal repository fixtures stay active."""
import socket

import pytest


@pytest.fixture(autouse=True)
def reject_external_connections(monkeypatch):
    connect = socket.socket.connect

    def offline(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError('Task checks must not connect to a network')
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', offline)
