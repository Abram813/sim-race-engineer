from __future__ import annotations

import socket

import pytest

from conftest import NetworkBlocked


def test_external_network_is_blocked():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80), timeout=0.1)


def test_external_dns_is_blocked():
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("example.com", 443)
