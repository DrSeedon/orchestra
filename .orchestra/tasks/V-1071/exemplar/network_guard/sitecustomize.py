"""Fail closed on Python network access in the research's offline subprocesses."""
import socket


def denied(*args, **kwargs):
    raise RuntimeError("V-1071 offline run: network access denied")


socket.create_connection = denied
socket.getaddrinfo = denied
socket.socket.connect = denied
socket.socket.connect_ex = denied
