from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from telethon import errors, functions, types

from tg_mcp.bot import BotGateway
from tg_mcp.errors import GatewayError
from tg_mcp.telegram import UserGateway


async def items(values):
    for value in values:
        yield value


class CallableClient(SimpleNamespace):
    async def __call__(self, request):
        return await self.raw_call(request)


def message(mid, *, at=None, outgoing=False, sender_id=7):
    return SimpleNamespace(
        id=mid,
        date=at or datetime(2026, 1, 1, tzinfo=UTC),
        message=f"message {mid}",
        sender_id=sender_id,
        out=outgoing,
        reply_to_msg_id=None,
        media=None,
    )


def user():
    peer = types.InputPeerUser(123, 456)
    client = CallableClient(
        is_user_authorized=AsyncMock(return_value=True),
        get_me=AsyncMock(return_value=SimpleNamespace(id=7, username="owner")),
        get_input_entity=AsyncMock(return_value=peer),
        get_messages=AsyncMock(),
        get_entity=AsyncMock(),
        iter_messages=Mock(),
        iter_dialogs=Mock(),
        iter_download=Mock(),
        download_media=AsyncMock(),
        send_message=AsyncMock(return_value=message(44, outgoing=True)),
        edit_message=AsyncMock(return_value=message(44, outgoing=True)),
        send_file=AsyncMock(return_value=message(45, outgoing=True)),
        forward_messages=AsyncMock(return_value=[message(46, outgoing=True)]),
        send_read_acknowledge=AsyncMock(return_value=True),
        raw_call=AsyncMock(),
    )
    return client, UserGateway(client, "t" * 43)


async def test_history_pagination_and_decimal_ids():
    client, gateway = user()
    client.iter_messages.return_value = items([message(9), message(8), message(7)])
    page = await gateway.history("123", limit=2)
    assert [m["id"] for m in page["messages"]] == ["9", "8"]
    assert page["next_cursor"]
    client.iter_messages.return_value = items([message(7)])
    page2 = await gateway.history("123", limit=2, cursor=page["next_cursor"])
    assert page2["next_cursor"] is None
    assert client.iter_messages.call_args.kwargs["offset_id"] == 8


async def test_search_cursor_is_bound_to_chat_and_query():
    client, gateway = user()
    client.iter_messages.return_value = items([message(9), message(8)])
    page = await gateway.history("123", limit=1, query="hello")
    with pytest.raises(GatewayError, match="invalid_cursor"):
        await gateway.history("123", limit=1, cursor=page["next_cursor"], query="other")


async def test_find_dialogs_matches_reordered_inflected_russian_name():
    client, gateway = user()
    dialogs = [
        SimpleNamespace(
            id=1,
            name="Дима Кривов",
            is_user=True,
            is_group=False,
            unread_count=0,
        ),
        SimpleNamespace(
            id=2,
            name="Другой контакт",
            is_user=True,
            is_group=False,
            unread_count=0,
        ),
        SimpleNamespace(
            id=3,
            name="Дима",
            is_user=True,
            is_group=False,
            unread_count=0,
        ),
    ]
    client.iter_dialogs.return_value = items(dialogs)

    result = await gateway.find_dialogs("Кривовым Димой", limit=5)

    assert [chat["title"] for chat in result["chats"]] == ["Дима Кривов", "Дима"]
    assert result["chats"][0]["match_score"] > result["chats"][1]["match_score"]
    assert client.iter_dialogs.call_args.kwargs["limit"] == 500

    client.iter_dialogs.return_value = items(dialogs)
    transliterated = await gateway.find_dialogs("Dima Krivov", limit=5)
    assert [chat["title"] for chat in transliterated["chats"]] == ["Дима Кривов", "Дима"]


async def test_history_filters_an_inclusive_date_range():
    client, gateway = user()
    client.iter_messages.return_value = items(
        [
            message(3, at=datetime(2026, 9, 30, 12, tzinfo=UTC)),
            message(2, at=datetime(2026, 9, 1, 0, tzinfo=UTC)),
            message(1, at=datetime(2026, 8, 31, 23, 59, tzinfo=UTC)),
        ]
    )

    result = await gateway.history("123", limit=10, date_from="2026-09-01", date_to="2026-09-30")

    assert [row["id"] for row in result["messages"]] == ["3", "2"]
    assert client.iter_messages.call_args.kwargs["offset_date"] == datetime(2026, 10, 1, tzinfo=UTC)


async def test_unread_inbox_filters_dialogs_and_includes_context():
    client, gateway = user()
    unread = SimpleNamespace(
        id=1,
        name="Unread",
        is_user=True,
        is_group=False,
        unread_count=2,
        unread_mentions_count=1,
        unread_reactions_count=0,
        message=message(9),
    )
    read = SimpleNamespace(
        id=2,
        name="Read",
        is_user=True,
        is_group=False,
        unread_count=0,
        unread_mentions_count=0,
        unread_reactions_count=0,
        message=message(8),
    )
    client.iter_dialogs.return_value = items([unread, read])

    result = await gateway.unread_inbox(limit=10)

    assert [row["title"] for row in result["chats"]] == ["Unread"]
    assert result["chats"][0]["unread_mentions_count"] == 1
    assert result["chats"][0]["last_message"]["id"] == "9"


async def test_inbox_context_prioritizes_mentions_and_includes_messages():
    client, gateway = user()
    mentioned = SimpleNamespace(
        id=1,
        name="Mentioned",
        is_user=False,
        is_group=True,
        unread_count=1,
        unread_mentions_count=1,
        unread_reactions_count=0,
        input_entity=types.InputPeerChat(1),
    )
    unread = SimpleNamespace(
        id=2,
        name="Unread",
        is_user=True,
        is_group=False,
        unread_count=9,
        unread_mentions_count=0,
        unread_reactions_count=0,
        input_entity=types.InputPeerUser(2, 3),
    )
    client.iter_dialogs.return_value = items([unread, mentioned])
    client.iter_messages.side_effect = [items([message(10)]), items([message(9)])]

    result = await gateway.inbox_context(limit=2, messages_per_chat=1)

    assert [row["title"] for row in result["chats"]] == ["Mentioned", "Unread"]
    assert result["chats"][0]["messages"][0]["id"] == "10"


async def test_folders_are_named_and_messages_merge_newest_first():
    client, gateway = user()
    folder = types.DialogFilter(
        id=3,
        title=types.TextWithEntities("ITQuick", []),
        pinned_peers=[],
        include_peers=[],
        exclude_peers=[],
        groups=False,
    )
    client.raw_call.side_effect = [
        types.messages.DialogFilters([folder]),
        types.messages.DialogFilters([folder]),
    ]
    first = SimpleNamespace(
        id=101,
        name="Alpha",
        is_user=False,
        is_group=True,
        unread_count=0,
        input_entity=types.InputPeerChat(101),
        entity=SimpleNamespace(contact=False, bot=False),
    )
    second = SimpleNamespace(
        id=202,
        name="Beta",
        is_user=True,
        is_group=False,
        unread_count=0,
        input_entity=types.InputPeerUser(202, 1),
        entity=SimpleNamespace(contact=False, bot=False),
    )
    folder.include_peers = [first.input_entity, second.input_entity]
    client.get_entity.return_value = [
        types.User(id=101, first_name="Alpha"),
        types.User(id=202, first_name="Beta"),
    ]
    client.iter_dialogs.return_value = items([first, second])
    client.iter_messages.side_effect = [
        items([message(1, at=datetime(2026, 9, 16, 8, tzinfo=UTC))]),
        items([message(2, at=datetime(2026, 9, 16, 10, tzinfo=UTC))]),
    ]

    folders = await gateway.list_folders()
    result = await gateway.folder_messages(
        "itq",
        limit=10,
        date_from="2026-09-16",
        date_to="2026-09-16",
        timezone_name="Europe/Madrid",
    )

    assert folders["folders"][0]["title"] == "ITQuick"
    assert [row["id"] for row in result["messages"]] == ["2", "1"]
    assert [row["chat_title"] for row in result["messages"]] == ["Beta", "Alpha"]
    client.iter_dialogs.assert_not_called()
    assert client.iter_messages.call_args.kwargs["offset_date"] == datetime(
        2026, 9, 16, 22, tzinfo=UTC
    )


async def test_reply_thread_and_live_update_cursor_are_bounded():
    client, gateway = user()
    target = message(10)
    target.reply_to_msg_id = 8
    parent = message(8)
    direct_reply = message(11)
    direct_reply.reply_to_msg_id = 10
    other = message(12)
    client.get_messages.side_effect = [target, parent]
    client.iter_messages.return_value = items([other, direct_reply])

    thread = await gateway.reply_thread("123", "10", ancestor_limit=2, reply_limit=2)
    first_poll = await gateway.poll_updates(None)
    await gateway._record_update("new_message", chat_id="123", message={"id": "13"})
    second_poll = await gateway.poll_updates(first_poll["next_cursor"])

    assert [row["id"] for row in thread["ancestors"]] == ["8"]
    assert [row["id"] for row in thread["replies"]] == ["11"]
    assert second_poll["updates"][0]["type"] == "new_message"


async def test_edit_schedule_list_and_cancel_messages():
    client, gateway = user()
    original = message(44, outgoing=True, sender_id=7)
    client.get_messages.return_value = original

    edited = await gateway.edit_own_message("123", "44", "updated")
    send_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    scheduled = await gateway.schedule_message("123", "later", send_at)
    client.raw_call.side_effect = [
        SimpleNamespace(messages=[message(44)]),
        SimpleNamespace(),
    ]
    listed = await gateway.scheduled_messages("123")
    cancelled = await gateway.cancel_scheduled_message("123", "44")

    assert edited["edited"] is True
    assert scheduled["scheduled"] is True
    assert listed["messages"][0]["id"] == "44"
    assert cancelled["cancelled"] is True
    assert isinstance(
        client.raw_call.call_args.args[0], functions.messages.DeleteScheduledMessagesRequest
    )


async def test_global_search_is_paginated_and_includes_chat_ids():
    client, gateway = user()
    found = [message(9), message(8), message(7)]
    for item in found:
        item.chat_id = -100123
    client.iter_messages.return_value = items(found)

    result = await gateway.search_all("needle", limit=2, media_kind="photo")

    assert [row["id"] for row in result["messages"]] == ["9", "8"]
    assert result["messages"][0]["chat_id"] == "-100123"
    assert result["next_cursor"]
    assert client.iter_messages.call_args.args == (None,)
    assert client.iter_messages.call_args.kwargs["filter"] is types.InputMessagesFilterPhotos


async def test_get_message_and_context_return_a_bounded_window():
    client, gateway = user()
    client.get_messages.return_value = message(10)
    client.iter_messages.side_effect = [items([message(9), message(8)]), items([message(11)])]

    one = await gateway.message("123", "10")
    context = await gateway.message_context("123", "10", before=2, after=1)

    assert one["message"]["id"] == "10"
    assert [row["id"] for row in context["messages"]] == ["8", "9", "10", "11"]
    assert client.iter_messages.call_args_list[1].kwargs["reverse"] is True


async def test_list_attachments_filters_out_messages_without_files():
    client, gateway = user()
    attached = message(9)
    attached.media = object()
    attached.file = SimpleNamespace(size=123, name="photo.jpg", mime_type="image/jpeg")
    plain = message(8)
    client.iter_messages.return_value = items([plain, attached])

    result = await gateway.attachments("123", limit=10, media_kind="any")

    assert [row["id"] for row in result["attachments"]] == ["9"]
    assert result["next_cursor"] is None


async def test_chat_info_and_message_links_are_normalized():
    client, gateway = user()
    client.get_entity.return_value = types.User(
        id=123, access_hash=456, first_name="Dima", username="dima_test", verified=True
    )

    info = await gateway.chat_info("123")
    public = await gateway.resolve_message_link("https://t.me/dima_test/77")
    private_topic = await gateway.resolve_message_link("https://t.me/c/123456/42/77")

    assert info["chat"] == {
        "id": "123",
        "title": "Dima",
        "kind": "user",
        "username": "dima_test",
        "verified": True,
        "bot": False,
        "forum": False,
        "participants_count": None,
    }
    assert public == {"chat_id": "123", "message_id": "77", "topic_id": None}
    assert private_topic == {"chat_id": "-100123456", "message_id": "77", "topic_id": "42"}


async def test_topics_and_mentions_use_telegram_filters():
    client, gateway = user()
    topic = types.ForumTopic(
        id=42,
        date=datetime(2026, 1, 1, tzinfo=UTC),
        peer=types.PeerChannel(123),
        title="Planning",
        icon_color=1,
        top_message=99,
        read_inbox_max_id=0,
        read_outbox_max_id=0,
        unread_count=3,
        unread_mentions_count=1,
        unread_reactions_count=0,
        unread_poll_votes_count=0,
        from_id=types.PeerUser(7),
        notify_settings=types.PeerNotifySettings(),
        pinned=True,
    )
    client.raw_call.return_value = SimpleNamespace(topics=[topic])

    topic_result = await gateway.topics("123", limit=10)
    assert topic_result["topics"][0]["title"] == "Planning"
    assert isinstance(client.raw_call.call_args.args[0], functions.messages.GetForumTopicsRequest)

    mentioned = message(9)
    mentioned.chat_id = 123
    client.iter_messages.return_value = items([mentioned])
    mention_result = await gateway.recent_mentions(limit=10, chat_id="123")
    assert mention_result["messages"][0]["chat_id"] == "123"
    assert client.iter_messages.call_args.kwargs["filter"] is types.InputMessagesFilterMyMentions


async def test_global_mentions_only_queries_dialogs_with_unread_mentions():
    client, gateway = user()
    peer = types.InputPeerUser(123, 456)
    client.iter_dialogs.return_value = items(
        [
            SimpleNamespace(id=123, unread_mentions_count=1, input_entity=peer),
            SimpleNamespace(id=456, unread_mentions_count=0, input_entity=object()),
        ]
    )
    mentioned = message(9)
    mentioned.chat_id = 123
    client.iter_messages.return_value = items([mentioned])

    result = await gateway.recent_mentions(limit=10)

    assert [row["id"] for row in result["messages"]] == ["9"]
    assert client.iter_messages.call_count == 1
    assert client.iter_messages.call_args.args == (peer,)


async def test_download_attachment_returns_bounded_bytes_and_safe_metadata():
    client, gateway = user()
    attached = SimpleNamespace(
        id=9,
        media=object(),
        file=SimpleNamespace(size=4, name="../photo.png", mime_type="image/png"),
    )
    client.get_messages.return_value = attached
    client.download_media.return_value = b"data"

    result = await gateway.download_attachment("123", "9")

    assert result == {
        "chat_id": "123",
        "message_id": "9",
        "file_name": "photo.png",
        "mime_type": "image/png",
        "size": 4,
        "data": b"data",
    }
    client.download_media.assert_awaited_once_with(attached, file=bytes)


async def test_inline_download_redirects_large_files_to_chunked_tool():
    client, gateway = user()
    client.get_messages.return_value = SimpleNamespace(
        id=9,
        media=object(),
        file=SimpleNamespace(size=10 * 1024 * 1024 + 1, name="large.bin", mime_type=None),
    )

    with pytest.raises(GatewayError, match="chunked_download_required"):
        await gateway.download_attachment("123", "9")

    client.download_media.assert_not_awaited()


async def test_download_attachment_chunk_reads_a_bounded_range():
    client, gateway = user()
    attached = SimpleNamespace(
        id=9,
        media=object(),
        file=SimpleNamespace(size=20 * 1024 * 1024, name="large.bin", mime_type=None),
    )
    client.get_messages.return_value = attached
    client.iter_download.return_value = items([b"abc", b"def"])

    result = await gateway.download_attachment_chunk("123", "9", offset=0, chunk_size=5)

    assert result["data"] == b"abcde"
    assert result["size"] == 5
    assert result["total_size"] == 20 * 1024 * 1024
    assert result["next_offset"] == 5
    assert result["complete"] is False


def test_message_includes_attachment_metadata():
    attached = message(9)
    attached.media = object()
    attached.file = SimpleNamespace(size=123, name="photo.jpg", mime_type="image/jpeg")

    result = UserGateway._message(attached)

    assert result["attachment"] == {
        "file_name": "photo.jpg",
        "mime_type": "image/jpeg",
        "size": 123,
    }


async def test_explicit_user_sender_plain_text():
    client, gateway = user()
    result = await gateway.send("123", "**text**", reply_to="12")
    assert result["sender"] == "user"
    assert result["sender_id"] == "7"
    assert result["message_id"] == "44"
    kwargs = client.send_message.call_args.kwargs
    assert kwargs["parse_mode"] is None
    assert "send_as" not in kwargs
    assert kwargs["reply_to"] == 12


async def test_channel_send_explicitly_uses_personal_identity():
    client, gateway = user()
    client.get_input_entity.return_value = types.InputPeerChannel(123, 456)

    await gateway.send("-100123", "text")

    assert isinstance(client.send_message.call_args.kwargs["send_as"], types.InputPeerSelf)


async def test_send_rereads_ambiguous_private_receipt_before_sender_mismatch():
    client, gateway = user()
    client.send_message.return_value = message(44, outgoing=True, sender_id=123)
    client.get_messages.return_value = message(44, outgoing=True, sender_id=7)

    result = await gateway.send("123", "text")

    assert result["sender_id"] == "7"
    client.get_messages.assert_awaited_once_with(types.InputPeerUser(123, 456), ids=44)


async def test_agent_actions_route_explicit_source_and_destination():
    client, gateway = user()
    source_peer = types.InputPeerUser(123, 456)
    destination_peer = types.InputPeerUser(789, 654)
    source_message = SimpleNamespace(
        id=9,
        media=object(),
        file=SimpleNamespace(size=4, name="photo.jpg", mime_type="image/jpeg"),
    )
    client.get_messages.return_value = source_message
    client.get_input_entity.side_effect = [source_peer, destination_peer]

    sent = await gateway.send_attachment("123", "9", "789", caption="caption", reply_to="12")

    assert sent["message_id"] == "45"
    assert client.send_file.call_args.args == (destination_peer, source_message.media)
    assert client.send_file.call_args.kwargs["caption"] == "caption"
    assert client.send_file.call_args.kwargs["reply_to"] == 12

    client.get_input_entity.side_effect = [source_peer, destination_peer]
    forwarded = await gateway.forward("123", ["9", "10"], "789")
    assert forwarded["message_ids"] == ["46"]
    client.forward_messages.assert_awaited_once_with(
        destination_peer, [9, 10], from_peer=source_peer
    )


async def test_mark_read_and_reaction_are_explicit_and_idempotent():
    client, gateway = user()

    read = await gateway.mark_read("123", "9")
    assert read["acknowledged"] is True
    client.send_read_acknowledge.assert_awaited_once_with(types.InputPeerUser(123, 456), max_id=9)

    await gateway.react("123", "9", "👍")
    request = client.raw_call.call_args.args[0]
    assert isinstance(request, functions.messages.SendReactionRequest)
    assert request.msg_id == 9
    assert request.reaction[0].emoticon == "👍"


async def test_rate_limit_is_sanitized():
    client, gateway = user()
    client.send_message.side_effect = errors.FloodWaitError(request=None, capture=37)
    with pytest.raises(GatewayError) as raised:
        await gateway.send("123", "private text")
    assert raised.value.code == "rate_limited"
    assert raised.value.retry_after == 37
    assert "private text" not in str(raised.value)


async def test_unknown_send_is_not_retried():
    client, gateway = user()
    client.send_message.side_effect = ConnectionError("secret session detail")
    with pytest.raises(GatewayError) as raised:
        await gateway.send("123", "private text")
    assert raised.value.code == "delivery_unknown"
    assert "secret" not in str(raised.value)
    assert client.send_message.await_count == 1


async def test_resolving_peer_failure_is_not_delivery_unknown():
    client, gateway = user()
    client.get_input_entity.side_effect = ConnectionError("secret")
    with pytest.raises(GatewayError) as raised:
        await gateway.send("123", "private text")
    assert raised.value.code == "unavailable"
    client.send_message.assert_not_awaited()


async def test_revoked_session():
    client, gateway = user()
    client.is_user_authorized.return_value = False
    with pytest.raises(GatewayError, match="not_authorized"):
        await gateway.history("123")


async def test_bot_sends_once_and_returns_actual_sender():
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 5,
                    "from": {"id": 999, "is_bot": True},
                    "chat": {"id": 123},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await BotGateway("999:" + "s" * 30, client).send("123", "hello")
    assert result == {"sender": "bot", "sender_id": "999", "chat_id": "123", "message_id": "5"}
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/sendMessage")


@pytest.mark.parametrize(
    "status, code",
    [(429, "rate_limited"), (403, "forbidden"), (401, "not_authorized"), (500, "delivery_unknown")],
)
async def test_bot_errors_are_safe(status, code):
    async def handle(request):
        return httpx.Response(
            status,
            json={
                "ok": False,
                "error_code": status,
                "description": "sensitive URL or message",
                "parameters": {"retry_after": 5},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(GatewayError) as raised:
            await BotGateway("999:" + "s" * 30, client).send("123", "hello")
    assert raised.value.code == code
    assert "sensitive" not in str(raised.value)


async def test_bot_timeout_is_uncertain_without_retry():
    requests = []

    async def handle(request):
        requests.append(request)
        raise httpx.ReadTimeout("token-secret", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(GatewayError, match="delivery_unknown"):
            await BotGateway("999:" + "s" * 30, client).send("123", "hello")
    assert len(requests) == 1


async def test_bot_channel_receipt_without_from():
    async def handle(request):
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 5,
                    "sender_chat": {"id": -100123},
                    "chat": {"id": -100123},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await BotGateway("999:" + "s" * 30, client).send("-100123", "hello")
    assert result["sender"] == "bot"
    assert result["sender_id"] == "-100123"
    assert result["message_id"] == "5"


async def test_dialog_pagination_keeps_pinned_entries():
    client, gateway = user()
    dialogs = [
        SimpleNamespace(id=i, name=str(i), is_user=True, is_group=False, unread_count=0)
        for i in [3, 1, 2]
    ]
    client.iter_dialogs.side_effect = lambda **kw: items(dialogs[: kw["limit"]])
    first = await gateway.dialogs(limit=1)
    second = await gateway.dialogs(limit=1, cursor=first["next_cursor"])
    third = await gateway.dialogs(limit=1, cursor=second["next_cursor"])
    assert [p["chats"][0]["id"] for p in [first, second, third]] == ["3", "1", "2"]
    assert third["next_cursor"] is None


@pytest.mark.parametrize("text", [" ", "😀" * 2049])
async def test_invalid_text_never_sent(text):
    client, gateway = user()
    with pytest.raises(GatewayError, match="invalid_request"):
        await gateway.send("123", text)
    client.send_message.assert_not_awaited()


async def test_unexpected_sender_is_reported_as_already_sent():
    client, gateway = user()
    client.send_message.return_value.sender_id = -100123
    with pytest.raises(GatewayError, match="sender_mismatch"):
        await gateway.send("123", "hello")
    assert client.send_message.await_count == 1


async def test_corrupt_cursor_never_reaches_telegram():
    client, gateway = user()
    with pytest.raises(GatewayError, match="invalid_cursor"):
        await gateway.history("123", cursor="not-a-valid-token")
    client.iter_messages.assert_not_called()
