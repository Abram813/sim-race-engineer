from __future__ import annotations

import ipaddress
import os
import socket

import pytest


class NetworkBlocked(RuntimeError):
    """Raised when a test tries to reach a non-loopback address."""


def _is_loopback(host: str | None) -> bool:
    if host in (None, "", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    """Make the offline guarantee testable.

    Loopback is allowed because the app's own server binds to 127.0.0.1.
    Everything else raises before DNS or a TCP handshake happens.
    """
    monkeypatch.setenv("RACECOACH_OFFLINE", "1")
    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        if self.family in (socket.AF_INET, socket.AF_INET6):
            host = address[0]
            if not _is_loopback(host):
                raise NetworkBlocked(f"external connection blocked: {address!r}")
        return real_connect(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        if not _is_loopback(address[0]):
            raise NetworkBlocked(f"external connection blocked: {address!r}")
        return real_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in (None, "") and not _is_loopback(host):
            raise NetworkBlocked(f"external DNS blocked: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    yield


@pytest.fixture
def demo_csvs():
    from racecoach.demo import demo_csv_texts

    return demo_csv_texts()


@pytest.fixture
def demo_files(tmp_path):
    from racecoach.demo import export_demo

    return export_demo(tmp_path / "demo laps")
