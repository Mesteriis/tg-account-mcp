"""Private drafts and bounded idempotency receipts for agent operations."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from tg_mcp.errors import GatewayError, LocalError
from tg_mcp.storage import StateStore

_DRAFT = re.compile(r"^draft_[a-z2-7]{16}$")


class AgentStateStore:
    def __init__(self, store: StateStore, *, max_receipts: int = 1000):
        self.store = store
        self.drafts_path = store.root / "drafts.json"
        self.receipts_path = store.root / "idempotency.json"
        self.max_receipts = max_receipts
        self._lock = Lock()
        self._drafts = self._load(self.drafts_path, "drafts")
        self._receipts = self._load(self.receipts_path, "receipts")

    def _load(self, path, key: str) -> list[dict]:
        if not path.exists():
            return []
        try:
            document = self.store.read_private_json(path)
            if document.get("version") != 1 or not isinstance(document.get(key), list):
                raise ValueError
            return document[key]
        except (OSError, ValueError, TypeError, LocalError):
            raise LocalError(f"Invalid agent {key} document") from None

    @staticmethod
    def fingerprint(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    def lookup_receipt(self, key: str, operation: str, fingerprint: str) -> dict | None:
        with self._lock:
            record = next((row for row in self._receipts if row["key"] == key), None)
            if record is None:
                return None
            if record["operation"] != operation or record["fingerprint"] != fingerprint:
                raise GatewayError(
                    "idempotency_conflict",
                    "Idempotency key was already used with different arguments.",
                )
            return {**record["result"], "idempotent_replay": True}

    def save_receipt(
        self, key: str, operation: str, fingerprint: str, result: dict[str, Any]
    ) -> None:
        record = {
            "key": key,
            "operation": operation,
            "fingerprint": fingerprint,
            "result": result,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with self._lock:
            self._receipts.append(record)
            self._receipts = self._receipts[-self.max_receipts :]
            self.store.write_private_json(
                self.receipts_path, {"version": 1, "receipts": self._receipts}
            )

    @staticmethod
    def _new_draft_id() -> str:
        suffix = base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=").lower()
        return f"draft_{suffix}"

    def create_draft(self, identity_id: str, chat_id: str, text: str, reply_to: str | None) -> dict:
        record = {
            "draft_id": self._new_draft_id(),
            "identity_id": identity_id,
            "chat_id": chat_id,
            "text": text,
            "reply_to": reply_to,
            "status": "pending",
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "sent_result": None,
        }
        with self._lock:
            self._drafts.append(record)
            self.store.write_private_json(self.drafts_path, {"version": 1, "drafts": self._drafts})
        return record.copy()

    def list_drafts(self, identity_id: str | None = None) -> list[dict]:
        with self._lock:
            return [
                record.copy()
                for record in self._drafts
                if identity_id is None or record["identity_id"] == identity_id
            ]

    def draft(self, draft_id: str) -> dict:
        if not _DRAFT.fullmatch(draft_id):
            raise GatewayError("draft_not_found", "Draft was not found.")
        with self._lock:
            for record in self._drafts:
                if record["draft_id"] == draft_id:
                    return record.copy()
        raise GatewayError("draft_not_found", "Draft was not found.")

    def mark_sent(self, draft_id: str, result: dict) -> dict:
        with self._lock:
            for record in self._drafts:
                if record["draft_id"] == draft_id:
                    record["status"] = "sent"
                    record["sent_result"] = result
                    record["sent_at"] = datetime.now(UTC).isoformat(timespec="seconds")
                    self.store.write_private_json(
                        self.drafts_path, {"version": 1, "drafts": self._drafts}
                    )
                    return record.copy()
        raise GatewayError("draft_not_found", "Draft was not found.")

    def delete_draft(self, draft_id: str) -> dict:
        with self._lock:
            for index, record in enumerate(self._drafts):
                if record["draft_id"] == draft_id:
                    removed = self._drafts.pop(index)
                    self.store.write_private_json(
                        self.drafts_path, {"version": 1, "drafts": self._drafts}
                    )
                    return {"draft_id": removed["draft_id"], "deleted": True}
        raise GatewayError("draft_not_found", "Draft was not found.")
