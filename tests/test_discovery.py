import asyncio
import hashlib
import socket
from typing import Any

import pytest

from tg_mcp.access import AgentAccessStore
from tg_mcp.config import Settings
from tg_mcp.discovery import (
    DiscoveryResponder,
    discover_services,
    discovery_responder,
    make_discovery_request,
    parse_discovery_response,
    token_digest,
    validate_endpoint,
)
from tg_mcp.storage import StateStore


class DatagramCapture:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((data, addr))


def responder(
    token: str, endpoint: str = "https://telegram.example/mcp"
) -> tuple[Any, DatagramCapture]:
    protocol = DiscoveryResponder(
        token_digests=lambda: (token_digest(token),),
        endpoint=endpoint,
        http_port=8000,
    )
    transport = DatagramCapture()
    protocol.transport = transport  # type: ignore[assignment]
    return protocol, transport


def test_discovery_response_is_authenticated() -> None:
    token = "x" * 43
    request, nonce = make_discovery_request(token, "a" * 24)
    protocol, transport = responder(token)

    protocol.datagram_received(request, ("192.168.1.20", 49000))

    assert len(transport.sent) == 1
    response, destination = transport.sent[0]
    assert destination == ("192.168.1.20", 49000)
    assert parse_discovery_response(response, token, nonce) == "https://telegram.example/mcp"
    assert parse_discovery_response(response, "y" * 43, nonce) is None


def test_discovery_does_not_answer_invalid_proof_or_public_peer() -> None:
    protocol, transport = responder("x" * 43)
    wrong_request, _ = make_discovery_request("y" * 43, "a" * 24)
    valid_request, _ = make_discovery_request("x" * 43, "b" * 24)

    protocol.datagram_received(wrong_request, ("192.168.1.20", 49000))
    protocol.datagram_received(valid_request, ("8.8.8.8", 49000))

    assert transport.sent == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://8.8.8.8:8000/mcp",
        "http://example.com/mcp",
        "https://example.com/not-mcp",
        "https://user:password@example.com/mcp",
        "file:///tmp/mcp",
    ],
)
def test_discovery_rejects_unsafe_endpoints(endpoint: str) -> None:
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_settings_enable_discovery_for_lan_bind(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TG_MCP_BIND", "0.0.0.0")
    monkeypatch.setenv("TG_MCP_PORT", "8765")
    monkeypatch.setattr("tg_mcp.config.local_ipv4_addresses", lambda: ["192.168.1.10"])

    settings = Settings.from_env(tmp_path)

    assert settings.discovery_enabled
    assert "192.168.1.10:8765" in settings.allowed_hosts


def test_settings_enable_loopback_discovery_by_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tg_mcp.config.local_ipv4_addresses", list)

    settings = Settings.from_env(tmp_path)

    assert settings.discovery_enabled


def test_scoped_agent_digest_can_authenticate_discovery(tmp_path) -> None:
    store = StateStore(tmp_path / "private")
    access = AgentAccessStore(store)
    created = access.create("Codex", ["read"], None, None)

    assert access.enabled_token_digests() == (
        hashlib.sha256(created["token"].encode("ascii")).digest(),
    )
    access.revoke(created["agent_id"])
    assert access.enabled_token_digests() == ()


def test_discovery_responder_context_can_be_disabled() -> None:
    async def run() -> None:
        async with discovery_responder(
            enabled=False,
            udp_port=38475,
            endpoint=None,
            http_port=8000,
            token_digests=tuple,
        ):
            pass

    asyncio.run(run())


def test_discovery_responder_answers_authenticated_local_datagram() -> None:
    token = "x" * 43

    def exchange(port: int) -> bytes:
        request, _ = make_discovery_request(token, "a" * 24)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(2)
            sock.sendto(request, ("127.0.0.1", port))
            return sock.recv(1024)
        finally:
            sock.close()

    async def run() -> None:
        async with discovery_responder(
            enabled=True,
            udp_port=0,
            endpoint="https://telegram.example/mcp",
            http_port=8000,
            token_digests=lambda: (token_digest(token),),
        ) as port:
            assert port is not None
            response = await asyncio.to_thread(exchange, port)
            assert (
                parse_discovery_response(response, token, "a" * 24)
                == "https://telegram.example/mcp"
            )

    asyncio.run(run())


def test_client_discovers_authenticated_loopback_responder() -> None:
    token = "x" * 43

    async def run() -> None:
        async with discovery_responder(
            enabled=True,
            udp_port=0,
            endpoint="https://telegram.example/mcp",
            http_port=8000,
            token_digests=lambda: (token_digest(token),),
        ) as port:
            assert port is not None
            assert await discover_services(token, port, deadline_seconds=0.1) == [
                "https://telegram.example/mcp"
            ]
            assert await discover_services("y" * 43, port, deadline_seconds=0.1) == []

    asyncio.run(run())
