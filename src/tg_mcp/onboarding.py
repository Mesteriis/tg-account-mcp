"""Interactive QR login, separate from the remotely callable MCP surface."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from telethon import TelegramClient
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from tg_mcp.errors import LocalError


async def login_with_qr(
    client: TelegramClient,
    show_qr: Callable[[str], None],
    ask_password: Callable[[], Awaitable[str]],
) -> None:
    if await client.is_user_authorized():
        return
    while True:
        qr = await client.qr_login()
        waiter = asyncio.create_task(qr.wait())
        try:
            # Telethon requires its UpdateLoginToken handler to be listening before scanning.
            await asyncio.sleep(0)
            show_qr(qr.url)
            await waiter
            return
        except TimeoutError:
            continue
        except SessionPasswordNeededError:
            for attempt in range(3):
                password = await ask_password()
                try:
                    await client.sign_in(password=password)
                    return
                except PasswordHashInvalidError:
                    if attempt == 2:
                        raise LocalError(
                            "2FA password rejected three times; run login again"
                        ) from None
                finally:
                    password = ""
        finally:
            if not waiter.done():
                waiter.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await waiter
