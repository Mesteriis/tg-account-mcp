"""User-account operations, with bounded reads and explicit sender selection."""

import asyncio
import re
from collections import deque
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telethon import TelegramClient, events, functions, types, utils

from tg_mcp import __version__
from tg_mcp.config import Credentials
from tg_mcp.cursors import Cursors, query_context
from tg_mcp.errors import GatewayError, telegram_errors, validate_text
from tg_mcp.storage import StateStore

_WORDS = re.compile(r"\w+", re.UNICODE)
INLINE_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_CHUNK_BYTES = 4 * 1024 * 1024
MAX_GLOBAL_SCAN = 10_000
MAX_ATTACHMENT_SCAN = 2_000
MAX_FOLDER_CHATS = 100
MAX_FOLDER_RESULTS = 500
MAX_REPLY_SCAN = 500
_TELEGRAM_LINK_HOSTS = {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "kh",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "shch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def make_client(
    store: StateStore, credentials: Credentials, session_path: Path | None = None
) -> TelegramClient:
    session_path = store.prepare_session(session_path)
    return TelegramClient(
        str(session_path),
        credentials.api_id,
        credentials.api_hash.get_secret_value(),
        request_retries=0,
        connection_retries=3,
        retry_delay=1,
        flood_sleep_threshold=0,
        raise_last_call_error=True,
        device_model="Telegram MCP Server",
        app_version=__version__,
    )


class UserGateway:
    def __init__(
        self, client: TelegramClient, cursor_secret: str, identity_id: str = "acct_legacy"
    ):
        self.client = client
        self.identity_id = identity_id
        self.cursors = Cursors(cursor_secret)
        self._updates: deque[dict] = deque(maxlen=2_000)
        self._update_sequence = 0
        self._update_condition = asyncio.Condition()
        if hasattr(client, "add_event_handler"):
            client.add_event_handler(self._on_new_message, events.NewMessage())
            client.add_event_handler(self._on_edited_message, events.MessageEdited())
            client.add_event_handler(self._on_deleted_message, events.MessageDeleted())
            client.add_event_handler(self._on_read_message, events.MessageRead())
            client.add_event_handler(self._on_raw_update, events.Raw())

    async def _authorized(self) -> None:
        if not await self.client.is_user_authorized():
            raise GatewayError("not_authorized", "Run tg-mcp login on the server.")

    async def status(self) -> dict:
        with telegram_errors():
            authorized = await self.client.is_user_authorized()
            if not authorized:
                return {"authorized": False}
            me = await self.client.get_me()
            return {"authorized": True, "id": str(me.id), "username": me.username}

    async def dialogs(self, limit: int = 50, cursor: str | None = None) -> dict:
        offset = self.cursors.decode(cursor, "dialogs", self.identity_id)
        # Telethon's dialog order includes pins and folders. Positional pagination preserves
        # that ordering without dropping pinned dialogs at a keyset boundary.
        if offset > 10000:
            raise GatewayError("pagination_limit", "Dialog listing is limited to 10,000 positions.")
        with telegram_errors():
            await self._authorized()
            rows = []
            index = 0
            async for dialog in self.client.iter_dialogs(limit=offset + limit + 1):
                if index >= offset:
                    rows.append(self._dialog(dialog))
                index += 1
        has_more = len(rows) > limit
        return {
            "chats": rows[:limit],
            "next_cursor": self.cursors.encode("dialogs", self.identity_id, offset + limit)
            if has_more
            else None,
        }

    async def find_dialogs(self, query: str, limit: int = 20) -> dict:
        query_terms = self._terms(query)
        if not query_terms or len(query) > 256:
            raise GatewayError("invalid_request", "Chat query must contain 1 to 256 characters.")
        with telegram_errors():
            await self._authorized()
            ranked = []
            normalized_query = " ".join(query_terms)
            index = 0
            async for dialog in self.client.iter_dialogs(limit=500):
                title = dialog.name or ""
                title_terms = self._terms(title)
                normalized_title = " ".join(title_terms)
                exact = normalized_query in normalized_title
                matched_terms = sum(
                    any(
                        query_term == title_term
                        or (
                            len(query_term) >= 3
                            and len(title_term) >= 3
                            and query_term[:3] == title_term[:3]
                        )
                        for title_term in title_terms
                    )
                    for query_term in query_terms
                )
                if exact or matched_terms:
                    row = self._dialog(dialog)
                    row["match_score"] = round(matched_terms / len(query_terms), 2)
                    ranked.append((exact, matched_terms, -index, row))
                index += 1
        ranked.sort(reverse=True, key=lambda item: item[:3])
        return {"query": query, "chats": [item[3] for item in ranked[:limit]]}

    async def unread_inbox(self, limit: int = 50, cursor: str | None = None) -> dict:
        offset = self.cursors.decode(cursor, "unread", self.identity_id)
        if offset > MAX_GLOBAL_SCAN:
            raise GatewayError("pagination_limit", "Unread listing is limited to 10,000 dialogs.")
        with telegram_errors():
            await self._authorized()
            rows = []
            scanned = 0
            async for dialog in self.client.iter_dialogs(limit=MAX_GLOBAL_SCAN):
                if scanned < offset:
                    scanned += 1
                    continue
                scanned += 1
                unread = int(getattr(dialog, "unread_count", 0) or 0)
                mentions = int(getattr(dialog, "unread_mentions_count", 0) or 0)
                reactions = int(getattr(dialog, "unread_reactions_count", 0) or 0)
                if unread or mentions or reactions:
                    row = self._dialog(dialog)
                    row.update(
                        {
                            "unread_mentions_count": mentions,
                            "unread_reactions_count": reactions,
                            "last_message": self._message(dialog.message)
                            if getattr(dialog, "message", None)
                            else None,
                        }
                    )
                    rows.append((scanned, row))
                    if len(rows) > limit:
                        break
        visible = rows[:limit]
        return {
            "chats": [row for _, row in visible],
            "next_cursor": (
                self.cursors.encode("unread", self.identity_id, visible[-1][0])
                if len(rows) > limit
                else None
            ),
        }

    async def inbox_context(self, limit: int = 10, messages_per_chat: int = 5) -> dict:
        with telegram_errors():
            await self._authorized()
            dialogs = []
            async for dialog in self.client.iter_dialogs(limit=500):
                unread = int(getattr(dialog, "unread_count", 0) or 0)
                mentions = int(getattr(dialog, "unread_mentions_count", 0) or 0)
                reactions = int(getattr(dialog, "unread_reactions_count", 0) or 0)
                if not (unread or mentions or reactions):
                    continue
                dialogs.append((mentions > 0, reactions > 0, unread, dialog))
            dialogs.sort(key=lambda row: row[:3], reverse=True)
            rows = []
            for _, _, _, dialog in dialogs[:limit]:
                messages = [
                    message
                    async for message in self.client.iter_messages(
                        dialog.input_entity, limit=messages_per_chat
                    )
                ]
                rows.append(
                    {
                        **self._dialog(dialog),
                        "unread_mentions_count": int(
                            getattr(dialog, "unread_mentions_count", 0) or 0
                        ),
                        "unread_reactions_count": int(
                            getattr(dialog, "unread_reactions_count", 0) or 0
                        ),
                        "messages": [self._message(message) for message in messages],
                    }
                )
        return {"chats": rows}

    async def list_folders(self) -> dict:
        folders = await self._folders()
        return {
            "folders": [
                {
                    "id": str(folder.id),
                    "title": self._folder_title(folder),
                    "kind": (
                        "shared" if isinstance(folder, types.DialogFilterChatlist) else "personal"
                    ),
                    "include_contacts": bool(getattr(folder, "contacts", False)),
                    "include_groups": bool(getattr(folder, "groups", False)),
                    "include_channels": bool(getattr(folder, "broadcasts", False)),
                    "include_bots": bool(getattr(folder, "bots", False)),
                    "exclude_muted": bool(getattr(folder, "exclude_muted", False)),
                    "exclude_read": bool(getattr(folder, "exclude_read", False)),
                    "exclude_archived": bool(getattr(folder, "exclude_archived", False)),
                }
                for folder in folders
            ]
        }

    async def folder_messages(
        self,
        folder: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        query: str | None = None,
        timezone_name: str = "UTC",
    ) -> dict:
        start, end = self._date_bounds(date_from, date_to, timezone_name)
        selected = await self._resolve_folder(folder)
        folder_id = str(selected.id)
        filters = f"{folder_id}|{query or ''}|{date_from or ''}|{date_to or ''}|{timezone_name}"
        context = query_context(self.identity_id, filters)
        offset = self.cursors.decode(cursor, "folder_messages", context)
        if offset + limit > MAX_FOLDER_RESULTS:
            raise GatewayError(
                "pagination_limit", "Folder message listing is limited to 500 results."
            )
        wanted = offset + limit + 1
        with telegram_errors():
            await self._authorized()
            explicit_peers = self._folder_explicit_peers(selected)
            if not self._folder_has_automatic_rules(selected):
                visible_peers = explicit_peers[: MAX_FOLDER_CHATS + 1]
                entities = await self.client.get_entity(visible_peers) if visible_peers else []
                if not isinstance(entities, list):
                    entities = [entities]
                matched_dialogs = [
                    SimpleNamespace(
                        id=utils.get_peer_id(peer),
                        name=utils.get_display_name(entity),
                        input_entity=peer,
                    )
                    for peer, entity in zip(visible_peers, entities, strict=True)
                ]
            else:
                matched_dialogs = []
                async for dialog in self.client.iter_dialogs(limit=MAX_GLOBAL_SCAN):
                    if self._dialog_matches_folder(dialog, selected):
                        matched_dialogs.append(dialog)
                        if len(matched_dialogs) > MAX_FOLDER_CHATS:
                            break
            dialogs = matched_dialogs[:MAX_FOLDER_CHATS]
        semaphore = asyncio.Semaphore(8)

        async def read_dialog(dialog):
            async with semaphore:
                kwargs = {"limit": wanted, "search": query}
                if end is not None:
                    kwargs["offset_date"] = end
                local_rows = []
                try:
                    with telegram_errors():
                        async for message in self.client.iter_messages(
                            dialog.input_entity, **kwargs
                        ):
                            if start is not None and message.date < start:
                                break
                            if end is not None and message.date >= end:
                                continue
                            row = self._message(message, include_chat=True)
                            row["chat_id"] = str(dialog.id)
                            row["chat_title"] = dialog.name
                            local_rows.append((message.date, row))
                    return local_rows, None
                except GatewayError as exc:
                    return [], {"chat_id": str(dialog.id), "code": exc.code}

        results = await asyncio.gather(*(read_dialog(dialog) for dialog in dialogs))
        rows = [row for local_rows, _ in results for row in local_rows]
        skipped_chats = [skipped for _, skipped in results if skipped is not None]
        rows.sort(key=lambda item: item[0], reverse=True)
        visible = rows[offset : offset + limit]
        return {
            "folder": {"id": folder_id, "title": self._folder_title(selected)},
            "messages": [row for _, row in visible],
            "next_cursor": self.cursors.encode("folder_messages", context, offset + limit)
            if len(rows) > offset + limit
            else None,
            "scanned_chats": len(dialogs),
            "skipped_chats": skipped_chats,
            "partial": len(matched_dialogs) > MAX_FOLDER_CHATS,
        }

    async def history(
        self,
        chat_id: str,
        limit: int = 50,
        cursor: str | None = None,
        query: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        start, end = self._date_bounds(date_from, date_to)
        filters = f"{query or ''}|{date_from or ''}|{date_to or ''}"
        context = query_context(self.identity_id, query_context(chat_id, filters))
        offset = self.cursors.decode(cursor, "messages", context)
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            kwargs = {"limit": limit + 1, "offset_id": offset, "search": query}
            if end is not None:
                kwargs["offset_date"] = end
            rows = []
            async for message in self.client.iter_messages(peer, **kwargs):
                if start is not None and message.date < start:
                    break
                if end is None or message.date < end:
                    rows.append(message)
        visible = rows[:limit]
        return {
            "chat_id": chat_id,
            "messages": [self._message(message) for message in visible],
            "next_cursor": (
                self.cursors.encode("messages", context, visible[-1].id)
                if len(rows) > limit
                else None
            ),
        }

    async def search_all(
        self,
        query: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sender_id: str | None = None,
        media_kind: str | None = None,
    ) -> dict:
        start, end = self._date_bounds(date_from, date_to)
        filters = f"{query}|{date_from or ''}|{date_to or ''}|{sender_id or ''}|{media_kind or ''}"
        context = query_context(self.identity_id, filters)
        offset = self.cursors.decode(cursor, "global_messages", context)
        if offset > MAX_GLOBAL_SCAN:
            raise GatewayError("pagination_limit", "Global search is limited to 10,000 results.")
        with telegram_errors():
            await self._authorized()
            from_user = (
                await self.client.get_input_entity(int(sender_id))
                if sender_id is not None
                else None
            )
            kwargs = {
                "limit": offset + limit + 1,
                "search": query,
                "from_user": from_user,
                "filter": self._media_filter(media_kind),
            }
            if end is not None:
                kwargs["offset_date"] = end
            rows = []
            matched = 0
            async for message in self.client.iter_messages(None, **kwargs):
                if start is not None and message.date < start:
                    break
                if end is not None and message.date >= end:
                    continue
                if matched >= offset:
                    rows.append(message)
                matched += 1
                if len(rows) > limit:
                    break
        visible = rows[:limit]
        return {
            "query": query,
            "messages": [self._message(message, include_chat=True) for message in visible],
            "next_cursor": (
                self.cursors.encode("global_messages", context, offset + limit)
                if len(rows) > limit
                else None
            ),
        }

    async def message(self, chat_id: str, message_id: str) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            message = await self.client.get_messages(peer, ids=int(message_id))
            if message is None:
                raise GatewayError("message_not_found", "Message was not found.")
            return {"chat_id": chat_id, "message": self._message(message)}

    async def message_context(
        self, chat_id: str, message_id: str, *, before: int = 5, after: int = 5
    ) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            target = await self.client.get_messages(peer, ids=int(message_id))
            if target is None:
                raise GatewayError("message_not_found", "Message was not found.")
            older = [
                item
                async for item in self.client.iter_messages(
                    peer, limit=before, offset_id=int(message_id)
                )
            ]
            newer = [
                item
                async for item in self.client.iter_messages(
                    peer, limit=after, min_id=int(message_id), reverse=True
                )
            ]
        ordered = list(reversed(older)) + [target] + newer
        return {
            "chat_id": chat_id,
            "target_message_id": message_id,
            "messages": [self._message(item) for item in ordered],
        }

    async def attachments(
        self,
        chat_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
        media_kind: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        start, end = self._date_bounds(date_from, date_to)
        filters = f"{media_kind or ''}|{date_from or ''}|{date_to or ''}"
        context = query_context(self.identity_id, query_context(chat_id, filters))
        offset_id = self.cursors.decode(cursor, "attachments", context)
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            telegram_filter = self._media_filter(media_kind)
            kwargs = {
                "limit": limit + 1 if telegram_filter is not None else MAX_ATTACHMENT_SCAN,
                "offset_id": offset_id,
                "filter": telegram_filter,
            }
            if end is not None:
                kwargs["offset_date"] = end
            rows = []
            last_scanned = None
            scanned = 0
            async for message in self.client.iter_messages(peer, **kwargs):
                last_scanned = message.id
                scanned += 1
                if start is not None and message.date < start:
                    break
                if end is not None and message.date >= end:
                    continue
                if getattr(message, "file", None) is not None:
                    rows.append(message)
                    if len(rows) > limit:
                        break
        visible = rows[:limit]
        has_more = len(rows) > limit or (
            telegram_filter is None and scanned >= MAX_ATTACHMENT_SCAN and last_scanned is not None
        )
        next_offset = visible[-1].id if len(rows) > limit and visible else last_scanned
        return {
            "chat_id": chat_id,
            "kind": media_kind or "any",
            "attachments": [self._message(item) for item in visible],
            "next_cursor": (
                self.cursors.encode("attachments", context, next_offset)
                if has_more and next_offset
                else None
            ),
        }

    async def chat_info(self, chat_id: str) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            entity = await self.client.get_entity(peer)
        kind = (
            "user"
            if isinstance(entity, types.User)
            else "group"
            if isinstance(entity, types.Chat) or getattr(entity, "megagroup", False)
            else "channel"
        )
        return {
            "chat": {
                "id": str(utils.get_peer_id(entity)),
                "title": utils.get_display_name(entity),
                "kind": kind,
                "username": getattr(entity, "username", None),
                "verified": bool(getattr(entity, "verified", False)),
                "bot": bool(getattr(entity, "bot", False)),
                "forum": bool(getattr(entity, "forum", False)),
                "participants_count": getattr(entity, "participants_count", None),
            }
        }

    async def resolve_message_link(self, link: str) -> dict:
        try:
            parsed = urlsplit(link)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname not in _TELEGRAM_LINK_HOSTS
            ):
                raise ValueError
            parts = [part for part in parsed.path.split("/") if part]
            if parts and parts[0] == "s":
                parts = parts[1:]
            if not parts:
                raise ValueError
            if parts[0] == "c":
                if len(parts) not in {3, 4}:
                    raise ValueError
                channel_id = int(parts[1])
                if channel_id < 1:
                    raise ValueError
                chat_id = f"-100{channel_id}"
                message_id = int(parts[-1])
                topic_id = int(parts[-2]) if len(parts) == 4 else None
            else:
                if len(parts) not in {2, 3}:
                    raise ValueError
                message_id = int(parts[-1])
                topic_id = int(parts[-2]) if len(parts) == 3 else None
                if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", parts[0]):
                    raise ValueError
                with telegram_errors():
                    await self._authorized()
                    peer = await self.client.get_input_entity(parts[0])
                chat_id = str(utils.get_peer_id(peer))
            if message_id < 1 or (topic_id is not None and topic_id < 1):
                raise ValueError
        except (TypeError, ValueError):
            raise GatewayError(
                "invalid_request", "Use a public or private t.me message link."
            ) from None
        return {
            "chat_id": chat_id,
            "message_id": str(message_id),
            "topic_id": str(topic_id) if topic_id else None,
        }

    async def topics(self, chat_id: str, limit: int = 50, cursor: str | None = None) -> dict:
        context = query_context(self.identity_id, chat_id)
        offset_topic = self.cursors.decode(cursor, "topics", context)
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            result = await self.client(
                functions.messages.GetForumTopicsRequest(
                    peer=peer,
                    offset_date=None,
                    offset_id=0,
                    offset_topic=offset_topic,
                    limit=limit,
                )
            )
        topics = [topic for topic in result.topics if isinstance(topic, types.ForumTopic)]
        rows = [
            {
                "id": str(topic.id),
                "title": topic.title,
                "top_message_id": str(topic.top_message),
                "unread_count": topic.unread_count,
                "unread_mentions_count": topic.unread_mentions_count,
                "closed": bool(topic.closed),
                "pinned": bool(topic.pinned),
            }
            for topic in topics
        ]
        has_more = len(topics) == limit and bool(topics)
        return {
            "chat_id": chat_id,
            "topics": rows,
            "next_cursor": self.cursors.encode("topics", context, topics[-1].id)
            if has_more
            else None,
        }

    async def recent_mentions(
        self, *, limit: int = 50, cursor: str | None = None, chat_id: str | None = None
    ) -> dict:
        context = query_context(self.identity_id, chat_id or "all")
        offset = self.cursors.decode(cursor, "mentions", context)
        if offset > MAX_GLOBAL_SCAN:
            raise GatewayError("pagination_limit", "Mention listing is limited to 10,000 results.")
        with telegram_errors():
            await self._authorized()
            wanted = offset + limit + 1
            if chat_id:
                peer = await self.client.get_input_entity(int(chat_id))
                rows = [
                    message
                    async for message in self.client.iter_messages(
                        peer,
                        limit=wanted,
                        filter=types.InputMessagesFilterMyMentions,
                    )
                ]
            else:
                rows = []
                async for dialog in self.client.iter_dialogs(limit=500):
                    mention_count = int(getattr(dialog, "unread_mentions_count", 0) or 0)
                    if mention_count < 1:
                        continue
                    peer = getattr(dialog, "input_entity", None)
                    if peer is None:
                        peer = await self.client.get_input_entity(dialog.id)
                    rows.extend(
                        [
                            message
                            async for message in self.client.iter_messages(
                                peer,
                                limit=min(mention_count, wanted),
                                filter=types.InputMessagesFilterMyMentions,
                            )
                        ]
                    )
                rows.sort(key=lambda item: item.date, reverse=True)
        visible = rows[offset : offset + limit]
        return {
            "chat_id": chat_id,
            "messages": [self._message(item, include_chat=True) for item in visible],
            "next_cursor": self.cursors.encode("mentions", context, offset + limit)
            if len(rows) > offset + limit
            else None,
        }

    async def reply_thread(
        self,
        chat_id: str,
        message_id: str,
        *,
        ancestor_limit: int = 20,
        reply_limit: int = 50,
    ) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            target = await self.client.get_messages(peer, ids=int(message_id))
            if target is None:
                raise GatewayError("message_not_found", "Message was not found.")
            ancestors = []
            current = target
            visited = {target.id}
            while current.reply_to_msg_id and len(ancestors) < ancestor_limit:
                parent_id = current.reply_to_msg_id
                if parent_id in visited:
                    break
                parent = await self.client.get_messages(peer, ids=parent_id)
                if parent is None:
                    break
                ancestors.append(parent)
                visited.add(parent.id)
                current = parent
            replies = []
            scanned = 0
            async for candidate in self.client.iter_messages(peer, limit=MAX_REPLY_SCAN):
                scanned += 1
                if candidate.reply_to_msg_id == target.id:
                    replies.append(candidate)
                    if len(replies) >= reply_limit:
                        break
        ancestors.reverse()
        return {
            "chat_id": chat_id,
            "target": self._message(target),
            "ancestors": [self._message(item) for item in ancestors],
            "replies": [self._message(item) for item in reversed(replies)],
            "partial": scanned == MAX_REPLY_SCAN and len(replies) < reply_limit,
        }

    async def conversation_snapshot(self, chat_id: str, message_limit: int = 20) -> dict:
        info = await self.chat_info(chat_id)
        history = await self.history(chat_id, limit=message_limit)
        with telegram_errors():
            peer = await self.client.get_input_entity(int(chat_id))
            pinned = [
                message
                async for message in self.client.iter_messages(
                    peer, limit=1, filter=types.InputMessagesFilterPinned
                )
            ]
        return {
            **info,
            "messages": history["messages"],
            "pinned_message": self._message(pinned[0]) if pinned else None,
        }

    async def resolve_peer(self, value: str, limit: int = 10) -> dict:
        candidate = value.strip()
        if not candidate:
            raise GatewayError("invalid_request", "Peer query must not be empty.")
        with telegram_errors():
            await self._authorized()
            direct = None
            if re.fullmatch(r"-?[1-9][0-9]{0,18}", candidate):
                direct = await self.client.get_input_entity(int(candidate))
            elif candidate.startswith("@") and re.fullmatch(r"@[A-Za-z0-9_]{5,32}", candidate):
                direct = await self.client.get_input_entity(candidate[1:])
            else:
                parsed = urlsplit(candidate)
                if parsed.hostname in _TELEGRAM_LINK_HOSTS:
                    parts = [part for part in parsed.path.split("/") if part]
                    if parts and parts[0] == "s":
                        parts = parts[1:]
                    if parts and parts[0] != "c":
                        direct = await self.client.get_input_entity(parts[0])
            if direct is not None:
                entity = await self.client.get_entity(direct)
                return {"query": value, "chats": [self._entity_row(entity)]}
        return await self.find_dialogs(candidate, limit=limit)

    async def special_messages(
        self,
        chat_id: str,
        kind: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict:
        filters = {
            "link": types.InputMessagesFilterUrl,
            "poll": types.InputMessagesFilterPoll,
            "gif": types.InputMessagesFilterGif,
            "video_note": types.InputMessagesFilterRoundVideo,
            "voice": types.InputMessagesFilterVoice,
            "pinned": types.InputMessagesFilterPinned,
        }
        try:
            telegram_filter = filters[kind]
        except KeyError:
            raise GatewayError(
                "invalid_request", "Kind must be link, poll, gif, video_note, voice or pinned."
            ) from None
        context = query_context(self.identity_id, query_context(chat_id, kind))
        offset = self.cursors.decode(cursor, "special_messages", context)
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            rows = [
                message
                async for message in self.client.iter_messages(
                    peer, limit=limit + 1, offset_id=offset, filter=telegram_filter
                )
            ]
        visible = rows[:limit]
        return {
            "chat_id": chat_id,
            "kind": kind,
            "messages": [self._message(item) for item in visible],
            "next_cursor": self.cursors.encode("special_messages", context, visible[-1].id)
            if len(rows) > limit
            else None,
        }

    async def poll_updates(
        self, cursor: str | None, *, limit: int = 100, timeout_seconds: int = 0
    ) -> dict:
        await self._authorized()
        if cursor is None:
            offset = self._update_sequence
        else:
            offset = self.cursors.decode(cursor, "updates", self.identity_id)

        async def available() -> list[dict]:
            if self._updates and offset < self._updates[0]["sequence"] - 1:
                raise GatewayError(
                    "cursor_expired", "Update cursor is older than the retained event window."
                )
            return [event.copy() for event in self._updates if event["sequence"] > offset][:limit]

        rows = await available()
        if not rows and timeout_seconds:
            try:
                async with self._update_condition:
                    await asyncio.wait_for(self._update_condition.wait(), timeout=timeout_seconds)
            except TimeoutError:
                pass
            rows = await available()
        next_sequence = rows[-1]["sequence"] if rows else offset
        return {
            "updates": rows,
            "next_cursor": self.cursors.encode("updates", self.identity_id, next_sequence),
        }

    @staticmethod
    def _terms(value: str) -> list[str]:
        return [term.casefold().translate(_CYRILLIC_TO_LATIN) for term in _WORDS.findall(value)]

    @staticmethod
    def _date_bounds(
        date_from: str | None, date_to: str | None, timezone_name: str = "UTC"
    ) -> tuple[datetime | None, datetime | None]:
        try:
            start_date = date.fromisoformat(date_from) if date_from else None
            end_date = date.fromisoformat(date_to) if date_to else None
            zone = ZoneInfo(timezone_name)
        except (ValueError, ZoneInfoNotFoundError):
            raise GatewayError(
                "invalid_request", "Dates must use YYYY-MM-DD and timezone must be an IANA name."
            ) from None
        if start_date and end_date and start_date > end_date:
            raise GatewayError("invalid_request", "date_from must not be after date_to.")
        start = datetime.combine(start_date, time.min, zone).astimezone(UTC) if start_date else None
        end = (
            datetime.combine(end_date + timedelta(days=1), time.min, zone).astimezone(UTC)
            if end_date
            else None
        )
        return start, end

    @staticmethod
    def _dialog(dialog) -> dict:
        return {
            "id": str(dialog.id),
            "title": dialog.name,
            "kind": ("user" if dialog.is_user else "group" if dialog.is_group else "channel"),
            "unread_count": dialog.unread_count,
        }

    async def send(self, chat_id: str, text: str, reply_to: str | None = None) -> dict:
        validate_text(text)
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            me = await self.client.get_me()
        with telegram_errors(sending=True):
            message = await self.client.send_message(
                peer,
                text,
                reply_to=int(reply_to) if reply_to else None,
                parse_mode=None,
                link_preview=False,
                **self._send_as_self(peer),
            )
        if message is None:
            raise GatewayError(
                "delivery_unknown", "No message receipt. Check history before retrying."
            )
        message = await self._verify_personal_sender(peer, message, me.id)
        return {
            "sender": "user",
            "sender_id": str(message.sender_id),
            "chat_id": str(utils.get_peer_id(peer)),
            "message_id": str(message.id),
        }

    async def edit_own_message(self, chat_id: str, message_id: str, text: str) -> dict:
        validate_text(text)
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            me = await self.client.get_me()
            original = await self.client.get_messages(peer, ids=int(message_id))
            if original is None:
                raise GatewayError("message_not_found", "Message was not found.")
            if not original.out or original.sender_id != me.id:
                raise GatewayError("forbidden", "Only messages sent by this account can be edited.")
        with telegram_errors(sending=True):
            edited = await self.client.edit_message(
                peer,
                int(message_id),
                text,
                parse_mode=None,
                link_preview=False,
            )
        if edited is None:
            raise GatewayError(
                "delivery_unknown", "No edit receipt. Check the message before retrying."
            )
        return {
            "sender": "user",
            "sender_id": str(me.id),
            "chat_id": chat_id,
            "message_id": str(edited.id),
            "edited": True,
        }

    async def schedule_message(
        self,
        chat_id: str,
        text: str,
        send_at: str,
        *,
        reply_to: str | None = None,
    ) -> dict:
        validate_text(text)
        try:
            when = datetime.fromisoformat(send_at.replace("Z", "+00:00"))
            if when.tzinfo is None:
                raise ValueError
            when = when.astimezone(UTC)
        except (TypeError, ValueError):
            raise GatewayError(
                "invalid_request", "send_at must be an ISO 8601 timestamp with timezone."
            ) from None
        now = datetime.now(UTC)
        if when <= now + timedelta(seconds=10) or when > now + timedelta(days=365):
            raise GatewayError(
                "invalid_request", "Scheduled time must be 10 seconds to 365 days in the future."
            )
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
        with telegram_errors(sending=True):
            message = await self.client.send_message(
                peer,
                text,
                reply_to=int(reply_to) if reply_to else None,
                parse_mode=None,
                link_preview=False,
                schedule=when,
                **self._send_as_self(peer),
            )
        if message is None:
            raise GatewayError(
                "delivery_unknown", "No schedule receipt. Check scheduled messages before retrying."
            )
        return {
            "sender": "user",
            "chat_id": chat_id,
            "message_id": str(message.id),
            "send_at": when.isoformat(),
            "scheduled": True,
        }

    async def scheduled_messages(self, chat_id: str) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            result = await self.client(
                functions.messages.GetScheduledHistoryRequest(peer=peer, hash=0)
            )
        messages = getattr(result, "messages", [])
        return {
            "chat_id": chat_id,
            "messages": [self._message(message) for message in messages],
        }

    async def cancel_scheduled_message(self, chat_id: str, message_id: str) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
        with telegram_errors(sending=True):
            await self.client(
                functions.messages.DeleteScheduledMessagesRequest(peer=peer, id=[int(message_id)])
            )
        return {"chat_id": chat_id, "message_id": message_id, "cancelled": True}

    async def send_attachment(
        self,
        source_chat_id: str,
        source_message_id: str,
        chat_id: str,
        *,
        caption: str | None = None,
        reply_to: str | None = None,
    ) -> dict:
        if caption is not None:
            validate_text(caption)
        with telegram_errors():
            source, _, _ = await self._attachment(source_chat_id, source_message_id)
            peer = await self.client.get_input_entity(int(chat_id))
            me = await self.client.get_me()
        with telegram_errors(sending=True):
            message = await self.client.send_file(
                peer,
                source.media,
                caption=caption or "",
                reply_to=int(reply_to) if reply_to else None,
                parse_mode=None,
                **self._send_as_self(peer),
            )
        if message is None:
            raise GatewayError(
                "delivery_unknown", "No message receipt. Check history before retrying."
            )
        message = await self._verify_personal_sender(peer, message, me.id)
        return {
            "sender": "user",
            "sender_id": str(message.sender_id),
            "chat_id": str(utils.get_peer_id(peer)),
            "message_id": str(message.id),
        }

    async def forward(self, source_chat_id: str, message_ids: list[str], chat_id: str) -> dict:
        with telegram_errors():
            await self._authorized()
            source = await self.client.get_input_entity(int(source_chat_id))
            destination = await self.client.get_input_entity(int(chat_id))
        with telegram_errors(sending=True):
            messages = await self.client.forward_messages(
                destination, [int(message_id) for message_id in message_ids], from_peer=source
            )
        if not isinstance(messages, list):
            messages = [messages]
        if not messages or any(message is None for message in messages):
            raise GatewayError(
                "delivery_unknown", "Forward receipt is incomplete. Check history before retrying."
            )
        return {
            "sender": "user",
            "chat_id": str(utils.get_peer_id(destination)),
            "message_ids": [str(message.id) for message in messages],
        }

    async def mark_read(self, chat_id: str, message_id: str | None = None) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
            acknowledged = await self.client.send_read_acknowledge(
                peer, max_id=int(message_id) if message_id else None
            )
        return {"chat_id": chat_id, "message_id": message_id, "acknowledged": bool(acknowledged)}

    async def react(self, chat_id: str, message_id: str, emoji: str | None) -> dict:
        with telegram_errors():
            await self._authorized()
            peer = await self.client.get_input_entity(int(chat_id))
        with telegram_errors(sending=True):
            await self.client(
                functions.messages.SendReactionRequest(
                    peer=peer,
                    msg_id=int(message_id),
                    reaction=[types.ReactionEmoji(emoticon=emoji)] if emoji else [],
                )
            )
        return {"chat_id": chat_id, "message_id": message_id, "reaction": emoji}

    async def download_attachment(self, chat_id: str, message_id: str) -> dict:
        with telegram_errors():
            message, file, size = await self._attachment(chat_id, message_id)
            if size > INLINE_ATTACHMENT_BYTES:
                raise GatewayError(
                    "chunked_download_required",
                    "Use download_attachment_chunk for attachments larger than 10 MB.",
                )
            data = await self.client.download_media(message, file=bytes)
            if not isinstance(data, bytes):
                raise GatewayError("attachment_unavailable", "Attachment could not be downloaded.")
            if len(data) > INLINE_ATTACHMENT_BYTES:
                raise GatewayError(
                    "chunked_download_required",
                    "Use download_attachment_chunk for attachments larger than 10 MB.",
                )

        file_name = self._file_name(file, message_id)
        return {
            "chat_id": chat_id,
            "message_id": message_id,
            "file_name": file_name,
            "mime_type": getattr(file, "mime_type", None) or "application/octet-stream",
            "size": len(data),
            "data": data,
        }

    async def download_attachment_chunk(
        self, chat_id: str, message_id: str, *, offset: int, chunk_size: int
    ) -> dict:
        if offset < 0 or chunk_size < 1 or chunk_size > MAX_ATTACHMENT_CHUNK_BYTES:
            raise GatewayError(
                "invalid_request", "Offset must be non-negative and chunk size 1–4 MB."
            )
        with telegram_errors():
            message, file, total_size = await self._attachment(chat_id, message_id)
            if offset >= total_size:
                raise GatewayError("invalid_request", "Offset is outside the attachment.")
            wanted = min(chunk_size, total_size - offset)
            request_size = min(512 * 1024, wanted)
            chunk_count = (wanted + request_size - 1) // request_size
            content = bytearray()
            async for chunk in self.client.iter_download(
                message.media,
                offset=offset,
                limit=chunk_count,
                chunk_size=request_size,
                request_size=request_size,
                file_size=total_size,
            ):
                content.extend(chunk)
            data = bytes(content[:wanted])
            if not data:
                raise GatewayError("attachment_unavailable", "Attachment chunk is unavailable.")

        next_offset = offset + len(data)
        return {
            "chat_id": chat_id,
            "message_id": message_id,
            "file_name": self._file_name(file, message_id),
            "mime_type": getattr(file, "mime_type", None) or "application/octet-stream",
            "total_size": total_size,
            "offset": offset,
            "size": len(data),
            "next_offset": next_offset if next_offset < total_size else None,
            "complete": next_offset >= total_size,
            "data": data,
        }

    async def _attachment(self, chat_id: str, message_id: str):
        await self._authorized()
        peer = await self.client.get_input_entity(int(chat_id))
        message = await self.client.get_messages(peer, ids=int(message_id))
        if message is None:
            raise GatewayError("message_not_found", "Message was not found.")
        file = getattr(message, "file", None)
        if message.media is None or file is None:
            raise GatewayError("attachment_not_found", "Message has no downloadable attachment.")
        size = getattr(file, "size", None)
        if not isinstance(size, int) or size < 0:
            raise GatewayError("attachment_size_unknown", "Attachment size is unavailable.")
        return message, file, size

    @staticmethod
    def _message(message, *, include_chat: bool = False) -> dict:
        file = getattr(message, "file", None)
        attachment = None
        if file is not None:
            attachment = {
                "file_name": UserGateway._file_name(file, str(message.id)),
                "mime_type": getattr(file, "mime_type", None) or "application/octet-stream",
                "size": getattr(file, "size", None),
            }
        result = {
            "id": str(message.id),
            "date": message.date.isoformat() if message.date else None,
            "text": message.message or "",
            "sender_id": (str(message.sender_id) if message.sender_id is not None else None),
            "outgoing": bool(message.out),
            "reply_to": str(message.reply_to_msg_id) if message.reply_to_msg_id else None,
            "has_media": message.media is not None,
            "attachment": attachment,
        }
        if include_chat:
            chat_id = getattr(message, "chat_id", None)
            if chat_id is None and getattr(message, "peer_id", None) is not None:
                chat_id = utils.get_peer_id(message.peer_id)
            result["chat_id"] = str(chat_id) if chat_id is not None else None
        return result

    @staticmethod
    def _media_filter(kind: str | None):
        filters = {
            None: None,
            "any": None,
            "photo": types.InputMessagesFilterPhotos,
            "video": types.InputMessagesFilterVideo,
            "voice": types.InputMessagesFilterVoice,
            "audio": types.InputMessagesFilterMusic,
            "document": types.InputMessagesFilterDocument,
        }
        try:
            return filters[kind]
        except KeyError:
            raise GatewayError(
                "invalid_request",
                "Attachment kind must be any, photo, video, voice, audio or document.",
            ) from None

    @staticmethod
    def _send_as_self(peer) -> dict:
        # Telegram rejects the send_as flag in ordinary private and basic-group chats.
        # Channels and supergroups support it and may otherwise default to a chat identity.
        return (
            {"send_as": types.InputPeerSelf()} if isinstance(peer, types.InputPeerChannel) else {}
        )

    async def _folders(self) -> list:
        with telegram_errors():
            await self._authorized()
            result = await self.client(functions.messages.GetDialogFiltersRequest())
        filters = getattr(result, "filters", result)
        return [
            folder
            for folder in filters
            if isinstance(folder, (types.DialogFilter, types.DialogFilterChatlist))
        ]

    async def _resolve_folder(self, value: str):
        folders = await self._folders()
        if value.isdecimal():
            selected = next((folder for folder in folders if folder.id == int(value)), None)
        else:
            normalized = " ".join(self._terms(value))
            selected = next(
                (
                    folder
                    for folder in folders
                    if " ".join(self._terms(self._folder_title(folder))) == normalized
                ),
                None,
            )
            if selected is None and len(normalized) >= 2:
                prefix_matches = [
                    folder
                    for folder in folders
                    if " ".join(self._terms(self._folder_title(folder))).startswith(normalized)
                ]
                if len(prefix_matches) == 1:
                    selected = prefix_matches[0]
        if selected is None:
            raise GatewayError("folder_not_found", "Telegram folder was not found.")
        return selected

    @staticmethod
    def _folder_title(folder) -> str:
        title = getattr(folder, "title", "")
        return getattr(title, "text", title) or "Untitled"

    @staticmethod
    def _dialog_matches_folder(dialog, folder) -> bool:
        dialog_id = str(dialog.id)

        def peer_ids(field: str) -> set[str]:
            return {str(utils.get_peer_id(peer)) for peer in getattr(folder, field, []) or []}

        if dialog_id in peer_ids("exclude_peers"):
            return False
        if dialog_id in peer_ids("pinned_peers") | peer_ids("include_peers"):
            return True
        if isinstance(folder, types.DialogFilterChatlist):
            return False
        entity = getattr(dialog, "entity", None)
        automatic = bool(
            (
                getattr(folder, "contacts", False)
                and dialog.is_user
                and getattr(entity, "contact", False)
            )
            or (
                getattr(folder, "non_contacts", False)
                and dialog.is_user
                and not getattr(entity, "contact", False)
            )
            or (getattr(folder, "groups", False) and dialog.is_group)
            or (
                getattr(folder, "broadcasts", False)
                and getattr(dialog, "is_channel", False)
                and not dialog.is_group
            )
            or (getattr(folder, "bots", False) and getattr(entity, "bot", False))
        )
        if not automatic:
            return False
        if getattr(folder, "exclude_read", False) and not dialog.unread_count:
            return False
        if getattr(folder, "exclude_archived", False) and getattr(dialog, "archived", False):
            return False
        if getattr(folder, "exclude_muted", False):
            settings = getattr(getattr(dialog, "dialog", None), "notify_settings", None)
            mute_until = getattr(settings, "mute_until", None)
            if mute_until is not None:
                if isinstance(mute_until, datetime) and mute_until > datetime.now(UTC):
                    return False
                if isinstance(mute_until, int) and mute_until > int(datetime.now(UTC).timestamp()):
                    return False
        return True

    @staticmethod
    def _folder_explicit_peers(folder) -> list:
        excluded = {utils.get_peer_id(peer) for peer in getattr(folder, "exclude_peers", []) or []}
        seen = set()
        peers = []
        for peer in (getattr(folder, "pinned_peers", []) or []) + (
            getattr(folder, "include_peers", []) or []
        ):
            peer_id = utils.get_peer_id(peer)
            if peer_id not in excluded and peer_id not in seen:
                seen.add(peer_id)
                peers.append(peer)
        return peers

    @staticmethod
    def _folder_has_automatic_rules(folder) -> bool:
        if isinstance(folder, types.DialogFilterChatlist):
            return False
        return any(
            bool(getattr(folder, field, False))
            for field in ("contacts", "non_contacts", "groups", "broadcasts", "bots")
        )

    @staticmethod
    def _entity_row(entity) -> dict:
        kind = (
            "user"
            if isinstance(entity, types.User)
            else "group"
            if isinstance(entity, types.Chat) or getattr(entity, "megagroup", False)
            else "channel"
        )
        return {
            "id": str(utils.get_peer_id(entity)),
            "title": utils.get_display_name(entity),
            "kind": kind,
            "username": getattr(entity, "username", None),
        }

    async def _record_update(self, kind: str, **payload) -> None:
        async with self._update_condition:
            self._update_sequence += 1
            self._updates.append(
                {
                    "sequence": self._update_sequence,
                    "type": kind,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    **payload,
                }
            )
            self._update_condition.notify_all()

    async def _on_new_message(self, event) -> None:
        await self._record_update(
            "new_message",
            chat_id=str(event.chat_id) if event.chat_id is not None else None,
            message=self._message(event.message),
        )

    async def _on_edited_message(self, event) -> None:
        await self._record_update(
            "edited_message",
            chat_id=str(event.chat_id) if event.chat_id is not None else None,
            message=self._message(event.message),
        )

    async def _on_deleted_message(self, event) -> None:
        await self._record_update(
            "deleted_messages",
            chat_id=str(event.chat_id) if event.chat_id is not None else None,
            message_ids=[str(message_id) for message_id in event.deleted_ids],
        )

    async def _on_read_message(self, event) -> None:
        await self._record_update(
            "read",
            chat_id=str(event.chat_id) if event.chat_id is not None else None,
            max_message_id=str(event.max_id) if event.max_id else None,
            inbox=bool(event.inbox),
        )

    async def _on_raw_update(self, update) -> None:
        if not isinstance(update, types.UpdateMessageReactions):
            return
        await self._record_update(
            "reactions",
            chat_id=str(utils.get_peer_id(update.peer)),
            message_id=str(update.msg_id),
        )

    async def _verify_personal_sender(self, peer, message, user_id: int):
        if message.sender_id == user_id and bool(message.out):
            return message
        # The immediate MTProto update can omit or misreport sender metadata in private chats.
        # Re-read the stored message before concluding that Telegram used a chat identity.
        with telegram_errors(sending=True):
            stored = await self.client.get_messages(peer, ids=message.id)
        if stored is not None and stored.sender_id == user_id and bool(stored.out):
            return stored
        raise GatewayError(
            "sender_mismatch",
            "Message was sent with a chat identity. Check history; do not retry.",
        )

    @staticmethod
    def _file_name(file, message_id: str) -> str:
        raw_name = getattr(file, "name", None) or f"attachment-{message_id}"
        file_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1]
        file_name = re.sub(r"[\x00-\x1f\x7f]", "_", file_name)[:255]
        return file_name or f"attachment-{message_id}"
