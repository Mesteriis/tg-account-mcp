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

from tg_mcp.archive import ArchiveStore
from tg_mcp.config import Settings
from tg_mcp.errors import GatewayError
from tg_mcp.server import create_app
from tg_mcp.storage import StateStore

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
    manager.archive = ArchiveStore(StateStore(tmp_path))
    manager.embedding_provider = SimpleNamespace(
        enabled=False,
        model_key=AsyncMock(
            side_effect=GatewayError("semantic_disabled", "Configure local embeddings first.")
        ),
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    settings = Settings(state_dir=tmp_path, port=port, allowed_hosts=[f"127.0.0.1:{port}"])
    app = create_app(settings, manager, TOKEN, embedding_provider=manager.embedding_provider)
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
            "configure_chat_archive",
            "sync_chat_archive",
            "get_archive_status",
            "get_ingestion_policy",
            "set_ingestion_policy",
            "search_archive",
            "get_message_versions",
            "export_chat_archive",
            "purge_chat_archive",
            "create_memory_project",
            "list_memory_projects",
            "propose_project_memory",
            "approve_project_memory",
            "list_project_memory",
            "delete_project_memory",
            "delete_memory_project",
            "index_archive_semantics",
            "semantic_search_archive",
            "find_messages",
            "index_project_memory",
            "search_project_memory",
            "get_background_rag_status",
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


async def test_archive_tools_enforce_chat_account_and_admin_scopes(endpoint):
    url, manager = endpoint
    archive = manager.archive
    for account, chat, text in [
        (ACCOUNT_A, "123", "SQLite chosen"),
        (ACCOUNT_A, "456", "private secret"),
        (ACCOUNT_B, "123", "other account secret"),
    ]:
        archive.configure(account, chat, "Synthetic", enabled=True, retain_deleted=True)
        archive.ingest_page(
            account,
            chat,
            [{"id": "1", "text": text, "date": "2026-10-25T10:00:00+00:00", "sender_id": "7"}],
            None,
        )
    async with connected(url) as client:
        created = await client.call_tool(
            "create_agent_token",
            {
                "label": "Archive reader",
                "scopes": ["read"],
                "identity_ids": [ACCOUNT_A],
                "chat_ids": ["123"],
            },
        )
        token = created.structured_content["token"]
    async with connected(url, token=token) as client:
        args = {"account_id": ACCOUNT_A, "chat_id": "123"}
        found = await client.call_tool("search_archive", {**args, "query": "SQLite"})
        assert not found.is_error
        assert found.structured_content["messages"][0]["text"] == "SQLite chosen"
        for name, extra in [
            ("get_archive_status", {}),
            ("search_archive", {"query": "secret"}),
            ("export_chat_archive", {}),
            ("get_message_versions", {"message_id": "1"}),
        ]:
            assert not (await client.call_tool(name, {**args, **extra})).is_error
            for denied in [{**args, "chat_id": "456"}, {**args, "account_id": ACCOUNT_B}]:
                assert (await client.call_tool(name, {**denied, **extra})).is_error
        for name in ["configure_chat_archive", "sync_chat_archive", "purge_chat_archive"]:
            assert (await client.call_tool(name, args)).is_error
        # The admin check precedes upstream chat metadata or any mutation.
        manager.users[ACCOUNT_A].chat_info.assert_not_awaited()
        assert archive.status(ACCOUNT_A, "123")["message_count"] == 1
        assert (
            await client.call_tool(
                "search_archive", {**args, "query": "SQLite", "date_from": "2026-02-30"}
            )
        ).is_error


async def test_archive_search_cursor_is_bound_to_chat_query_and_filters(endpoint):
    url, manager = endpoint
    for chat in ["123", "456"]:
        manager.archive.configure(ACCOUNT_A, chat, "Synthetic", enabled=True, retain_deleted=True)
        manager.archive.ingest_page(
            ACCOUNT_A,
            chat,
            [
                {"id": str(i), "text": "SQLite decision", "date": "2026-10-25T10:00:00+00:00"}
                for i in range(1, 4)
            ],
            None,
        )
    async with connected(url) as client:
        args = {"account_id": ACCOUNT_A, "chat_id": "123", "query": "SQLite", "limit": 2}
        first = await client.call_tool("search_archive", args)
        cursor = first.structured_content["next_cursor"]
        assert cursor
        second = await client.call_tool("search_archive", {**args, "cursor": cursor})
        assert len(second.structured_content["messages"]) == 1
        for change in [{"chat_id": "456"}, {"query": "decision"}, {"include_deleted": True}]:
            assert (
                await client.call_tool("search_archive", {**args, "cursor": cursor, **change})
            ).is_error
        versions = await client.call_tool(
            "get_message_versions", {"account_id": ACCOUNT_A, "chat_id": "123", "message_id": "1"}
        )
        assert versions.structured_content["versions"][0]["message"]["text"] == "SQLite decision"
        purged = await client.call_tool(
            "purge_chat_archive", {"account_id": ACCOUNT_A, "chat_id": "123"}
        )
        assert purged.structured_content["purged"]
        assert (await client.call_tool("search_archive", args)).is_error
        assert manager.archive.status(ACCOUNT_A, "456")["message_count"] == 3


async def test_pause_archive_preserves_retention_unless_explicitly_changed(endpoint):
    url, manager = endpoint
    manager.archive.configure(ACCOUNT_A, "123", "Synthetic", enabled=True, retain_deleted=True)
    manager.archive.ingest_page(ACCOUNT_A, "123", [{"id": "1", "text": "retained"}], None)
    manager.archive.record(ACCOUNT_A, "deleted_messages", {"chat_id": "123", "message_ids": ["1"]})
    async with connected(url) as client:
        args = {"account_id": ACCOUNT_A, "chat_id": "123", "enabled": False}
        paused = await client.call_tool("configure_chat_archive", args)
        assert not paused.is_error
        assert paused.structured_content["retain_deleted"] is True
        assert manager.archive.search(ACCOUNT_A, "123", "retained", include_deleted=True)[
            "messages"
        ]
        erased = await client.call_tool("configure_chat_archive", {**args, "retain_deleted": False})
        assert not erased.is_error
        assert not manager.archive.search(ACCOUNT_A, "123", "retained", include_deleted=True)[
            "messages"
        ]


async def test_disabled_account_blocks_archive_reads_but_allows_admin_cleanup(endpoint):
    url, manager = endpoint
    manager.archive.configure(ACCOUNT_A, "123", "Synthetic", enabled=True, retain_deleted=True)
    original = manager.list_accounts
    manager.list_accounts = lambda: [
        {**row, "enabled": False, "status": "disabled"} for row in original()
    ]
    async with connected(url) as client:
        args = {"account_id": ACCOUNT_A, "chat_id": "123"}
        for name, extra in [
            ("get_archive_status", {}),
            ("search_archive", {"query": "test"}),
            ("get_message_versions", {"message_id": "1"}),
            ("export_chat_archive", {}),
        ]:
            assert (await client.call_tool(name, {**args, **extra})).is_error
        paused = await client.call_tool("configure_chat_archive", {**args, "enabled": False})
        assert not paused.is_error
        purged = await client.call_tool("purge_chat_archive", args)
        assert purged.structured_content["purged"] is True


async def test_project_memory_approval_semantics_and_scope_boundaries(endpoint):
    url, manager = endpoint
    provider = manager.embedding_provider
    provider.enabled = True
    provider.model_key = AsyncMock(return_value="synthetic-model")
    provider.embed = AsyncMock(side_effect=lambda texts, key: [[1.0, 0.0] for _ in texts])
    archive = manager.archive
    for chat in ["123", "456"]:
        archive.configure(ACCOUNT_A, chat, "Synthetic", enabled=True, retain_deleted=True)
        archive.ingest_page(ACCOUNT_A, chat, [{"id": "1", "text": "durable queue"}], None)
    async with connected(url) as client:
        projects = []
        for chats in [["123"], ["456"], ["123", "456"]]:
            result = await client.call_tool(
                "create_memory_project",
                {"account_id": ACCOUNT_A, "title": "Synthetic project", "chat_ids": chats},
            )
            assert not result.is_error
            projects.append(result.structured_content["project_id"])
        project = projects[0]
        args = {"account_id": ACCOUNT_A, "project_id": project}
        proposed = await client.call_tool(
            "propose_project_memory",
            {**args, "text": "Use a queue", "sources": [{"chat_id": "123", "message_id": "1"}]},
        )
        assert not proposed.is_error
        memory_id = proposed.structured_content["memory_id"]
        result = await client.call_tool("search_project_memory", {**args, "query": "queue"})
        assert not result.structured_content["results"]
        approved = await client.call_tool(
            "approve_project_memory", {**args, "memory_id": memory_id}
        )
        assert approved.structured_content["state"] == "approved"
        indexed = await client.call_tool("index_project_memory", args)
        assert indexed.structured_content["indexed"] == 1
        indexed_chat = await client.call_tool(
            "index_archive_semantics", {"account_id": ACCOUNT_A, "chat_id": "123"}
        )
        assert indexed_chat.structured_content["indexed"] == 1
        denied_source = await client.call_tool(
            "propose_project_memory",
            {**args, "text": "no", "sources": [{"chat_id": "456", "message_id": "1"}]},
        )
        assert denied_source.is_error
        created = await client.call_tool(
            "create_agent_token",
            {
                "label": "Scoped memory reader",
                "scopes": ["read"],
                "identity_ids": [ACCOUNT_A],
                "chat_ids": ["123"],
            },
        )
        token = created.structured_content["token"]
    async with connected(url, token=token) as client:
        args = {"account_id": ACCOUNT_A, "project_id": project}
        result = await client.call_tool(
            "search_project_memory", {**args, "query": "queue", "mode": "semantic"}
        )
        assert not result.is_error
        assert result.structured_content["results"][0]["sources"] == [
            {"account_id": ACCOUNT_A, "chat_id": "123", "message_id": "1"}
        ]
        listed = await client.call_tool("list_memory_projects", {"account_id": ACCOUNT_A})
        assert [p["project_id"] for p in listed.structured_content["projects"]] == [project]
        provider.embed.reset_mock()
        for denied_project in projects[1:]:
            result = await client.call_tool(
                "search_project_memory",
                {**args, "project_id": denied_project, "query": "queue", "mode": "semantic"},
            )
            assert result.is_error
        result = await client.call_tool(
            "semantic_search_archive", {"account_id": ACCOUNT_A, "chat_id": "456", "query": "queue"}
        )
        assert result.is_error
        provider.embed.assert_not_awaited()
        archive.purge(ACCOUNT_A, "456")
        for denied_project in projects[1:]:
            result = await client.call_tool(
                "search_project_memory",
                {**args, "project_id": denied_project, "query": "queue", "mode": "semantic"},
            )
            assert result.is_error
        provider.embed.assert_not_awaited()
        for name, extra in [
            ("approve_project_memory", {"memory_id": memory_id}),
            ("delete_project_memory", {"memory_id": memory_id}),
            ("index_project_memory", {}),
            ("delete_memory_project", {}),
            ("list_project_memory", {"state": "all"}),
        ]:
            assert (await client.call_tool(name, {**args, **extra})).is_error
        assert (
            await client.call_tool(
                "search_project_memory", {**args, "account_id": ACCOUNT_B, "query": "queue"}
            )
        ).is_error
        archive.record(
            ACCOUNT_A,
            "edited_message",
            {
                "chat_id": "123",
                "message": {
                    "id": "1",
                    "text": "new decision",
                    "edit_date": "2026-10-25T12:00:00+00:00",
                },
            },
        )
        result = await client.call_tool(
            "search_project_memory", {**args, "query": "queue", "mode": "semantic"}
        )
        assert not result.structured_content["results"]


async def test_semantic_disabled_is_explicit_and_offline_keyword_memory_still_works(endpoint):
    url, manager = endpoint
    manager.archive.configure(ACCOUNT_A, "123", "Synthetic", enabled=True, retain_deleted=False)
    async with connected(url) as client:
        result = await client.call_tool(
            "semantic_search_archive", {"account_id": ACCOUNT_A, "chat_id": "123", "query": "queue"}
        )
        assert result.is_error
        capabilities = (await client.call_tool("get_capabilities")).structured_content
        assert capabilities["features"]["semantic_search"] is False
        assert capabilities["features"]["project_memory"] is True


async def test_background_status_is_admin_only(endpoint):
    url, _ = endpoint
    async with connected(url) as client:
        result = await client.call_tool("get_background_rag_status")
        assert result.structured_content == {"enabled": False, "running": False}
        token = (
            await client.call_tool(
                "create_agent_token",
                {
                    "label": "Reader",
                    "scopes": ["read"],
                    "identity_ids": [ACCOUNT_A],
                    "chat_ids": ["123"],
                },
            )
        ).structured_content["token"]
    async with connected(url, token=token) as client:
        assert (await client.call_tool("get_background_rag_status")).is_error


async def test_local_first_search_enforces_identity_and_chat_scope_before_retrieval(endpoint):
    url, manager = endpoint
    archive = manager.archive
    for account, chat in [(ACCOUNT_A, "123"), (ACCOUNT_A, "456"), (ACCOUNT_B, "123")]:
        archive.configure(account, chat, "Synthetic", enabled=True, retain_deleted=False)
        archive.ingest_page(account, chat, [{"id": "1", "text": "queue secret"}], None)
    async with connected(url) as admin:
        token = (
            await admin.call_tool(
                "create_agent_token",
                {
                    "label": "Scoped finder",
                    "scopes": ["read"],
                    "identity_ids": [ACCOUNT_A],
                    "chat_ids": ["123"],
                },
            )
        ).structured_content["token"]
    manager.embedding_provider.model_key.reset_mock()
    async with connected(url, token=token) as client:
        for args in [{}, {"chat_id": "456"}, {"chat_id": "123", "account_id": ACCOUNT_B}]:
            result = await client.call_tool(
                "find_messages",
                {"account_id": ACCOUNT_A, "query": "queue", "telegram": "never", **args},
            )
            assert result.is_error
        manager.embedding_provider.model_key.assert_not_awaited()
        result = await client.call_tool(
            "find_messages",
            {"account_id": ACCOUNT_A, "chat_id": "123", "query": "queue", "telegram": "never"},
        )
        assert not result.is_error
        assert len(result.structured_content["results"]) == 1
        assert result.structured_content["results"][0]["account_id"] == ACCOUNT_A
    manager.users[ACCOUNT_A].history.assert_not_awaited()


async def test_find_messages_native_cursor_continues_with_date_bounds(endpoint):
    url, manager = endpoint
    manager.users[ACCOUNT_A].history.return_value = {"messages": [], "next_cursor": "native"}
    async with connected(url) as client:
        args = {
            "account_id": ACCOUNT_A,
            "chat_id": "123",
            "query": "queue",
            "date_from": "2026-10-01",
            "date_to": "2026-10-26",
        }
        found = await client.call_tool("find_messages", args)
        assert not found.is_error
        live = found.structured_content["telegram"]
        assert live["next_cursor"] == "native"
        continued = await client.call_tool(live["cursor_tool"], {**args, "cursor": "native"})
        assert not continued.is_error
        assert manager.users[ACCOUNT_A].history.call_args.kwargs["date_to"] == "2026-10-26"


async def test_ingestion_policy_admin_scope_and_global_identity_boundary(endpoint):
    url, manager = endpoint
    manager.archive.discover(ACCOUNT_A, "-1001", "Synthetic", is_channel=True, chat_kind="group")
    args = dict(kind="group", rag_enabled=False, s3_enabled=True, content_types=["photo"])
    async with connected(url) as client:
        result = await client.call_tool("set_ingestion_policy", args)
        assert not result.is_error
        created = await client.call_tool(
            "create_agent_token",
            {"label": "Scoped admin", "scopes": ["admin"], "identity_ids": [ACCOUNT_A]},
        )
        token = created.structured_content["token"]
    async with connected(url, token=token) as client:
        assert (
            await client.call_tool("set_ingestion_policy", dict(args, content_types=["video"]))
        ).is_error
        assert manager.archive.ingestion.policy("group")["content_types"] == ["photo"]
        assert not (
            await client.call_tool(
                "set_ingestion_policy", dict(args, account_id=ACCOUNT_A, chat_id="-1001")
            )
        ).is_error
        assert (
            await client.call_tool(
                "get_ingestion_policy", {"account_id": ACCOUNT_B, "chat_id": "-1001"}
            )
        ).is_error
