"""Project-scoped, source-backed decisions and their approval lifecycle."""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import TYPE_CHECKING

from tg_mcp.archive import now
from tg_mcp.errors import GatewayError

if TYPE_CHECKING:
    from tg_mcp.archive import ArchiveStore


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_id(prefix: str) -> str:
    return prefix + "_" + base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=").lower()


MEMORY_SCHEMA = """
    CREATE TABLE IF NOT EXISTS rag_exclusions (
        account TEXT NOT NULL, chat TEXT NOT NULL, PRIMARY KEY(account,chat)
    );
    CREATE TABLE IF NOT EXISTS rag_heads (
        account TEXT NOT NULL, chat TEXT NOT NULL, cursor TEXT,
        high_id INTEGER NOT NULL DEFAULT 0, stop_id INTEGER NOT NULL DEFAULT 0,
        top_id INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(account,chat),
        FOREIGN KEY(account,chat) REFERENCES chats(account,chat) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, account TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS project_chats (
        project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        account TEXT NOT NULL, chat TEXT NOT NULL,
        PRIMARY KEY(project,chat)
    );
    CREATE TABLE IF NOT EXISTS project_memories (
        id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        text TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, approved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS memory_sources (
        memory TEXT NOT NULL REFERENCES project_memories(id) ON DELETE CASCADE,
        account TEXT NOT NULL, chat TEXT NOT NULL, mid TEXT NOT NULL, fingerprint TEXT NOT NULL,
        PRIMARY KEY(memory,chat,mid),
        FOREIGN KEY(account,chat,mid) REFERENCES messages(account,chat,mid) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS memory_source_message ON memory_sources(account,chat,mid);
    CREATE TABLE IF NOT EXISTS message_vectors (
        message INTEGER NOT NULL REFERENCES messages(rowid) ON DELETE CASCADE,
        model TEXT NOT NULL, fingerprint TEXT NOT NULL, vector TEXT NOT NULL,
        PRIMARY KEY(message,model)
    );
    CREATE TABLE IF NOT EXISTS memory_vectors (
        memory TEXT NOT NULL REFERENCES project_memories(id) ON DELETE CASCADE,
        model TEXT NOT NULL, fingerprint TEXT NOT NULL, vector TEXT NOT NULL,
        PRIMARY KEY(memory,model)
    );
    CREATE TRIGGER IF NOT EXISTS archive_delete_derived BEFORE DELETE ON messages BEGIN
        DELETE FROM project_memories WHERE id IN (SELECT memory FROM memory_sources
            WHERE account=old.account AND chat=old.chat AND mid=old.mid);
    END;
    CREATE TRIGGER IF NOT EXISTS archive_tombstone_derived AFTER UPDATE OF deleted_at ON messages
        WHEN new.deleted_at IS NOT NULL BEGIN
        DELETE FROM project_memories WHERE id IN (SELECT memory FROM memory_sources
            WHERE account=new.account AND chat=new.chat AND mid=new.mid);
        DELETE FROM message_vectors WHERE message=new.rowid;
    END;
    CREATE TRIGGER IF NOT EXISTS archive_edit_derived AFTER UPDATE OF snapshot ON messages
        WHEN new.snapshot != old.snapshot BEGIN
        DELETE FROM message_vectors WHERE message=new.rowid;
        DELETE FROM memory_vectors WHERE memory IN (SELECT memory FROM memory_sources
            WHERE account=new.account AND chat=new.chat AND mid=new.mid);
        UPDATE project_memories SET state='stale',approved_at=NULL WHERE id IN
            (SELECT memory FROM memory_sources
             WHERE account=new.account AND chat=new.chat AND mid=new.mid);
    END;
"""


class ProjectMemory:
    def __init__(self, archive: ArchiveStore):
        self.archive = archive

    def project(self, account: str, project_id: str) -> dict:
        with self.archive.connect() as db:
            row = db.execute(
                "SELECT * FROM projects WHERE id=? AND account=?", (project_id, account)
            ).fetchone()
            if row is None:
                raise GatewayError("project_not_found", "Project was not found in this account.")
            chats = [
                r[0]
                for r in db.execute(
                    "SELECT chat FROM project_chats WHERE project=? ORDER BY chat", (project_id,)
                )
            ]
            return {
                "project_id": row["id"],
                "account_id": account,
                "title": row["title"],
                "created_at": row["created_at"],
                "chat_ids": chats,
            }

    def projects(self, account: str) -> list[dict]:
        with self.archive.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM projects WHERE account=? ORDER BY id", (account,)
                )
            ]
        return [self.project(account, project_id) for project_id in ids]

    def create(self, account: str, title: str, chat_ids: list[str]) -> dict:
        if not title.strip() or not chat_ids:
            raise GatewayError("invalid_request", "A project needs a title and selected chats.")
        project_id = new_id("project")
        with self.archive.connect() as db:
            if (
                db.execute("SELECT count(*) FROM projects WHERE account=?", (account,)).fetchone()[
                    0
                ]
                >= 100
            ):
                raise GatewayError(
                    "project_limit", "At most 100 projects are supported per account."
                )
            for chat in set(chat_ids):
                if not db.execute(
                    "SELECT 1 FROM chats WHERE account=? AND chat=?", (account, chat)
                ).fetchone():
                    raise GatewayError("archive_not_configured", "Select existing chat archives.")
            db.execute("INSERT INTO projects VALUES(?,?,?,?)", (project_id, account, title, now()))
            db.executemany(
                "INSERT INTO project_chats VALUES(?,?,?)",
                [(project_id, account, chat) for chat in sorted(set(chat_ids))],
            )
        return self.project(account, project_id)

    def propose(self, account: str, project: str, text: str, sources: list[dict]) -> dict:
        info = self.project(account, project)
        if not text.strip() or not sources:
            raise GatewayError("invalid_request", "Memory needs text and archived sources.")
        memory_id = new_id("memory")
        with self.archive.connect() as db:
            db.execute(
                "INSERT INTO project_memories VALUES(?,?,?,?,?,NULL)",
                (memory_id, project, text, "pending", now()),
            )
            for source in sources:
                chat, mid = source["chat_id"], source["message_id"]
                if chat not in info["chat_ids"]:
                    raise GatewayError("forbidden", "Source chat is outside this project.")
                row = db.execute(
                    "SELECT snapshot FROM messages WHERE account=? AND chat=? "
                    "AND mid=? AND deleted_at IS NULL",
                    (account, chat, mid),
                ).fetchone()
                if row is None:
                    raise GatewayError("source_unavailable", "Archive the active source first.")
                db.execute(
                    "INSERT OR IGNORE INTO memory_sources VALUES(?,?,?,?,?)",
                    (memory_id, account, chat, mid, content_hash(row["snapshot"])),
                )
        return {"memory_id": memory_id, "project_id": project, "state": "pending"}

    def approve(self, account: str, project: str, memory_id: str) -> dict:
        self.project(account, project)
        with self.archive.connect() as db:
            memory = db.execute(
                "SELECT * FROM project_memories WHERE id=? AND project=?", (memory_id, project)
            ).fetchone()
            if memory is None:
                raise GatewayError("memory_not_found", "Project memory was not found.")
            if memory["state"] == "stale":
                raise GatewayError("source_changed", "Propose a new memory from current sources.")
            rows = db.execute(
                "SELECT s.fingerprint AS original,m.snapshot AS current,m.deleted_at "
                "FROM memory_sources s JOIN messages m ON m.account=s.account AND m.chat=s.chat "
                "AND m.mid=s.mid WHERE s.memory=?",
                (memory_id,),
            ).fetchall()
            if not rows or any(
                r["deleted_at"] or r["original"] != content_hash(r["current"]) for r in rows
            ):
                raise GatewayError("source_changed", "Sources changed; propose a new memory.")
            db.execute(
                "UPDATE project_memories SET state='approved',approved_at=coalesce(approved_at,?) "
                "WHERE id=?",
                (now(), memory_id),
            )
        return {"memory_id": memory_id, "project_id": project, "state": "approved"}

    def entries(self, account: str, project: str, *, state="approved", limit=50, offset=0) -> dict:
        self.project(account, project)
        with self.archive.connect() as db:
            rows = db.execute(
                "SELECT * FROM project_memories WHERE project=? "
                + ("" if state == "all" else "AND state=? ")
                + "ORDER BY id LIMIT ? OFFSET ?",
                [project, *([] if state == "all" else [state]), limit + 1, offset],
            ).fetchall()
            entries = []
            for row in rows[:limit]:
                sources = [
                    {"chat_id": r["chat"], "message_id": r["mid"], "account_id": account}
                    for r in db.execute(
                        "SELECT chat,mid FROM memory_sources WHERE memory=? ORDER BY chat,mid",
                        (row["id"],),
                    )
                ]
                entries.append(
                    {
                        "memory_id": row["id"],
                        "text": row["text"],
                        "state": row["state"],
                        "created_at": row["created_at"],
                        "approved_at": row["approved_at"],
                        "sources": sources,
                    }
                )
            return {"memories": entries, "has_more": len(rows) > limit}

    def sources(self, project: str, memory_id: str) -> list[dict]:
        with self.archive.connect() as db:
            return [
                {"account_id": r["account"], "chat_id": r["chat"], "message_id": r["mid"]}
                for r in db.execute(
                    "SELECT s.account,s.chat,s.mid FROM memory_sources s "
                    "JOIN project_memories m ON m.id=s.memory WHERE m.project=? AND m.id=? "
                    "ORDER BY s.chat,s.mid",
                    (project, memory_id),
                )
            ]

    def delete(self, account: str, project: str, memory_id: str | None = None) -> dict:
        self.project(account, project)
        with self.archive.connect() as db:
            if memory_id is None:
                db.execute("DELETE FROM projects WHERE id=?", (project,))
            else:
                db.execute(
                    "DELETE FROM project_memories WHERE project=? AND id=?", (project, memory_id)
                )
        return {"project_id": project, "memory_id": memory_id, "deleted": True}
