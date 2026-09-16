import secrets
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from tg_mcp.config import Settings
from tg_mcp.server import create_app

TOKEN = secrets.token_urlsafe(32)
ACCOUNT = "acct_aaaaaaaaaaaaaaaa"
BOT = "bot_bbbbbbbbbbbbbbbb"


def test_wizard_submit_buttons_do_not_recursively_submit_forms():
    script = (Path(__file__).parents[1] / "src/tg_mcp/static/app.js").read_text()

    assert "form.requestSubmit()" not in script


def test_status_polling_does_not_replace_an_unchanged_wizard_form():
    script = (Path(__file__).parents[1] / "src/tg_mcp/static/app.js").read_text()

    assert "nextWizardKey !== renderedWizardKey" in script


def test_2fa_wizard_explains_password_and_allows_restart():
    script = (Path(__file__).parents[1] / "src/tg_mcp/static/app.js").read_text()

    assert "Подсказка Telegram" in script
    assert "Это не код из SMS" in script
    assert "Начать заново" in script


def test_chart_wave_animation_is_bounded_and_respects_reduced_motion():
    script = (Path(__file__).parents[1] / "src/tg_mcp/static/app.js").read_text()

    assert "prefers-reduced-motion: reduce" in script
    assert "function startChartAnimation()" in script
    assert "cancelAnimationFrame(chartAnimationFrame)" in script
    assert "* 1.65" in script
    assert "function chartAreaPath(" in script
    assert "createLinearGradient" in script
    assert "hourly_series" in script
    assert "function formatBucket(" in script


class FakeManager:
    def __init__(self):
        self.add_account = AsyncMock(
            return_value={"account_id": ACCOUNT, "label": None, "status": "waiting_qr"}
        )
        self.begin_login = AsyncMock(return_value={"account_id": ACCOUNT, "status": "waiting_qr"})
        self.submit_password = AsyncMock(
            return_value={"account_id": ACCOUNT, "status": "waiting_name"}
        )
        self.rename_account = AsyncMock(return_value={"account_id": ACCOUNT, "label": "New"})
        self.set_account_enabled = AsyncMock(return_value={"account_id": ACCOUNT, "enabled": False})
        self.add_bot = AsyncMock(return_value={"bot_id": BOT, "label": "Helper", "status": "ready"})
        self.rename_bot = AsyncMock(return_value={"bot_id": BOT, "label": "New"})
        self.set_bot_enabled = AsyncMock(return_value={"bot_id": BOT, "enabled": False})

    def status(self):
        return {"accounts": {"total": 1, "ready": 0}, "bots": {"total": 0, "ready": 0}}

    def list_accounts(self):
        return [{"account_id": ACCOUNT, "label": "Personal", "status": "waiting_qr"}]

    def login_state(self, account_id):
        return {
            "account_id": account_id,
            "label": "Personal",
            "status": "waiting_qr",
            "qr_data_url": "data:image/svg+xml;base64,PHN2Zy8+",
        }

    def list_bots(self):
        return []


def app(tmp_path, *, host):
    settings = Settings(
        state_dir=tmp_path,
        host=host,
        allowed_hosts=["mcp.test"],
        allowed_origins=["https://mcp.test"],
    )
    manager = FakeManager()
    return create_app(settings, manager, TOKEN), manager


async def test_page_is_public_and_has_safe_headers(tmp_path):
    application, _ = app(tmp_path, host="0.0.0.0")
    transport = httpx.ASGITransport(application, client=("203.0.113.9", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://mcp.test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "TG MCP" in response.text
    assert "QR → 2FA" in response.text
    assert "accountLabel" not in response.text
    assert "/assets/app.css" in response.text


async def test_remote_setup_requires_bearer(tmp_path):
    application, _ = app(tmp_path, host="0.0.0.0")
    transport = httpx.ASGITransport(application, client=("203.0.113.9", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://mcp.test") as client:
        response = await client.get("/setup/api/status")
        assert response.status_code == 401
        response = await client.get(
            "/setup/api/status",
            headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://mcp.test"},
        )
    assert response.status_code == 200
    assert response.json()["accounts"][0]["qr_data_url"].startswith("data:image/svg+xml")
    assert response.json()["analytics"]["totals"]["requests"] == 0
    assert len(response.json()["analytics"]["hourly_series"]) == 24


async def test_static_assets_are_local_and_allowlisted(tmp_path):
    application, _ = app(tmp_path, host="127.0.0.1")
    transport = httpx.ASGITransport(application, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://mcp.test") as client:
        css = await client.get("/assets/app.css")
        icon = await client.get("/assets/icon-house.svg")
        missing = await client.get("/assets/secret.txt")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert icon.status_code == 200
    assert "image/svg+xml" in icon.headers["content-type"]
    assert missing.status_code == 404


async def test_loopback_setup_bypasses_token_only_for_loopback_client(tmp_path):
    application, _ = app(tmp_path, host="127.0.0.1")
    local = httpx.ASGITransport(application, client=("127.0.0.1", 50000))
    remote = httpx.ASGITransport(application, client=("192.0.2.10", 50000))
    async with httpx.AsyncClient(transport=local, base_url="https://mcp.test") as client:
        assert (await client.get("/setup/api/status")).status_code == 200
    async with httpx.AsyncClient(transport=remote, base_url="https://mcp.test") as client:
        assert (await client.get("/setup/api/status")).status_code == 401


async def test_account_and_bot_actions_and_body_limit(tmp_path):
    application, manager = app(tmp_path, host="127.0.0.1")
    transport = httpx.ASGITransport(application, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://mcp.test") as client:
        response = await client.post("/setup/api/accounts", json={})
        assert response.status_code == 201
        response = await client.post(
            "/setup/api/accounts", content=b"x" * 9000, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413
        response = await client.post(
            "/setup/api/bots", json={"label": "Helper", "token": "123:" + "x" * 30}
        )
        assert response.status_code == 201
        response = await client.patch(f"/setup/api/accounts/{ACCOUNT}", json={"enabled": False})
        assert response.status_code == 200
    manager.add_account.assert_awaited_once_with()
    manager.add_bot.assert_awaited_once()
    manager.set_account_enabled.assert_awaited_once_with(ACCOUNT, False)
