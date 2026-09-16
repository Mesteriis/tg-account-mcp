import asyncio
import secrets
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from tg_mcp.config import Settings
from tg_mcp.errors import GatewayError
from tg_mcp.server import create_app

TOKEN = secrets.token_urlsafe(32)
ACCOUNT_A = "acct_aaaaaaaaaaaaaaaa"
ACCOUNT_B = "acct_bbbbbbbbbbbbbbbb"
BOT_A = "bot_cccccccccccccccc"


class FakeManager:
    def __init__(self):
        self.users = {
            ACCOUNT_A: SimpleNamespace(
                dialogs=AsyncMock(return_value={"account": "a", "chats": []}),
                find_dialogs=AsyncMock(return_value={"account": "a", "chats": []}),
                unread_inbox=AsyncMock(return_value={"account": "a", "chats": []}),
                inbox_context=AsyncMock(return_value={"account": "a", "chats": []}),
                list_folders=AsyncMock(return_value={"account": "a", "folders": []}),
                folder_messages=AsyncMock(return_value={"account": "a", "messages": []}),
                history=AsyncMock(return_value={"account": "a", "messages": []}),
                search_all=AsyncMock(return_value={"account": "a", "messages": []}),
                message=AsyncMock(return_value={"account": "a", "message": {}}),
                message_context=AsyncMock(return_value={"account": "a", "messages": []}),
                reply_thread=AsyncMock(return_value={"account": "a", "replies": []}),
                conversation_snapshot=AsyncMock(return_value={"account": "a", "messages": []}),
                resolve_peer=AsyncMock(return_value={"account": "a", "chats": []}),
                special_messages=AsyncMock(return_value={"account": "a", "messages": []}),
                poll_updates=AsyncMock(return_value={"account": "a", "updates": []}),
                attachments=AsyncMock(return_value={"account": "a", "attachments": []}),
                chat_info=AsyncMock(return_value={"account": "a", "chat": {}}),
                resolve_message_link=AsyncMock(
                    return_value={"chat_id": "123", "message_id": "9", "topic_id": None}
                ),
                topics=AsyncMock(return_value={"account": "a", "topics": []}),
                recent_mentions=AsyncMock(return_value={"account": "a", "messages": []}),
                download_attachment=AsyncMock(
                    return_value={
                        "chat_id": "123",
                        "message_id": "9",
                        "file_name": "photo.png",
                        "mime_type": "image/png",
                        "size": 4,
                        "data": b"data",
                    }
                ),
                download_attachment_chunk=AsyncMock(
                    return_value={
                        "chat_id": "123",
                        "message_id": "9",
                        "file_name": "large.bin",
                        "mime_type": "application/octet-stream",
                        "total_size": 20,
                        "offset": 0,
                        "size": 4,
                        "next_offset": 4,
                        "complete": False,
                        "data": b"data",
                    }
                ),
                send=AsyncMock(return_value={"sender": "user", "account": "a"}),
                edit_own_message=AsyncMock(return_value={"sender": "user", "account": "a"}),
                schedule_message=AsyncMock(return_value={"sender": "user", "account": "a"}),
                scheduled_messages=AsyncMock(return_value={"account": "a", "messages": []}),
                cancel_scheduled_message=AsyncMock(
                    return_value={"account": "a", "cancelled": True}
                ),
                send_attachment=AsyncMock(return_value={"sender": "user", "account": "a"}),
                forward=AsyncMock(return_value={"sender": "user", "account": "a"}),
                mark_read=AsyncMock(return_value={"account": "a", "acknowledged": True}),
                react=AsyncMock(return_value={"account": "a", "reaction": "👍"}),
            ),
            ACCOUNT_B: SimpleNamespace(
                dialogs=AsyncMock(return_value={"account": "b", "chats": []}),
                find_dialogs=AsyncMock(return_value={"account": "b", "chats": []}),
                unread_inbox=AsyncMock(return_value={"account": "b", "chats": []}),
                inbox_context=AsyncMock(return_value={"account": "b", "chats": []}),
                list_folders=AsyncMock(return_value={"account": "b", "folders": []}),
                folder_messages=AsyncMock(return_value={"account": "b", "messages": []}),
                history=AsyncMock(return_value={"account": "b", "messages": []}),
                search_all=AsyncMock(return_value={"account": "b", "messages": []}),
                message=AsyncMock(return_value={"account": "b", "message": {}}),
                message_context=AsyncMock(return_value={"account": "b", "messages": []}),
                reply_thread=AsyncMock(return_value={"account": "b", "replies": []}),
                conversation_snapshot=AsyncMock(return_value={"account": "b", "messages": []}),
                resolve_peer=AsyncMock(return_value={"account": "b", "chats": []}),
                special_messages=AsyncMock(return_value={"account": "b", "messages": []}),
                poll_updates=AsyncMock(return_value={"account": "b", "updates": []}),
                attachments=AsyncMock(return_value={"account": "b", "attachments": []}),
                chat_info=AsyncMock(return_value={"account": "b", "chat": {}}),
                resolve_message_link=AsyncMock(
                    return_value={"chat_id": "123", "message_id": "9", "topic_id": None}
                ),
                topics=AsyncMock(return_value={"account": "b", "topics": []}),
                recent_mentions=AsyncMock(return_value={"account": "b", "messages": []}),
                download_attachment=AsyncMock(),
                download_attachment_chunk=AsyncMock(),
                send=AsyncMock(return_value={"sender": "user", "account": "b"}),
                edit_own_message=AsyncMock(return_value={"sender": "user", "account": "b"}),
                schedule_message=AsyncMock(return_value={"sender": "user", "account": "b"}),
                scheduled_messages=AsyncMock(return_value={"account": "b", "messages": []}),
                cancel_scheduled_message=AsyncMock(
                    return_value={"account": "b", "cancelled": True}
                ),
                send_attachment=AsyncMock(return_value={"sender": "user", "account": "b"}),
                forward=AsyncMock(return_value={"sender": "user", "account": "b"}),
                mark_read=AsyncMock(return_value={"account": "b", "acknowledged": True}),
                react=AsyncMock(return_value={"account": "b", "reaction": "👍"}),
            ),
        }
        self.bots = {
            BOT_A: SimpleNamespace(send=AsyncMock(return_value={"sender": "bot", "bot": "a"}))
        }

    def status(self):
        return {"accounts": {"total": 2, "ready": 2}, "bots": {"total": 1, "ready": 1}}

    def list_accounts(self):
        return [
            {"account_id": account_id, "label": account_id, "status": "ready"}
            for account_id in self.users
        ]

    def list_bots(self):
        return [{"bot_id": BOT_A, "label": "Bot", "status": "ready"}]

    def login_state(self, account_id):
        account = next(row for row in self.list_accounts() if row["account_id"] == account_id)
        return {**account, "qr_data_url": None}

    async def user_gateway(self, account_id):
        try:
            return self.users[account_id]
        except KeyError:
            raise GatewayError("identity_not_found", "Account identity was not found.") from None

    async def bot_gateway(self, bot_id):
        try:
            return self.bots[bot_id]
        except KeyError:
            raise GatewayError("identity_not_found", "Bot identity was not found.") from None


@pytest.fixture
async def endpoint(tmp_path):
    manager = FakeManager()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    settings = Settings(state_dir=tmp_path, port=port, allowed_hosts=[f"127.0.0.1:{port}"])
    app = create_app(settings, manager, TOKEN)
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(5):
            while not server.started:  # noqa: ASYNC110
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp", manager
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


@asynccontextmanager
async def connected(url, *, mode="auto", token=TOKEN):
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
        async with Client(streamable_http_client(url, http_client=http), mode=mode) as client:
            yield client


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_real_sdk_lists_tools_and_routes_explicit_ids(endpoint, mode):
    url, manager = endpoint
    async with connected(url, mode=mode) as client:
        tools = (await client.list_tools()).tools
        assert {tool.name for tool in tools} == {
            "get_status",
            "list_accounts",
            "list_bots",
            "get_capabilities",
            "list_chats",
            "find_chats",
            "get_unread_inbox",
            "get_inbox_context",
            "list_folders",
            "get_folder_messages",
            "get_chat_history",
            "search_messages",
            "search_all_messages",
            "get_message",
            "get_message_context",
            "get_reply_thread",
            "get_conversation_snapshot",
            "resolve_peer",
            "search_chat_content",
            "poll_updates",
            "list_attachments",
            "get_chat_info",
            "resolve_message_link",
            "list_topics",
            "get_recent_mentions",
            "download_attachment",
            "download_attachment_chunk",
            "send_as_user",
            "edit_own_message",
            "schedule_message",
            "list_scheduled_messages",
            "cancel_scheduled_message",
            "send_as_bot",
            "send_attachment",
            "forward_messages",
            "mark_chat_read",
            "react_to_message",
            "create_draft",
            "list_drafts",
            "send_draft",
            "delete_draft",
            "create_agent_token",
            "list_agent_tokens",
            "revoke_agent_token",
        }
        annotations = {tool.name: tool.annotations for tool in tools}
        assert annotations["send_as_user"].read_only_hint is False
        assert annotations["get_chat_history"].read_only_hint is True
        assert annotations["get_unread_inbox"].read_only_hint is True
        assert annotations["send_attachment"].read_only_hint is False
        assert annotations["mark_chat_read"].idempotent_hint is True
        result = await client.call_tool("list_accounts")
        assert len(result.structured_content["accounts"]) == 2
        result = await client.call_tool(
            "find_chats", {"account_id": ACCOUNT_B, "query": "Dima", "limit": 3}
        )
        assert result.structured_content["account"] == "b"
        manager.users[ACCOUNT_B].find_dialogs.assert_awaited_once_with("Dima", limit=3)
        result = await client.call_tool(
            "get_chat_history",
            {
                "account_id": ACCOUNT_B,
                "chat_id": "123",
                "limit": 3,
                "date_from": "2026-09-01",
                "date_to": "2026-09-30",
            },
        )
        assert result.structured_content["account"] == "b"
        manager.users[ACCOUNT_B].history.assert_awaited_once_with(
            "123",
            limit=3,
            cursor=None,
            date_from="2026-09-01",
            date_to="2026-09-30",
        )
        result = await client.call_tool(
            "download_attachment",
            {"account_id": ACCOUNT_A, "chat_id": "123", "message_id": "9"},
        )
        assert result.structured_content["file_name"] == "photo.png"
        assert [block.type for block in result.content] == ["text", "image"]
        manager.users[ACCOUNT_A].download_attachment.assert_awaited_once_with("123", "9")
        result = await client.call_tool(
            "download_attachment_chunk",
            {
                "account_id": ACCOUNT_A,
                "chat_id": "123",
                "message_id": "9",
                "offset": 0,
                "chunk_size": 4,
            },
        )
        assert result.structured_content["next_offset"] == 4
        assert [block.type for block in result.content] == ["text", "resource"]
        manager.users[ACCOUNT_A].download_attachment_chunk.assert_awaited_once_with(
            "123", "9", offset=0, chunk_size=4
        )
        result = await client.call_tool(
            "send_as_user", {"account_id": ACCOUNT_A, "chat_id": "123", "text": "hello"}
        )
        assert result.structured_content["account"] == "a"
        result = await client.call_tool(
            "send_as_bot", {"bot_id": BOT_A, "chat_id": "123", "text": "hello"}
        )
        assert result.structured_content["bot"] == "a"


async def test_idempotency_drafts_and_scoped_agent_access(endpoint):
    url, manager = endpoint
    async with connected(url) as client:
        manager.users[ACCOUNT_A].send.reset_mock()
        arguments = {
            "account_id": ACCOUNT_A,
            "chat_id": "123",
            "text": "one delivery",
            "idempotency_key": "test-one-delivery",
        }
        first = await client.call_tool("send_as_user", arguments)
        second = await client.call_tool("send_as_user", arguments)
        assert not first.is_error
        assert second.structured_content["idempotent_replay"] is True
        manager.users[ACCOUNT_A].send.assert_awaited_once()
        conflict = await client.call_tool(
            "send_as_user", {**arguments, "text": "different arguments"}
        )
        assert conflict.is_error
        manager.users[ACCOUNT_A].send.assert_awaited_once()

        created = await client.call_tool(
            "create_draft",
            {"identity_id": ACCOUNT_A, "chat_id": "123", "text": "draft text"},
        )
        draft_id = created.structured_content["draft_id"]
        await client.call_tool("send_draft", {"draft_id": draft_id})
        replay = await client.call_tool("send_draft", {"draft_id": draft_id})
        assert replay.structured_content["idempotent_replay"] is True
        assert manager.users[ACCOUNT_A].send.await_count == 2

        created_token = await client.call_tool(
            "create_agent_token",
            {
                "label": "Reader",
                "scopes": ["read"],
                "identity_ids": [ACCOUNT_A],
                "chat_ids": ["123"],
            },
        )
        agent_token = created_token.structured_content["token"]

    async with connected(url, token=agent_token) as agent:
        accounts = await agent.call_tool("list_accounts")
        assert [row["account_id"] for row in accounts.structured_content["accounts"]] == [ACCOUNT_A]
        allowed = await agent.call_tool(
            "get_chat_history", {"account_id": ACCOUNT_A, "chat_id": "123"}
        )
        assert not allowed.is_error
        wrong_identity = await agent.call_tool(
            "get_chat_history", {"account_id": ACCOUNT_B, "chat_id": "123"}
        )
        assert wrong_identity.is_error
        wrong_chat = await agent.call_tool(
            "get_chat_history", {"account_id": ACCOUNT_A, "chat_id": "456"}
        )
        assert wrong_chat.is_error
        aggregate = await agent.call_tool("list_chats", {"account_id": ACCOUNT_A})
        assert aggregate.is_error
        send = await agent.call_tool(
            "send_as_user", {"account_id": ACCOUNT_A, "chat_id": "123", "text": "no"}
        )
        assert send.is_error
        admin = await agent.call_tool("list_agent_tokens")
        assert admin.is_error


async def test_identity_id_is_mandatory(endpoint):
    url, manager = endpoint
    async with connected(url) as client:
        result = await client.call_tool("get_chat_history", {"chat_id": "123"})
        assert result.is_error
    manager.users[ACCOUNT_A].history.assert_not_awaited()


async def test_error_details_are_sanitized(endpoint):
    url, manager = endpoint
    manager.users[ACCOUNT_A].send.side_effect = GatewayError(
        "rate_limited", "Wait before trying again.", 15
    )
    async with connected(url) as client:
        result = await client.call_tool(
            "send_as_user",
            {"account_id": ACCOUNT_A, "chat_id": "123", "text": "private text"},
        )
        assert result.is_error
        assert '"retry_after_seconds": 15' in result.content[0].text
        assert "private text" not in result.content[0].text


async def test_auth_and_oversized_body(endpoint):
    url, _ = endpoint
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={"jsonrpc": "2.0", "method": "tools/list"})
        assert response.status_code == 401
        response = await client.post(
            url,
            content=b" " * 70000,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        )
        assert response.status_code == 413
