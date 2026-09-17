"""Scoped agent access tokens and request-local authorization context."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

from tg_mcp.errors import GatewayError, LocalError
from tg_mcp.storage import StateStore

ScopeName = Literal["read", "send", "admin"]
_SCOPES = frozenset({"read", "send", "admin"})
_IDENTITY = re.compile(r"^(?:acct|bot)_[a-z2-7]{16}$")
_CHAT = re.compile(r"^-?[1-9][0-9]{0,18}$")
_AGENT = re.compile(r"^agent_[a-z2-7]{16}$")


@dataclass(frozen=True)
class AccessPolicy:
    agent_id: str | None
    label: str
    scopes: frozenset[str]
    identity_ids: frozenset[str] | None = None
    chat_ids: frozenset[str] | None = None

    @property
    def is_master(self) -> bool:
        return self.agent_id is None


MASTER_ACCESS = AccessPolicy(None, "Master", _SCOPES)
current_access: ContextVar[AccessPolicy] = ContextVar("tg_mcp_access", default=MASTER_ACCESS)


def authorize(scope: ScopeName, identity_id: str | None = None, chat_id: str | None = None) -> None:
    policy = current_access.get()
    if "admin" not in policy.scopes and scope not in policy.scopes:
        raise GatewayError("forbidden", f"Agent token does not allow {scope} operations.")
    if (
        identity_id is not None
        and policy.identity_ids is not None
        and identity_id not in policy.identity_ids
    ):
        raise GatewayError("forbidden", "Agent token does not allow this identity.")
    if chat_id is not None and policy.chat_ids is not None and chat_id not in policy.chat_ids:
        raise GatewayError("forbidden", "Agent token does not allow this chat.")


def visible_identity(identity_id: str) -> bool:
    policy = current_access.get()
    return policy.identity_ids is None or identity_id in policy.identity_ids


class AgentAccessStore:
    """Store only hashes of scoped bearer tokens in private state."""

    def __init__(self, store: StateStore):
        self.store = store
        self.path = store.root / "agents.json"
        self._lock = Lock()
        self._records = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        document = self.store.read_private_json(self.path)
        if document.get("version") != 1 or not isinstance(document.get("agents"), list):
            raise LocalError("Invalid agent access document")
        records: list[dict] = []
        for record in document["agents"]:
            if self._valid(record):
                records.append(record)
            else:
                raise LocalError("Invalid agent access record")
        return records

    @staticmethod
    def _valid(record: object) -> bool:
        if not isinstance(record, dict):
            return False
        identities = record.get("identity_ids")
        chats = record.get("chat_ids")
        return bool(
            _AGENT.fullmatch(str(record.get("agent_id", "")))
            and isinstance(record.get("label"), str)
            and 0 < len(record["label"]) <= 64
            and isinstance(record.get("token_hash"), str)
            and re.fullmatch(r"[a-f0-9]{64}", record["token_hash"])
            and isinstance(record.get("scopes"), list)
            and record["scopes"]
            and set(record["scopes"]) <= _SCOPES
            and (
                identities is None
                or (
                    isinstance(identities, list)
                    and all(isinstance(v, str) and _IDENTITY.fullmatch(v) for v in identities)
                )
            )
            and (
                chats is None
                or (
                    isinstance(chats, list)
                    and all(isinstance(v, str) and _CHAT.fullmatch(v) for v in chats)
                )
            )
            and isinstance(record.get("enabled"), bool)
        )

    def _save(self) -> None:
        self.store.write_private_json(self.path, {"version": 1, "agents": self._records})

    @staticmethod
    def _new_id() -> str:
        suffix = base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=").lower()
        return f"agent_{suffix}"

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def create(
        self,
        label: str,
        scopes: list[str],
        identity_ids: list[str] | None,
        chat_ids: list[str] | None,
    ) -> dict:
        clean_label = label.strip()
        if not clean_label or any(ord(char) < 32 for char in clean_label):
            raise GatewayError("invalid_request", "Agent label must contain visible characters.")
        if not scopes or not set(scopes) <= _SCOPES:
            raise GatewayError("invalid_request", "Agent scopes are invalid.")
        token = secrets.token_urlsafe(32)
        record = {
            "agent_id": self._new_id(),
            "label": clean_label,
            "token_hash": self._digest(token),
            "scopes": sorted(set(scopes)),
            "identity_ids": sorted(set(identity_ids)) if identity_ids is not None else None,
            "chat_ids": sorted(set(chat_ids)) if chat_ids is not None else None,
            "enabled": True,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with self._lock:
            self._records.append(record)
            self._save()
        return {**self._public(record), "token": token}

    def verify(self, token: str) -> AccessPolicy | None:
        digest = self._digest(token)
        with self._lock:
            records = list(self._records)
        for record in records:
            if record["enabled"] and secrets.compare_digest(digest, record["token_hash"]):
                return AccessPolicy(
                    record["agent_id"],
                    record["label"],
                    frozenset(record["scopes"]),
                    frozenset(record["identity_ids"])
                    if record["identity_ids"] is not None
                    else None,
                    frozenset(record["chat_ids"]) if record["chat_ids"] is not None else None,
                )
        return None

    def list(self) -> list[dict]:
        with self._lock:
            return [self._public(record) for record in self._records]

    def enabled_token_digests(self) -> tuple[bytes, ...]:
        """Return digest bytes for authenticated discovery without exposing token material."""
        with self._lock:
            return tuple(
                bytes.fromhex(record["token_hash"]) for record in self._records if record["enabled"]
            )

    def revoke(self, agent_id: str) -> dict:
        with self._lock:
            for record in self._records:
                if record["agent_id"] == agent_id:
                    record["enabled"] = False
                    self._save()
                    return self._public(record)
        raise GatewayError("agent_not_found", "Agent token was not found.")

    @staticmethod
    def _public(record: dict) -> dict:
        return {key: value for key, value in record.items() if key != "token_hash"}
