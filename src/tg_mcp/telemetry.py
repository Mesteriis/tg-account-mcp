"""Bounded, content-free operation telemetry for the local administration UI."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from collections import deque
from datetime import UTC, date, datetime, timedelta
from threading import Lock
from typing import Any

from tg_mcp.errors import LocalError
from tg_mcp.storage import StateStore

_IDENTITY = re.compile(r"^(?:acct|bot)_[a-z2-7]{16}$")
_AGENT = re.compile(r"^agent_[a-z2-7]{16}$")
_CHAT = re.compile(r"^-?[1-9][0-9]{0,18}$")
_OPERATIONS = {
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
_CATEGORIES = {
    "get_status": "read",
    "list_accounts": "read",
    "list_bots": "read",
    "get_capabilities": "read",
    "list_chats": "read",
    "find_chats": "search",
    "get_unread_inbox": "read",
    "get_inbox_context": "read",
    "list_folders": "read",
    "get_folder_messages": "search",
    "get_chat_history": "read",
    "search_messages": "search",
    "search_all_messages": "search",
    "get_message": "read",
    "get_message_context": "read",
    "get_reply_thread": "read",
    "get_conversation_snapshot": "read",
    "resolve_peer": "search",
    "search_chat_content": "search",
    "poll_updates": "read",
    "list_attachments": "search",
    "get_chat_info": "read",
    "resolve_message_link": "search",
    "list_topics": "read",
    "get_recent_mentions": "read",
    "download_attachment": "read",
    "download_attachment_chunk": "read",
    "send_as_user": "send",
    "edit_own_message": "send",
    "schedule_message": "send",
    "list_scheduled_messages": "read",
    "cancel_scheduled_message": "send",
    "send_as_bot": "send",
    "send_attachment": "send",
    "forward_messages": "send",
    "mark_chat_read": "send",
    "react_to_message": "send",
    "create_draft": "send",
    "list_drafts": "read",
    "send_draft": "send",
    "delete_draft": "send",
    "create_agent_token": "send",
    "list_agent_tokens": "read",
    "revoke_agent_token": "send",
}


class TelemetryStore:
    """Persist a small rolling log without message text, queries, tokens, or passwords."""

    def __init__(self, store: StateStore, *, max_events: int = 2000):
        self.store = store
        self.path = store.root / "operations.json"
        self.max_events = max_events
        self._lock = Lock()
        self._events: deque[dict[str, Any]] = deque(self._load(), maxlen=max_events)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            fd = self.store.open_private(self.path, os.O_RDONLY)
            with os.fdopen(fd) as stream:
                document = json.load(stream)
            if document.get("version") != 1 or not isinstance(document.get("events"), list):
                raise ValueError("unsupported telemetry document")
            return [event for event in document["events"] if self._valid_event(event)][
                -self.max_events :
            ]
        except (OSError, ValueError, TypeError, AttributeError, LocalError):
            logging.getLogger("tg_mcp").warning("Operation telemetry could not be loaded")
            return []

    @staticmethod
    def _valid_event(event: Any) -> bool:
        if not isinstance(event, dict):
            return False
        return (
            event.get("operation") in _OPERATIONS
            and event.get("category") in {"read", "search", "send"}
            and event.get("status") in {"success", "error"}
            and isinstance(event.get("at"), str)
            and isinstance(event.get("duration_ms"), int)
        )

    def record(
        self,
        operation: str,
        *,
        identity_id: str | None = None,
        chat_id: str | None = None,
        status: str = "success",
        duration_ms: int = 0,
        error_code: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        if operation not in _OPERATIONS:
            raise ValueError("Unsupported telemetry operation")
        safe_identity = identity_id if identity_id and _IDENTITY.fullmatch(identity_id) else None
        safe_chat = chat_id if chat_id and _CHAT.fullmatch(chat_id) else None
        safe_agent = agent_id if agent_id and _AGENT.fullmatch(agent_id) else None
        event = {
            "id": secrets.token_hex(8),
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "operation": operation,
            "category": _CATEGORIES[operation],
            "identity_id": safe_identity,
            "chat_id": safe_chat,
            "agent_id": safe_agent,
            "status": "success" if status == "success" else "error",
            "duration_ms": max(0, min(int(duration_ms), 3_600_000)),
            "error_code": error_code[:64] if error_code else None,
        }
        with self._lock:
            self._events.append(event)
            try:
                self.store.write_private_json(
                    self.path, {"version": 1, "events": list(self._events)}
                )
            except (OSError, LocalError):
                logging.getLogger("tg_mcp").warning("Operation telemetry could not be saved")

    def snapshot(self, *, days: int = 30, recent_limit: int = 100) -> dict[str, Any]:
        days = max(1, min(days, 90))
        today = datetime.now(UTC).date()
        first = today - timedelta(days=days - 1)
        with self._lock:
            events = [event.copy() for event in self._events]
        selected = [event for event in events if self._event_date(event) >= first]
        current_hour = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        first_hour = current_hour - timedelta(hours=23)
        buckets = {
            first + timedelta(days=offset): {"read": 0, "search": 0, "send": 0}
            for offset in range(days)
        }
        hourly_buckets = {
            first_hour + timedelta(hours=offset): {"read": 0, "search": 0, "send": 0}
            for offset in range(24)
        }
        by_identity: dict[str, dict[str, Any]] = {}
        errors = 0
        for event in selected:
            event_date = self._event_date(event)
            if event_date in buckets:
                buckets[event_date][event["category"]] += 1
            event_hour = self._event_hour(event)
            if event_hour in hourly_buckets:
                hourly_buckets[event_hour][event["category"]] += 1
            errors += event["status"] == "error"
            identity_id = event.get("identity_id")
            if identity_id:
                row = by_identity.setdefault(
                    identity_id,
                    {
                        "identity_id": identity_id,
                        "requests": 0,
                        "read": 0,
                        "search": 0,
                        "send": 0,
                        "errors": 0,
                    },
                )
                row["requests"] += 1
                row[event["category"]] += 1
                row["errors"] += event["status"] == "error"
        requests = len(selected)
        return {
            "period": {"days": days, "from": first.isoformat(), "to": today.isoformat()},
            "totals": {
                "requests": requests,
                "read": sum(event["category"] == "read" for event in selected),
                "search": sum(event["category"] == "search" for event in selected),
                "send": sum(event["category"] == "send" for event in selected),
                "errors": errors,
                "error_rate": round((errors / requests * 100) if requests else 0, 1),
            },
            "series": [
                {"date": bucket_date.isoformat(), **values}
                for bucket_date, values in buckets.items()
            ],
            "hourly_series": [
                {"at": bucket_hour.isoformat(timespec="minutes"), **values}
                for bucket_hour, values in hourly_buckets.items()
            ],
            "by_identity": sorted(
                by_identity.values(), key=lambda row: row["requests"], reverse=True
            ),
            "recent": list(reversed(selected[-recent_limit:])),
        }

    @staticmethod
    def _event_date(event: dict[str, Any]) -> date:
        try:
            return datetime.fromisoformat(event["at"]).date()
        except (TypeError, ValueError):
            return date.min

    @staticmethod
    def _event_hour(event: dict[str, Any]) -> datetime:
        try:
            value = datetime.fromisoformat(event["at"])
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=UTC)
