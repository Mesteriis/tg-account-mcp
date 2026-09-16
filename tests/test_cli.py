from unittest.mock import AsyncMock

import pytest

from tg_mcp.cli import configure_logging, main, set_bot
from tg_mcp.config import Credentials
from tg_mcp.errors import GatewayError
from tg_mcp.server import connections
from tg_mcp.storage import StateStore


def test_setup_rotation_and_no_secrets_in_output(tmp_path, monkeypatch, capsys):
    root = tmp_path / "private"
    monkeypatch.setattr("builtins.input", lambda prompt: "12345")
    monkeypatch.setattr("tg_mcp.cli.getpass", lambda prompt: "a" * 32)
    assert main(["--state-dir", str(root), "setup"]) == 0
    store = StateStore(root)
    first = store.load().mcp_token.get_secret_value()
    output = capsys.readouterr()
    assert first not in output.out + output.err
    assert "a" * 32 not in output.out + output.err
    assert main(["--state-dir", str(root), "rotate-token"]) == 0
    assert first != store.load().mcp_token.get_secret_value()


def test_cli_cannot_rotate_during_service(tmp_path, capsys):
    store = StateStore(tmp_path / "private")
    with store.lock():
        assert main(["--state-dir", str(store.root), "rotate-token"]) == 1
    assert "already in use" in capsys.readouterr().err


def test_setup_does_not_overwrite_existing_state(tmp_path, capsys):
    store = StateStore(tmp_path / "private")
    config = Credentials(api_id=123, api_hash="a" * 32, mcp_token="x" * 43)
    store.save(config)
    assert main(["--state-dir", str(store.root), "setup"]) == 1
    assert store.load() == config


async def test_connection_failure_cleans_up_both_clients():
    telegram = AsyncMock()
    telegram.connect.side_effect = ConnectionError("secret")
    http = AsyncMock()
    with pytest.raises(GatewayError, match="unavailable"):
        async with connections(telegram, http):
            pytest.fail("Should not start")
    telegram.disconnect.assert_awaited_once()
    http.aclose.assert_awaited_once()


def test_unexpected_runtime_error_is_not_printed(tmp_path, monkeypatch, capsys):
    store = StateStore(tmp_path / "private")
    store.save(Credentials(api_id=123, api_hash="a" * 32, mcp_token="x" * 43))

    def fail(*args):
        raise RuntimeError("secret-upstream-token")

    monkeypatch.setattr("tg_mcp.cli.serve", fail)
    assert main(["--state-dir", str(store.root), "serve"]) == 1
    output = capsys.readouterr()
    assert "secret-upstream-token" not in output.out + output.err


async def test_rejected_bot_keeps_previous_credentials(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "private")
    old = Credentials(
        api_id=123, api_hash="a" * 32, mcp_token="x" * 43, bot_token="123:" + "a" * 30
    )
    store.save(old)
    monkeypatch.setattr(
        "tg_mcp.cli.BotGateway.status",
        AsyncMock(side_effect=GatewayError("not_authorized", "Bot token is invalid or revoked.")),
    )
    with pytest.raises(GatewayError):
        await set_bot(store, old, "456:" + "b" * 30)
    assert store.load() == old


def test_dependency_logs_do_not_expose_request_data(capsys, caplog):
    import logging

    configure_logging()
    for name in ("httpx", "telethon.network", "mcp.server.runner"):
        logging.getLogger(name).error("test-secret-request-body")
    output = capsys.readouterr()
    assert "test-secret-request-body" not in output.out + output.err + caplog.text
