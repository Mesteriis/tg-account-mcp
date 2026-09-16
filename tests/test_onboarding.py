import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from tg_mcp.onboarding import login_with_qr


def client():
    return SimpleNamespace(
        is_user_authorized=AsyncMock(return_value=False),
        qr_login=AsyncMock(),
        sign_in=AsyncMock(),
    )


async def test_existing_session_needs_no_qr():
    telegram = client()
    telegram.is_user_authorized.return_value = True
    await login_with_qr(telegram, Mock(), AsyncMock())
    telegram.qr_login.assert_not_called()


async def test_expired_qr_is_refreshed():
    telegram = client()
    telegram.qr_login.side_effect = [
        SimpleNamespace(url="tg://first", wait=AsyncMock(side_effect=TimeoutError)),
        SimpleNamespace(url="tg://second", wait=AsyncMock(return_value=None)),
    ]
    show = Mock()
    await login_with_qr(telegram, show, AsyncMock())
    assert [c.args[0] for c in show.call_args_list] == ["tg://first", "tg://second"]


async def test_wait_registered_before_qr_display_and_2fa():
    telegram = client()
    listening = False

    async def wait():
        nonlocal listening
        listening = True
        await asyncio.sleep(0)
        raise SessionPasswordNeededError(request=None)

    def show(url):
        assert listening

    telegram.qr_login.return_value = SimpleNamespace(url="tg://test", wait=wait)
    await login_with_qr(telegram, show, AsyncMock(return_value="test-password"))
    telegram.sign_in.assert_awaited_once_with(password="test-password")


async def test_display_failure_cancels_waiter():
    telegram = client()
    stopped = asyncio.Event()

    async def wait():
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    telegram.qr_login.return_value = SimpleNamespace(url="tg://test", wait=wait)
    with pytest.raises(RuntimeError, match="terminal"):
        await login_with_qr(telegram, Mock(side_effect=RuntimeError("terminal")), AsyncMock())
    assert stopped.is_set()


async def test_wrong_2fa_is_bounded_and_never_saved():
    telegram = client()
    telegram.qr_login.return_value = SimpleNamespace(
        url="tg://test", wait=AsyncMock(side_effect=SessionPasswordNeededError(request=None))
    )
    telegram.sign_in.side_effect = PasswordHashInvalidError(request=None)
    ask = AsyncMock(return_value="test-only-password")
    with pytest.raises(RuntimeError, match="three times"):
        await login_with_qr(telegram, Mock(), ask)
    assert ask.await_count == 3


async def test_cancellation_removes_qr_listener():
    telegram = client()
    shown = asyncio.Event()
    stopped = asyncio.Event()

    async def wait():
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    telegram.qr_login.return_value = SimpleNamespace(url="tg://test", wait=wait)
    task = asyncio.create_task(login_with_qr(telegram, lambda url: shown.set(), AsyncMock()))
    await shown.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stopped.is_set()
