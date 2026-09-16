import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from telethon.errors import SessionPasswordNeededError

from tg_mcp.config import Credentials
from tg_mcp.errors import GatewayError
from tg_mcp.identities import IdentityCatalog
from tg_mcp.manager import IdentityManager
from tg_mcp.storage import StateStore

PENDING = object()


class FakeQr:
    def __init__(self, url, result=PENDING, error=None):
        self.url = url
        self.result = result
        self.error = error
        self.expires = datetime.now(UTC) + timedelta(seconds=30)
        self.last_timeout = PENDING

    async def wait(self, timeout=None):  # noqa: ASYNC109 - mirrors Telethon's API
        self.last_timeout = timeout
        await asyncio.sleep(0)
        if self.error:
            raise self.error
        if self.result is PENDING:
            await asyncio.Future()
        return self.result


class FakeClient:
    def __init__(self, telegram_id=None, qr=None, connect_error=None):
        self.telegram_id = telegram_id
        self.qr = qr or FakeQr("tg://login?token=test")
        self.connect_error = connect_error
        self.qr_calls = 0
        self.connected = False
        self.authorized = telegram_id is not None
        self.disconnect = AsyncMock(side_effect=self._disconnect)
        self.log_out = AsyncMock(side_effect=self._logout)

    async def _disconnect(self):
        self.connected = False

    async def _logout(self):
        self.authorized = False

    async def connect(self):
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    async def is_user_authorized(self):
        return self.authorized

    async def get_me(self):
        return SimpleNamespace(id=self.telegram_id, username=f"user{self.telegram_id}")

    async def qr_login(self):
        self.qr_calls += 1
        if isinstance(self.qr, list):
            return self.qr.pop(0)
        return self.qr

    async def sign_in(self, password):
        if password == "bad":
            from telethon.errors import PasswordHashInvalidError

            raise PasswordHashInvalidError(request=None)
        self.telegram_id = int(password)
        self.authorized = True

    async def __call__(self, request):
        return SimpleNamespace(hint="childhood pet")


def config():
    return Credentials(api_id=123, api_hash="a" * 32, mcp_token="x" * 43)


@pytest.fixture
async def manager(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(config())
    clients = []

    def factory(path, credentials):
        client = FakeClient()
        clients.append(client)
        return client

    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as http:
        value = IdentityManager(store, config(), http, client_factory=factory)
        yield value, clients
        await value.close()


async def wait_for_state(manager, account_id, state):
    async with asyncio.timeout(2):
        while manager.login_state(account_id)["status"] != state:  # noqa: ASYNC110
            await asyncio.sleep(0)


async def test_starts_without_accounts(manager):
    value, _ = manager
    await value.start()
    assert value.list_accounts() == []
    assert value.status()["accounts"]["total"] == 0


async def test_existing_unauthorized_account_gets_qr_on_start(tmp_path):
    store = StateStore(tmp_path / "state")
    credentials = config()
    store.save(credentials)
    account = IdentityCatalog.load(store, credentials).add_account("Primary")
    client = FakeClient()
    async with httpx.AsyncClient() as http:
        value = IdentityManager(
            store, credentials, http, client_factory=lambda path, current: client
        )
        await value.start()
        await wait_for_state(value, account.account_id, "waiting_qr")
        assert value.login_state(account.account_id)["qr_data_url"].startswith(
            "data:image/svg+xml;base64,"
        )
        await value.close()


async def test_two_accounts_authorize_independently(manager):
    value, clients = manager
    await value.start()
    first = await value.add_account("Personal")
    second = await value.add_account("Work")
    await wait_for_state(value, first["account_id"], "waiting_qr")
    await wait_for_state(value, second["account_id"], "waiting_qr")
    clients[0].telegram_id, clients[0].authorized = 101, True
    clients[1].telegram_id, clients[1].authorized = 202, True
    await value.complete_login_for_test(first["account_id"])
    await value.complete_login_for_test(second["account_id"])
    assert {row["telegram_id"] for row in value.list_accounts()} == {"101", "202"}
    assert (await value.user_gateway(first["account_id"])).identity_id == first["account_id"]


async def test_wizard_requests_name_only_after_telegram_authorization(manager):
    value, clients = manager
    await value.start()
    draft = await value.add_account()
    assert draft["label"] is None
    assert draft["status"] in {"connecting", "waiting_qr"}
    clients[0].telegram_id, clients[0].authorized = 404, True
    await value.complete_login_for_test(draft["account_id"])
    assert value.login_state(draft["account_id"])["status"] == "waiting_name"
    with pytest.raises(GatewayError, match="not_authorized"):
        await value.user_gateway(draft["account_id"])
    completed = await value.rename_account(draft["account_id"], "Personal")
    assert completed["label"] == "Personal"
    assert completed["status"] == "ready"
    assert (await value.user_gateway(draft["account_id"])).identity_id == draft["account_id"]


async def test_2fa_flow_and_duplicate_account(manager):
    value, clients = manager
    await value.start()
    first = await value.add_account("One")
    clients[0].qr = FakeQr("tg://one", error=SessionPasswordNeededError(request=None))
    await value.begin_login(first["account_id"])
    await wait_for_state(value, first["account_id"], "waiting_2fa")
    await value.submit_password(first["account_id"], "303")
    second = await value.add_account("Two")
    clients[1].telegram_id, clients[1].authorized = 303, True
    await value.complete_login_for_test(second["account_id"])
    state = value.login_state(second["account_id"])
    assert state["status"] == "error"
    assert state["error"] == "duplicate_account"
    clients[1].log_out.assert_awaited_once()


async def test_disable_is_scoped_to_one_account(manager):
    value, clients = manager
    await value.start()
    first = await value.add_account("One")
    second = await value.add_account("Two")
    for client, telegram_id in zip(clients, (1, 2), strict=True):
        client.telegram_id, client.authorized = telegram_id, True
    await value.complete_login_for_test(first["account_id"])
    await value.complete_login_for_test(second["account_id"])
    await value.set_account_enabled(first["account_id"], False)
    with pytest.raises(GatewayError, match="identity_disabled"):
        await value.user_gateway(first["account_id"])
    assert (await value.user_gateway(second["account_id"])).identity_id == second["account_id"]


async def test_missing_id_is_safe(manager):
    value, _ = manager
    await value.start()
    with pytest.raises(GatewayError, match="identity_not_found"):
        await value.user_gateway("acct_aaaaaaaaaaaaaaaa")


async def test_expired_qr_is_refreshed(manager):
    value, clients = manager
    await value.start()
    account = await value.add_account("Refresh")
    clients[0].qr = [
        FakeQr("tg://old", error=TimeoutError()),
        FakeQr("tg://new"),
    ]
    await value.begin_login(account["account_id"])
    async with asyncio.timeout(2):
        while not (  # noqa: ASYNC110
            clients[0].qr_calls >= 3
            and value.login_state(account["account_id"])["status"] == "waiting_qr"
        ):
            await asyncio.sleep(0)
    assert value.login_state(account["account_id"])["status"] == "waiting_qr"


async def test_qr_is_refreshed_before_telegram_expiration(manager):
    value, clients = manager
    await value.start()
    account = await value.add_account("Refresh early")
    qr = FakeQr("tg://fresh")
    clients[0].qr = qr

    await value.begin_login(account["account_id"])
    async with asyncio.timeout(2):
        while qr.last_timeout is PENDING:  # noqa: ASYNC110
            await asyncio.sleep(0)

    assert qr.last_timeout is not None
    assert 0 < qr.last_timeout < 30


async def test_three_invalid_passwords_stop_login(manager):
    value, clients = manager
    await value.start()
    account = await value.add_account("Password")
    clients[0].qr = FakeQr("tg://2fa", error=SessionPasswordNeededError(request=None))
    await value.begin_login(account["account_id"])
    await wait_for_state(value, account["account_id"], "waiting_2fa")
    for _ in range(3):
        with pytest.raises(GatewayError, match="invalid_password"):
            await value.submit_password(account["account_id"], "bad")
    state = value.login_state(account["account_id"])
    assert state["status"] == "error"
    assert state["error"] == "password_attempts_exceeded"


async def test_2fa_state_exposes_hint_and_safe_failure_details(manager):
    value, clients = manager
    await value.start()
    account = await value.add_account("Password")
    clients[0].qr = FakeQr("tg://2fa", error=SessionPasswordNeededError(request=None))
    await value.begin_login(account["account_id"])
    await wait_for_state(value, account["account_id"], "waiting_2fa")

    state = value.login_state(account["account_id"])
    assert state["password_hint"] == "childhood pet"
    assert state["password_attempts_remaining"] == 3

    with pytest.raises(GatewayError, match="invalid_password"):
        await value.submit_password(account["account_id"], "bad")

    state = value.login_state(account["account_id"])
    assert state["error"] == "invalid_password"
    assert state["password_attempts_remaining"] == 2


async def test_expired_2fa_step_returns_to_a_fresh_qr(manager, monkeypatch):
    monkeypatch.setattr("tg_mcp.manager.TWO_FACTOR_TTL_SECONDS", 0)
    value, clients = manager
    await value.start()
    account = await value.add_account("Password")
    clients[0].qr = [
        FakeQr("tg://2fa", error=SessionPasswordNeededError(request=None)),
        FakeQr("tg://fresh"),
    ]

    await value.begin_login(account["account_id"])
    async with asyncio.timeout(2):
        while not (  # noqa: ASYNC110
            clients[0].qr_calls >= 3
            and value.login_state(account["account_id"])["status"] == "waiting_qr"
        ):
            await asyncio.sleep(0)

    state = value.login_state(account["account_id"])
    assert state["status"] == "waiting_qr"
    assert state["qr_data_url"] is not None


async def test_connection_failure_does_not_break_other_account(tmp_path):
    store = StateStore(tmp_path / "state")
    credentials = config()
    store.save(credentials)
    catalog = IdentityCatalog.load(store, credentials)
    catalog.add_account("Broken")
    catalog.add_account("Healthy")
    clients = [FakeClient(connect_error=OSError()), FakeClient(telegram_id=42)]

    def factory(path, current):
        return clients.pop(0)

    async with httpx.AsyncClient() as http:
        value = IdentityManager(store, credentials, http, client_factory=factory)
        await value.start()
        states = {row["label"]: row["status"] for row in value.list_accounts()}
        assert states == {"Broken": "error", "Healthy": "ready"}
        await value.close()


async def test_multiple_bots_are_selected_by_id(tmp_path):
    def responder(request):
        telegram_id = 1 if "/bot111:" in str(request.url) else 2
        return httpx.Response(200, json={"ok": True, "result": {"id": telegram_id}})

    store = StateStore(tmp_path / "state")
    credentials = config()
    store.save(credentials)
    async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as http:
        value = IdentityManager(store, credentials, http)
        await value.start()
        first = await value.add_bot("One", "111:" + "a" * 30)
        second = await value.add_bot("Two", "222:" + "b" * 30)
        assert (await value.bot_gateway(first["bot_id"]))._token.startswith("111:")
        assert (await value.bot_gateway(second["bot_id"]))._token.startswith("222:")
        await value.close()
