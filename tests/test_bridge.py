import pytest

from tg_mcp.bridge import _discovery_port, _token, select_endpoint
from tg_mcp.config import Credentials
from tg_mcp.storage import StateStore


def test_bridge_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("TG_MCP_TOKEN", raising=False)
    monkeypatch.setenv("TG_MCP_STATE_DIR", "/path/that/does/not/exist")
    with pytest.raises(ValueError, match="TG_MCP_TOKEN"):
        _token()


def test_bridge_reads_token_from_private_local_state(tmp_path, monkeypatch) -> None:
    state_dir = tmp_path / "private"
    store = StateStore(state_dir)
    store.save(Credentials(api_id=12345, api_hash="a" * 32, mcp_token="x" * 43))
    monkeypatch.delenv("TG_MCP_TOKEN", raising=False)
    monkeypatch.setenv("TG_MCP_STATE_DIR", str(state_dir))

    assert _token() == "x" * 43


def test_bridge_validates_discovery_port(monkeypatch) -> None:
    monkeypatch.setenv("TG_MCP_DISCOVERY_PORT", "70000")
    with pytest.raises(ValueError, match="TG_MCP_DISCOVERY_PORT"):
        _discovery_port()


async def test_bridge_prefers_working_configured_url(monkeypatch) -> None:
    endpoint = "https://telegram.example/mcp"
    monkeypatch.setenv("TG_MCP_URL", endpoint)

    async def works(candidate: str, token: str, deadline_seconds: float = 2.0) -> bool:
        return candidate == endpoint and token == "x" * 43 and deadline_seconds == 5.0

    monkeypatch.setattr("tg_mcp.bridge.endpoint_works", works)

    assert await select_endpoint("x" * 43) == endpoint


async def test_bridge_uses_only_authenticated_discovery(monkeypatch) -> None:
    monkeypatch.delenv("TG_MCP_URL", raising=False)
    seen: list[str] = []

    async def works(candidate: str, token: str, deadline_seconds: float = 2.0) -> bool:
        seen.append(candidate)
        return candidate == "http://192.168.1.5:8000/mcp"

    async def discovered(token: str, udp_port: int) -> list[str]:
        assert token == "x" * 43
        assert udp_port == 38475
        return ["http://192.168.1.5:8000/mcp"]

    monkeypatch.setattr("tg_mcp.bridge.endpoint_works", works)
    monkeypatch.setattr("tg_mcp.bridge.discover_services", discovered)

    assert await select_endpoint("x" * 43) == "http://192.168.1.5:8000/mcp"
    assert seen == ["http://192.168.1.5:8000/mcp"]
