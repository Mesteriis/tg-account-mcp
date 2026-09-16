"""Independent lifecycle and routing for Telegram user and bot identities."""

import asyncio
import base64
import contextlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import qrcode
import qrcode.image.svg
from telethon import functions
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from tg_mcp.bot import BotGateway
from tg_mcp.config import Credentials
from tg_mcp.errors import GatewayError, LocalError
from tg_mcp.identities import AccountRecord, BotRecord, IdentityCatalog
from tg_mcp.storage import StateStore
from tg_mcp.telegram import UserGateway, make_client

ClientFactory = Callable[[Path, Credentials], Any]
QR_REFRESH_MARGIN_SECONDS = 5
TWO_FACTOR_TTL_SECONDS = 300


@dataclass
class AccountRuntime:
    client: Any
    status: str = "connecting"
    gateway: UserGateway | None = None
    qr_data_url: str | None = None
    error: str | None = None
    login_task: asyncio.Task | None = None
    password_failures: int = 0
    password_hint: str | None = None
    login_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class IdentityManager:
    """Own all identity clients while keeping failures scoped to one identity."""

    def __init__(
        self,
        store: StateStore,
        credentials: Credentials,
        http: httpx.AsyncClient,
        *,
        client_factory: ClientFactory | None = None,
    ):
        self.store = store
        self.credentials = credentials
        self.http = http
        self.catalog = IdentityCatalog.load(store, credentials)
        self._factory = client_factory or self._make_client
        self._accounts: dict[str, AccountRuntime] = {}
        self._bots: dict[str, BotGateway] = {}
        self._mutation_lock = asyncio.Lock()
        self._started = False

    def _make_client(self, path: Path, credentials: Credentials):
        return make_client(self.store, credentials, path)

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for bot in self.catalog.document.bots:
            self._bots[bot.bot_id] = BotGateway(bot.token.get_secret_value(), self.http)
        for account in self.catalog.document.accounts:
            if not account.enabled:
                continue
            runtime = self._new_runtime(account)
            self._accounts[account.account_id] = runtime
            await self._connect_existing(account, runtime)

    async def close(self) -> None:
        tasks = [runtime.login_task for runtime in self._accounts.values() if runtime.login_task]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for runtime in self._accounts.values():
            with contextlib.suppress(Exception):
                await runtime.client.disconnect()
        self._accounts.clear()
        self._started = False

    def _new_runtime(self, account: AccountRecord) -> AccountRuntime:
        path = self.store.account_session_path(account.account_id)
        return AccountRuntime(client=self._factory(path, self.credentials))

    async def _connect_existing(self, account: AccountRecord, runtime: AccountRuntime) -> None:
        try:
            await runtime.client.connect()
            if await runtime.client.is_user_authorized():
                await self._finalize(account, runtime)
            elif account.telegram_id is None:
                await self.begin_login(account.account_id)
            else:
                runtime.status = "revoked"
        except Exception:
            runtime.status = "error"
            runtime.error = "unavailable"

    async def add_account(self, label: str | None = None) -> dict:
        async with self._mutation_lock:
            try:
                account = self.catalog.add_account(label)
            except (LocalError, ValueError) as exc:
                raise GatewayError("invalid_request", str(exc)) from None
            runtime = self._new_runtime(account)
            self._accounts[account.account_id] = runtime
            try:
                await runtime.client.connect()
            except Exception:
                runtime.status = "error"
                runtime.error = "unavailable"
                return self._account_view(account)
            await self.begin_login(account.account_id)
            return self._account_view(account)

    async def begin_login(self, account_id: str) -> dict:
        account = self._account(account_id)
        if not account.enabled:
            raise GatewayError("identity_disabled", "Account identity is disabled.")
        runtime = self._accounts.get(account_id)
        if runtime is None:
            runtime = self._new_runtime(account)
            self._accounts[account_id] = runtime
            try:
                await runtime.client.connect()
            except Exception:
                runtime.status = "error"
                runtime.error = "unavailable"
                return self.login_state(account_id)
        async with runtime.login_lock:
            await self._cancel_login(runtime)
            runtime.error = None
            runtime.qr_data_url = None
            runtime.password_failures = 0
            runtime.password_hint = None
            runtime.status = "connecting"
            runtime.login_task = asyncio.create_task(self._qr_loop(account, runtime))
            await asyncio.sleep(0)
        return self.login_state(account_id)

    async def _cancel_login(self, runtime: AccountRuntime) -> None:
        if runtime.login_task and not runtime.login_task.done():
            runtime.login_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runtime.login_task
        runtime.login_task = None

    async def _qr_loop(self, account: AccountRecord, runtime: AccountRuntime) -> None:
        try:
            while True:
                qr = await runtime.client.qr_login()
                seconds_until_expiry = (qr.expires - datetime.now(UTC)).total_seconds()
                refresh_timeout = max(0.1, seconds_until_expiry - QR_REFRESH_MARGIN_SECONDS)
                waiter = asyncio.create_task(qr.wait(timeout=refresh_timeout))
                await asyncio.sleep(0)
                runtime.qr_data_url = self._qr_data_url(qr.url)
                runtime.status = "waiting_qr"
                try:
                    await waiter
                except TimeoutError:
                    continue
                except SessionPasswordNeededError:
                    runtime.qr_data_url = None
                    runtime.password_hint = None
                    with contextlib.suppress(Exception):
                        password = await runtime.client(functions.account.GetPasswordRequest())
                        runtime.password_hint = getattr(password, "hint", None)
                    runtime.status = "waiting_2fa"
                    await asyncio.sleep(TWO_FACTOR_TTL_SECONDS)
                    if runtime.status == "waiting_2fa":
                        runtime.status = "connecting"
                        continue
                    return
                await self._finalize(account, runtime)
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            runtime.status = "error"
            runtime.error = "unavailable"
            runtime.qr_data_url = None

    @staticmethod
    def _qr_data_url(url: str) -> str:
        image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
        stream = io.BytesIO()
        image.save(stream)
        encoded = base64.b64encode(stream.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    async def submit_password(self, account_id: str, password: str) -> dict:
        account = self._account(account_id)
        runtime = self._runtime(account_id)
        if runtime.status != "waiting_2fa":
            raise GatewayError("invalid_state", "Account is not waiting for a password.")
        try:
            await runtime.client.sign_in(password=password)
        except PasswordHashInvalidError:
            runtime.password_failures += 1
            runtime.error = "invalid_password"
            if runtime.password_failures >= 3:
                runtime.status = "error"
                runtime.error = "password_attempts_exceeded"
            raise GatewayError("invalid_password", "Telegram password is incorrect.") from None
        except Exception:
            raise GatewayError(
                "unavailable", "Telegram login is temporarily unavailable."
            ) from None
        await self._finalize(account, runtime)
        return self.login_state(account_id)

    async def _finalize(self, account: AccountRecord, runtime: AccountRuntime) -> None:
        me = await runtime.client.get_me()
        telegram_id = str(me.id)
        duplicate = next(
            (
                candidate
                for candidate in self.catalog.document.accounts
                if candidate.account_id != account.account_id
                and candidate.telegram_id == telegram_id
            ),
            None,
        )
        if duplicate is not None:
            with contextlib.suppress(Exception):
                await runtime.client.log_out()
            runtime.status = "error"
            runtime.error = "duplicate_account"
            runtime.qr_data_url = None
            runtime.gateway = None
            return
        account.telegram_id = telegram_id
        account.username = getattr(me, "username", None)
        self.catalog.save()
        runtime.gateway = UserGateway(
            runtime.client,
            self.credentials.mcp_token.get_secret_value(),
            account.account_id,
        )
        runtime.status = "ready" if account.setup_complete else "waiting_name"
        runtime.error = None
        runtime.qr_data_url = None
        runtime.password_hint = None

    async def complete_login_for_test(self, account_id: str) -> None:
        """Complete an externally simulated login without weakening production routing."""
        account = self._account(account_id)
        runtime = self._runtime(account_id)
        await self._cancel_login(runtime)
        await self._finalize(account, runtime)

    def _account(self, account_id: str) -> AccountRecord:
        try:
            return self.catalog.account(account_id)
        except LocalError:
            raise GatewayError("identity_not_found", "Account identity was not found.") from None

    def _bot(self, bot_id: str) -> BotRecord:
        try:
            return self.catalog.bot(bot_id)
        except LocalError:
            raise GatewayError("identity_not_found", "Bot identity was not found.") from None

    def _runtime(self, account_id: str) -> AccountRuntime:
        runtime = self._accounts.get(account_id)
        if runtime is None:
            raise GatewayError("unavailable", "Account identity is unavailable.")
        return runtime

    def _account_view(self, account: AccountRecord) -> dict:
        runtime = self._accounts.get(account.account_id)
        status = "disabled" if not account.enabled else runtime.status if runtime else "revoked"
        return {
            "account_id": account.account_id,
            "label": account.label if account.setup_complete else None,
            "enabled": account.enabled,
            "telegram_id": account.telegram_id,
            "username": account.username,
            "status": status,
            "error": runtime.error if runtime else None,
        }

    def list_accounts(self) -> list[dict]:
        return [self._account_view(account) for account in self.catalog.document.accounts]

    def login_state(self, account_id: str) -> dict:
        account = self._account(account_id)
        result = self._account_view(account)
        runtime = self._accounts.get(account_id)
        result["qr_data_url"] = runtime.qr_data_url if runtime else None
        result["password_hint"] = (
            runtime.password_hint if runtime and runtime.status == "waiting_2fa" else None
        )
        result["password_attempts_remaining"] = (
            max(0, 3 - runtime.password_failures)
            if runtime and runtime.status == "waiting_2fa"
            else None
        )
        return result

    async def user_gateway(self, account_id: str) -> UserGateway:
        account = self._account(account_id)
        if not account.enabled:
            raise GatewayError("identity_disabled", "Account identity is disabled.")
        runtime = self._runtime(account_id)
        if runtime.status != "ready" or runtime.gateway is None:
            raise GatewayError("not_authorized", "Account identity is not ready.")
        return runtime.gateway

    async def set_account_enabled(self, account_id: str, enabled: bool) -> dict:
        async with self._mutation_lock:
            account = self._account(account_id)
            if account.enabled == enabled:
                return self._account_view(account)
            account.enabled = enabled
            self.catalog.save()
            if not enabled:
                runtime = self._accounts.pop(account_id, None)
                if runtime:
                    await self._cancel_login(runtime)
                    with contextlib.suppress(Exception):
                        await runtime.client.disconnect()
            else:
                runtime = self._new_runtime(account)
                self._accounts[account_id] = runtime
                await self._connect_existing(account, runtime)
            return self._account_view(account)

    async def rename_account(self, account_id: str, label: str) -> dict:
        async with self._mutation_lock:
            current = self._account(account_id)
            runtime = None
            if not current.setup_complete:
                runtime = self._runtime(account_id)
                if runtime.gateway is None or runtime.status != "waiting_name":
                    raise GatewayError(
                        "invalid_state", "Finish Telegram authorization before naming."
                    )
            try:
                account = self.catalog.rename_account(account_id, label)
                if not account.setup_complete:
                    account.setup_complete = True
                    runtime.status = "ready"
                    self.catalog.save()
                    return self._account_view(account)
            except (LocalError, ValueError) as exc:
                raise GatewayError("invalid_request", str(exc)) from None
            return self._account_view(account)

    async def add_bot(self, label: str, token: str) -> dict:
        gateway = BotGateway(token, self.http)
        status = await gateway.status()
        async with self._mutation_lock:
            try:
                bot = self.catalog.add_bot(label, token, status["id"], status.get("username"))
            except (LocalError, ValueError) as exc:
                raise GatewayError("invalid_request", str(exc)) from None
            self._bots[bot.bot_id] = gateway
            return self._bot_view(bot)

    def _bot_view(self, bot: BotRecord) -> dict:
        return {
            "bot_id": bot.bot_id,
            "label": bot.label,
            "enabled": bot.enabled,
            "telegram_id": bot.telegram_id,
            "username": bot.username,
            "status": "ready" if bot.enabled else "disabled",
        }

    def list_bots(self) -> list[dict]:
        return [self._bot_view(bot) for bot in self.catalog.document.bots]

    async def bot_gateway(self, bot_id: str) -> BotGateway:
        bot = self._bot(bot_id)
        if not bot.enabled:
            raise GatewayError("identity_disabled", "Bot identity is disabled.")
        gateway = self._bots.get(bot_id)
        if gateway is None:
            raise GatewayError("unavailable", "Bot identity is unavailable.")
        return gateway

    async def set_bot_enabled(self, bot_id: str, enabled: bool) -> dict:
        async with self._mutation_lock:
            bot = self._bot(bot_id)
            bot.enabled = enabled
            self.catalog.save()
            return self._bot_view(bot)

    async def rename_bot(self, bot_id: str, label: str) -> dict:
        async with self._mutation_lock:
            try:
                bot = self.catalog.rename_bot(bot_id, label)
            except (LocalError, ValueError) as exc:
                raise GatewayError("invalid_request", str(exc)) from None
            return self._bot_view(bot)

    def status(self) -> dict:
        accounts = self.list_accounts()
        bots = self.list_bots()
        return {
            "accounts": {
                "total": len(accounts),
                "ready": sum(row["status"] == "ready" for row in accounts),
            },
            "bots": {
                "total": len(bots),
                "ready": sum(row["status"] == "ready" for row in bots),
            },
        }
