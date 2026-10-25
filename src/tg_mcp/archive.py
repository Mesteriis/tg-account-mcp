"""Opt-in local message archive; no network, embeddings or model calls."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from threading import RLock

from tg_mcp.errors import GatewayError
from tg_mcp.storage import StateStore


def now() -> str:
    return datetime.now(UTC).isoformat()


class ArchiveStore:
    def __init__(self, store: StateStore):
        self.store = store
        self.path = store.root / "archive.sqlite3"
        self._lock = RLock()
        self.capture_failed = False
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise GatewayError("archive_version", "Unsupported archive schema version.")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS chats (
                    account TEXT NOT NULL, chat TEXT NOT NULL, title TEXT NOT NULL,
                    enabled INTEGER NOT NULL, retain_deleted INTEGER NOT NULL,
                    is_channel INTEGER NOT NULL,
                    cursor TEXT, backfill_complete INTEGER NOT NULL DEFAULT 0,
                    last_sync TEXT, last_event TEXT, error TEXT,
                    PRIMARY KEY(account, chat)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    rowid INTEGER PRIMARY KEY,
                    account TEXT NOT NULL, chat TEXT NOT NULL, mid TEXT NOT NULL,
                    snapshot TEXT NOT NULL, text TEXT NOT NULL, date TEXT,
                    sender TEXT, source_date TEXT NOT NULL, deleted_at TEXT,
                    UNIQUE(account, chat, mid),
                    FOREIGN KEY(account, chat) REFERENCES chats(account, chat) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS versions (
                    revision INTEGER PRIMARY KEY, account TEXT NOT NULL,
                    chat TEXT NOT NULL, mid TEXT NOT NULL, observed_at TEXT NOT NULL,
                    snapshot TEXT NOT NULL, source_date TEXT NOT NULL,
                    FOREIGN KEY(account, chat, mid) REFERENCES messages(account, chat, mid)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS versions_message
                    ON versions(account, chat, mid, revision);
                CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(text);

            """)
            from tg_mcp.memory import MEMORY_SCHEMA

            db.executescript(MEMORY_SCHEMA)
            from tg_mcp.loading import SCHEMA

            db.executescript(SCHEMA)
            db.execute("PRAGMA user_version=4")

    @contextmanager
    def connect(self):
        with self._lock:
            fd = self.store.open_private(self.path, os.O_CREAT | os.O_RDWR)
            os.close(fd)
            for suffix in ("-journal", "-wal", "-shm"):
                self.store._check_file(self.path.with_name(self.path.name + suffix))
            with closing(sqlite3.connect(self.path)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("PRAGMA secure_delete=ON")
                db.execute("PRAGMA temp_store=MEMORY")
                with db:
                    yield db

    def configure(
        self,
        account: str,
        chat: str,
        title: str,
        *,
        enabled: bool,
        retain_deleted: bool,
        is_channel: bool = False,
    ) -> dict:
        with self.connect() as db:
            if enabled:
                db.execute("DELETE FROM rag_exclusions WHERE account=? AND chat=?", (account, chat))
            else:
                db.execute("INSERT OR IGNORE INTO rag_exclusions VALUES(?,?)", (account, chat))
            db.execute(
                """INSERT INTO chats(account, chat, title, enabled, retain_deleted,is_channel)
                VALUES(?,?,?,?,?,?) ON CONFLICT(account,chat) DO UPDATE SET
                title=excluded.title, enabled=excluded.enabled,
                retain_deleted=excluded.retain_deleted,is_channel=excluded.is_channel""",
                (account, chat, title, enabled, retain_deleted, is_channel),
            )
            if not retain_deleted:
                for row in db.execute(
                    "SELECT rowid, mid FROM messages WHERE account=? AND chat=? "
                    "AND deleted_at IS NOT NULL",
                    (account, chat),
                ).fetchall():
                    self._erase(db, account, chat, row["mid"], row["rowid"])
        return self.status(account, chat)

    def discover(self, account: str, chat: str, title: str, is_channel: bool) -> bool:
        """Register an automatically discovered chat without overriding explicit exclusions."""
        with self.connect() as db:
            if db.execute(
                "SELECT 1 FROM rag_exclusions WHERE account=? AND chat=?", (account, chat)
            ).fetchone():
                return False
            existed = db.execute(
                "SELECT 1 FROM chats WHERE account=? AND chat=?", (account, chat)
            ).fetchone()
            db.execute(
                "INSERT INTO chats(account,chat,title,enabled,retain_deleted,is_channel) "
                "VALUES(?,?,?,1,0,?) ON CONFLICT(account,chat) DO UPDATE SET "
                "title=CASE WHEN excluded.title!='' THEN excluded.title ELSE chats.title END,"
                "is_channel=excluded.is_channel",
                (account, chat, title, is_channel),
            )
            return existed is None

    def head_progress(self, account: str, chat: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM rag_heads WHERE account=? AND chat=?", (account, chat)
            ).fetchone()
            return dict(row) if row else {"cursor": None, "high_id": 0, "stop_id": 0, "top_id": 0}

    def ingest_head(self, account: str, chat: str, messages: list[dict], cursor: str | None):
        with self.connect() as db:
            if not db.execute(
                "SELECT 1 FROM chats WHERE account=? AND chat=? AND enabled=1", (account, chat)
            ).fetchone():
                return
            row = db.execute(
                "SELECT * FROM rag_heads WHERE account=? AND chat=?", (account, chat)
            ).fetchone()
            progress = (
                dict(row) if row else {"cursor": None, "high_id": 0, "stop_id": 0, "top_id": 0}
            )
            stop = progress["stop_id"] if progress["cursor"] else progress["high_id"]
            top = max(
                [
                    progress["top_id"] if progress["cursor"] else progress["high_id"],
                    *(int(message["id"]) for message in messages),
                ]
            )
            for message in messages:
                self._put(db, account, chat, message)
            done = (
                stop == 0
                or cursor is None
                or any(int(message["id"]) <= stop for message in messages)
            )
            db.execute(
                "INSERT OR REPLACE INTO rag_heads VALUES(?,?,?,?,?,?)",
                (
                    account,
                    chat,
                    None if done else cursor,
                    top if done else progress["high_id"],
                    stop,
                    top,
                ),
            )
            db.execute(
                "UPDATE chats SET last_sync=?,error=NULL WHERE account=? AND chat=?",
                (now(), account, chat),
            )

    def sync_config(self, account: str, chat: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM chats WHERE account=? AND chat=? AND enabled=1", (account, chat)
            ).fetchone()
            return dict(row) if row else None

    def configured(self, account: str | None = None) -> list[dict]:
        with self.connect() as db:
            if account is None:
                rows = db.execute("SELECT * FROM chats WHERE enabled=1").fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM chats WHERE enabled=1 AND account=?", (account,)
                ).fetchall()
            return [dict(row) for row in rows]

    def status(self, account: str, chat: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM chats WHERE account=? AND chat=?", (account, chat)
            ).fetchone()
            if row is None:
                raise GatewayError("archive_not_configured", "Configure this chat archive first.")
            counts = db.execute(
                "SELECT count(*), sum(deleted_at IS NOT NULL) FROM messages "
                "WHERE account=? AND chat=?",
                (account, chat),
            ).fetchone()
            return {
                "account_id": account,
                "chat_id": chat,
                "title": row["title"],
                "enabled": bool(row["enabled"]),
                "is_channel": bool(row["is_channel"]),
                "retain_deleted": bool(row["retain_deleted"]),
                "backfill_complete": bool(row["backfill_complete"]),
                "last_sync": row["last_sync"],
                "last_event": row["last_event"],
                "error": row["error"],
                "capture_failed_since_start": self.capture_failed,
                "message_count": counts[0],
                "deleted_count": counts[1] or 0,
                "coverage": "observed_only",
            }

    @staticmethod
    def _erase(db, account, chat, mid, rowid):
        db.execute("DELETE FROM message_fts WHERE rowid=?", (rowid,))
        db.execute(
            "DELETE FROM versions WHERE account=? AND chat=? AND mid=?", (account, chat, mid)
        )
        db.execute(
            "UPDATE messages SET snapshot=?,text='',sender=NULL,date=NULL,"
            "deleted_at=coalesce(deleted_at,?) WHERE rowid=?",
            (json.dumps({"id": mid, "text": ""}), now(), rowid),
        )

    def _put(self, db, account, chat, message):
        mid = message["id"]
        source_date = message.get("edit_date") or message.get("date") or ""
        snapshot = json.dumps(message, sort_keys=True, ensure_ascii=False)
        old = db.execute(
            "SELECT rowid, * FROM messages WHERE account=? AND chat=? AND mid=?",
            (account, chat, mid),
        ).fetchone()
        # Backfill must never resurrect a tombstone or replace a newer live edit.
        if old and (old["deleted_at"] or old["source_date"] > source_date):
            return
        if old and old["snapshot"] == snapshot:
            return
        db.execute(
            """INSERT INTO messages(account,chat,mid,snapshot,text,date,sender,source_date)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account,chat,mid) DO UPDATE SET
            snapshot=excluded.snapshot,text=excluded.text,date=excluded.date,
            sender=excluded.sender,source_date=excluded.source_date""",
            (
                account,
                chat,
                mid,
                snapshot,
                message.get("text", ""),
                message.get("date"),
                message.get("sender_id"),
                source_date,
            ),
        )
        rowid = db.execute(
            "SELECT rowid FROM messages WHERE account=? AND chat=? AND mid=?", (account, chat, mid)
        ).fetchone()[0]
        db.execute("DELETE FROM message_fts WHERE rowid=?", (rowid,))
        db.execute(
            "INSERT INTO message_fts(rowid,text) VALUES(?,?)", (rowid, message.get("text", ""))
        )
        db.execute(
            "INSERT INTO versions(account,chat,mid,observed_at,snapshot,source_date) "
            "VALUES(?,?,?,?,?,?)",
            (account, chat, mid, now(), snapshot, source_date),
        )

    def ingest_page(self, account: str, chat: str, messages: list[dict], cursor: str | None):
        with self.connect() as db:
            config = db.execute(
                "SELECT * FROM chats WHERE account=? AND chat=? AND enabled=1", (account, chat)
            ).fetchone()
            if config is None:
                return
            for message in messages:
                self._put(db, account, chat, message)
            db.execute(
                "UPDATE chats SET cursor=?,backfill_complete=max(backfill_complete,?),"
                "last_sync=?,error=NULL "
                "WHERE account=? AND chat=?",
                (cursor, int(cursor is None), now(), account, chat),
            )

    def record(self, account: str, kind: str, payload: dict):
        if kind not in {"new_message", "edited_message", "deleted_messages"}:
            return
        chat = payload.get("chat_id")
        with self.connect() as db:
            if kind != "deleted_messages":
                if db.execute(
                    "SELECT 1 FROM chats WHERE account=? AND chat=? AND enabled=1", (account, chat)
                ).fetchone():
                    self._put(db, account, chat, payload["message"])
            else:
                for mid in payload["message_ids"]:
                    if chat is None:
                        # Without a peer Telegram IDs refer only to private/basic-group messages.
                        rows = db.execute(
                            "SELECT m.rowid, m.*, c.retain_deleted FROM messages m "
                            "JOIN chats c USING(account,chat) WHERE m.account=? AND m.mid=? "
                            "AND c.enabled=1 AND c.is_channel=0",
                            (account, mid),
                        ).fetchall()
                    else:
                        rows = db.execute(
                            "SELECT m.rowid, m.*, c.retain_deleted FROM messages m "
                            "JOIN chats c USING(account,chat) WHERE m.account=? AND m.chat=? "
                            "AND m.mid=? AND c.enabled=1",
                            (account, chat, mid),
                        ).fetchall()
                    if (
                        not rows
                        and chat is not None
                        and db.execute(
                            "SELECT 1 FROM chats WHERE account=? AND chat=? AND enabled=1",
                            (account, chat),
                        ).fetchone()
                    ):
                        self._put(db, account, chat, {"id": mid, "text": ""})
                        tombstone = db.execute(
                            "SELECT rowid FROM messages WHERE account=? AND chat=? AND mid=?",
                            (account, chat, mid),
                        ).fetchone()
                        self._erase(db, account, chat, mid, tombstone[0])
                    for row in rows:
                        if row["retain_deleted"]:
                            db.execute(
                                "UPDATE messages SET deleted_at=coalesce(deleted_at,?) "
                                "WHERE rowid=?",
                                (now(), row["rowid"]),
                            )
                        else:
                            self._erase(db, account, row["chat"], mid, row["rowid"])
            if chat is not None:
                db.execute(
                    "UPDATE chats SET last_event=? WHERE account=? AND chat=? AND enabled=1",
                    (now(), account, chat),
                )

    def sync_error(self, account: str, chat: str, code: str):
        with self.connect() as db:
            db.execute("UPDATE chats SET error=? WHERE account=? AND chat=?", (code, account, chat))

    def search(
        self,
        account: str,
        chat: str,
        query: str,
        *,
        limit=50,
        offset=0,
        include_deleted=False,
        sender_id=None,
        date_from=None,
        date_to=None,
    ) -> dict:
        self.status(account, chat)
        # Treat input as literal words, never as FTS operators or SQL.
        terms = query.split()
        if not terms:
            raise GatewayError("invalid_request", "Search query must contain words.")
        match = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)
        where = ["message_fts MATCH ?", "m.account=?", "m.chat=?"]
        params = [match, account, chat]
        if not include_deleted:
            where.append("m.deleted_at IS NULL")
        if sender_id is not None:
            where.append("m.sender=?")
            params.append(sender_id)
        if date_from is not None:
            where.append("substr(m.date,1,10)>=?")
            params.append(date_from)
        if date_to is not None:
            where.append("substr(m.date,1,10)<=?")
            params.append(date_to)
        with self.connect() as db:
            rows = db.execute(
                "SELECT m.* FROM message_fts JOIN messages m "
                "ON m.rowid=message_fts.rowid WHERE "
                + " AND ".join(where)
                + " ORDER BY bm25(message_fts),m.rowid LIMIT ? OFFSET ?",
                [*params, limit + 1, offset],
            ).fetchall()
            return {
                "messages": [
                    {
                        **json.loads(row["snapshot"]),
                        "deleted_at": row["deleted_at"],
                        "source": "local_archive",
                        "chat_id": chat,
                        "account_id": account,
                    }
                    for row in rows[:limit]
                ],
                "has_more": len(rows) > limit,
            }

    def versions(self, account: str, chat: str, mid: str, *, limit=50, offset=0) -> dict:
        self.status(account, chat)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM versions WHERE account=? AND chat=? AND mid=? "
                "ORDER BY revision DESC LIMIT ? OFFSET ?",
                (account, chat, mid, limit + 1, offset),
            ).fetchall()
            return {
                "versions": [
                    {
                        "revision": row["revision"],
                        "observed_at": row["observed_at"],
                        "message": json.loads(row["snapshot"]),
                    }
                    for row in rows[:limit]
                ],
                "has_more": len(rows) > limit,
            }

    def reset_sync(self, account: str, chat: str):
        with self.connect() as db:
            db.execute("DELETE FROM rag_heads WHERE account=? AND chat=?", (account, chat))
            db.execute(
                "UPDATE chats SET cursor=NULL,backfill_complete=0,error=NULL "
                "WHERE account=? AND chat=?",
                (account, chat),
            )

    def export(self, account: str, chat: str, *, limit=50, offset=0, include_deleted=False) -> dict:
        self.status(account, chat)
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM messages WHERE account=? AND chat=? "
                + ("" if include_deleted else "AND deleted_at IS NULL ")
                + "ORDER BY CAST(mid AS INTEGER) LIMIT ? OFFSET ?",
                (account, chat, limit + 1, offset),
            ).fetchall()
            return {
                "messages": [
                    {
                        **json.loads(row["snapshot"]),
                        "deleted_at": row["deleted_at"],
                        "account_id": account,
                        "chat_id": chat,
                        "source": "local_archive",
                    }
                    for row in rows[:limit]
                ],
                "has_more": len(rows) > limit,
            }

    def purge(self, account: str, chat: str | None = None):
        with self.connect() as db:
            if chat is not None:
                db.execute("INSERT OR IGNORE INTO rag_exclusions VALUES(?,?)", (account, chat))
            else:
                db.execute("DELETE FROM rag_exclusions WHERE account=?", (account,))
            where, params = (
                ("account=?", [account])
                if chat is None
                else ("account=? AND chat=?", [account, chat])
            )
            db.execute(
                "DELETE FROM message_fts WHERE rowid IN "
                "(SELECT rowid FROM messages WHERE " + where + ")",
                params,
            )
            db.execute("DELETE FROM chats WHERE " + where, params)
            if chat is None:
                db.execute("DELETE FROM projects WHERE account=?", (account,))
                db.execute("DELETE FROM rag_loading WHERE account=?", (account,))
        return {"account_id": account, "chat_id": chat, "purged": True}
