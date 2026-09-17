"""Authenticated local-network discovery for TG Account MCP endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

DISCOVERY_PORT = 38475
DISCOVERY_PROTOCOL = "tg-account-mcp"
DISCOVERY_VERSION = 1
MAX_DATAGRAM_SIZE = 1024


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def _proof(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _request_value(nonce: str) -> str:
    return f"discover:{DISCOVERY_VERSION}:{nonce}"


def _response_value(nonce: str, endpoint: str) -> str:
    return f"endpoint:{DISCOVERY_VERSION}:{nonce}:{endpoint}"


def make_discovery_request(token: str, nonce: str | None = None) -> tuple[bytes, str]:
    request_nonce = nonce or secrets.token_urlsafe(18)
    payload = {
        "protocol": DISCOVERY_PROTOCOL,
        "version": DISCOVERY_VERSION,
        "nonce": request_nonce,
        "proof": _proof(token_digest(token), _request_value(request_nonce)),
    }
    return json.dumps(payload, separators=(",", ":")).encode("ascii"), request_nonce


def parse_discovery_response(data: bytes, token: str, nonce: str) -> str | None:
    if len(data) > MAX_DATAGRAM_SIZE:
        return None
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or (
        payload.get("protocol") != DISCOVERY_PROTOCOL
        or payload.get("version") != DISCOVERY_VERSION
        or payload.get("nonce") != nonce
    ):
        return None
    endpoint = payload.get("endpoint")
    proof = payload.get("proof")
    if not isinstance(endpoint, str) or not isinstance(proof, str):
        return None
    expected = _proof(token_digest(token), _response_value(nonce, endpoint))
    if not hmac.compare_digest(proof, expected):
        return None
    try:
        return validate_endpoint(endpoint)
    except ValueError:
        return None


def validate_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/mcp"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Discovery endpoint must be an HTTP(S) /mcp URL")
    if parsed.scheme == "http":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            if parsed.hostname not in {"localhost", "localhost.localdomain"}:
                raise ValueError("Plain HTTP discovery endpoints must be local addresses") from None
        else:
            if not (address.is_private or address.is_loopback or address.is_link_local):
                raise ValueError("Plain HTTP discovery endpoints must be local addresses")
    return endpoint


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = result[4][0]
            if not ipaddress.ip_address(address).is_loopback:
                addresses.add(address)
    except OSError:
        pass
    for target in (("192.0.2.1", 9), ("198.51.100.1", 9)):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(target)
            address = probe.getsockname()[0]
            if not ipaddress.ip_address(address).is_loopback:
                addresses.add(address)
        except OSError:
            pass
        finally:
            probe.close()
    return sorted(addresses)


def _route_address(peer: str) -> str | None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((peer, 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


class DiscoveryResponder(asyncio.DatagramProtocol):
    def __init__(
        self,
        *,
        token_digests: Callable[[], Iterable[bytes]],
        endpoint: str | None,
        http_port: int,
    ):
        self.token_digests = token_digests
        self.endpoint = endpoint
        self.http_port = http_port
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        if isinstance(transport, asyncio.DatagramTransport):
            self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.transport is None or len(data) > MAX_DATAGRAM_SIZE:
            return
        try:
            peer = ipaddress.ip_address(addr[0])
        except ValueError:
            return
        if not (peer.is_private or peer.is_loopback or peer.is_link_local):
            return
        try:
            payload = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or (
            payload.get("protocol") != DISCOVERY_PROTOCOL
            or payload.get("version") != DISCOVERY_VERSION
        ):
            return
        nonce = payload.get("nonce")
        supplied_proof = payload.get("proof")
        if not isinstance(nonce, str) or not isinstance(supplied_proof, str):
            return
        if not 16 <= len(nonce) <= 64 or any(
            not (char.isalnum() or char in "-_") for char in nonce
        ):
            return
        matched_key = next(
            (
                key
                for key in self.token_digests()
                if hmac.compare_digest(_proof(key, _request_value(nonce)), supplied_proof)
            ),
            None,
        )
        if matched_key is None:
            return
        endpoint = self.endpoint
        if endpoint is None:
            host = _route_address(addr[0])
            if host is None:
                return
            endpoint = f"http://{host}:{self.http_port}/mcp"
        response = {
            "protocol": DISCOVERY_PROTOCOL,
            "version": DISCOVERY_VERSION,
            "nonce": nonce,
            "endpoint": endpoint,
            "proof": _proof(matched_key, _response_value(nonce, endpoint)),
        }
        encoded = json.dumps(response, separators=(",", ":")).encode("ascii")
        if len(encoded) <= MAX_DATAGRAM_SIZE:
            self.transport.sendto(encoded, addr)


@asynccontextmanager
async def discovery_responder(
    *,
    enabled: bool,
    udp_port: int,
    endpoint: str | None,
    http_port: int,
    token_digests: Callable[[], Iterable[bytes]],
):
    if not enabled:
        yield None
        return
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: DiscoveryResponder(
            token_digests=token_digests,
            endpoint=endpoint,
            http_port=http_port,
        ),
        local_addr=("0.0.0.0", udp_port),
        allow_broadcast=True,
    )
    try:
        sockname = transport.get_extra_info("sockname")
        yield sockname[1]
    finally:
        transport.close()


def _discover_sync(token: str, udp_port: int, timeout: float) -> list[str]:
    request, nonce = make_discovery_request(token)
    endpoints: set[str] = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        sock.settimeout(timeout)
        # Loopback finds a default local installation without exposing the bearer token.
        # Broadcast covers services on the current subnet using the same authenticated request.
        sent = False
        for destination in ("127.0.0.1", "255.255.255.255"):
            try:
                sock.sendto(request, (destination, udp_port))
                sent = True
            except OSError:
                continue
        if not sent:
            return []
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, _ = sock.recvfrom(MAX_DATAGRAM_SIZE + 1)
            except TimeoutError:
                break
            endpoint = parse_discovery_response(data, token, nonce)
            if endpoint is not None:
                endpoints.add(endpoint)
    finally:
        sock.close()
    return sorted(endpoints)


async def discover_services(
    token: str,
    udp_port: int = DISCOVERY_PORT,
    deadline_seconds: float = 1.5,
) -> list[str]:
    return await asyncio.to_thread(_discover_sync, token, udp_port, deadline_seconds)
