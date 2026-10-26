"""Persistent ingestion rules and an idempotent media archive queue."""

import hashlib
import json
import time

from tg_mcp.errors import GatewayError

CONTENT_TYPES = (
    "photo",
    "video",
    "document",
    "audio",
    "voice",
    "video_note",
    "sticker",
    "animation",
)
KINDS = ("private", "group", "channel")
SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_rules (
    account TEXT NOT NULL DEFAULT '', chat TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
    rag_enabled INTEGER NOT NULL, s3_enabled INTEGER NOT NULL, content_types TEXT NOT NULL,
    PRIMARY KEY(account,chat,kind)
);
CREATE TABLE IF NOT EXISTS media_jobs (
    id TEXT PRIMARY KEY, account TEXT NOT NULL, chat TEXT NOT NULL, mid TEXT NOT NULL,
    descriptor TEXT NOT NULL, source_date TEXT NOT NULL, priority TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', downloaded INTEGER NOT NULL DEFAULT 0,
    size INTEGER NOT NULL DEFAULT 0, object_key TEXT, sha256 TEXT,
    error TEXT, retry_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(account,chat) REFERENCES chats(account,chat) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS media_message ON media_jobs(account,chat,mid);
CREATE INDEX IF NOT EXISTS media_queue ON media_jobs(status,retry_at,priority);
CREATE TABLE IF NOT EXISTS media_deletions (
    object_key TEXT PRIMARY KEY, retry_at REAL NOT NULL DEFAULT 0, error TEXT
);
CREATE TRIGGER IF NOT EXISTS media_delete BEFORE DELETE ON media_jobs
WHEN old.object_key IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM media_jobs WHERE object_key=old.object_key AND id!=old.id
) BEGIN
    INSERT OR IGNORE INTO media_deletions(object_key) VALUES(old.object_key);
END;
CREATE TABLE IF NOT EXISTS media_tombstones (
    account TEXT NOT NULL, chat TEXT NOT NULL, mid TEXT NOT NULL,
    PRIMARY KEY(account,chat,mid),
    FOREIGN KEY(account,chat) REFERENCES chats(account,chat) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS media_uploads (
    object_key TEXT PRIMARY KEY, job_id TEXT NOT NULL, sha256 TEXT NOT NULL,
    size INTEGER NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_state (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


class IngestionStore:
    def __init__(self, archive):
        self.archive = archive

    @staticmethod
    def effective(db, kind, account="", chat=""):
        if kind == "private":
            return {
                "kind": kind,
                "rag_enabled": True,
                "s3_enabled": True,
                "content_types": list(CONTENT_TYPES),
                "inherited": True,
            }
        row = db.execute(
            "SELECT * FROM ingestion_rules WHERE kind=? AND "
            "((account='' AND chat='') OR (account=? AND chat=?)) "
            "ORDER BY length(account) DESC LIMIT 1",
            (kind, account, chat),
        ).fetchone()
        if row:
            return {
                "kind": kind,
                "rag_enabled": bool(row["rag_enabled"]),
                "s3_enabled": bool(row["s3_enabled"]),
                "content_types": json.loads(row["content_types"]),
                "inherited": row["account"] == "",
            }
        return {
            "kind": kind,
            "rag_enabled": True,
            "s3_enabled": False,
            "content_types": list(CONTENT_TYPES),
            "inherited": True,
        }

    def policy(self, kind, account="", chat=""):
        with self.archive.connect() as db:
            return self.effective(db, kind, account, chat)

    def apply_chat(self, db, account, chat, kind=None, *, reset=True):
        row = db.execute(
            "SELECT * FROM chats WHERE account=? AND chat=?", (account, chat)
        ).fetchone()
        if row is None:
            return
        if kind not in KINDS:
            kind = row["kind"]
        if kind not in KINDS:
            kind = "private" if int(chat) > 0 else ("group" if not row["is_channel"] else "unknown")
        policy = self.effective(db, kind, account, chat)
        restart = reset and (
            (not row["rag_enabled"] and policy["rag_enabled"])
            or (not row["rag_enabled"] and not row["media_enabled"] and policy["s3_enabled"])
        )
        db.execute(
            "UPDATE chats SET kind=?,rag_enabled=?,media_enabled=? WHERE account=? AND chat=?",
            (kind, policy["rag_enabled"], policy["s3_enabled"], account, chat),
        )
        if restart:
            db.execute("DELETE FROM rag_heads WHERE account=? AND chat=?", (account, chat))
            db.execute(
                "UPDATE chats SET cursor=NULL,backfill_complete=0 WHERE account=? AND chat=?",
                (account, chat),
            )

    def set_policy(
        self, kind, rag_enabled, s3_enabled, content_types, *, account="", chat="", inherit=False
    ):
        if (
            kind not in KINDS
            or set(content_types) - set(CONTENT_TYPES)
            or bool(account) != bool(chat)
        ):
            raise GatewayError("invalid_request", "Invalid ingestion policy.")
        if kind == "private" and (
            not rag_enabled or not s3_enabled or set(content_types) != set(CONTENT_TYPES)
        ):
            raise GatewayError(
                "invalid_request", "Private chats always enable text RAG and all file types."
            )
        with self.archive.connect() as db:
            if chat:
                row = db.execute(
                    "SELECT kind FROM chats WHERE account=? AND chat=?", (account, chat)
                ).fetchone()
                if row is None or row["kind"] != kind:
                    raise GatewayError("invalid_request", "Use the discovered chat kind.")
            if inherit:
                db.execute(
                    "DELETE FROM ingestion_rules WHERE account=? AND chat=? AND kind=?",
                    (account, chat, kind),
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO ingestion_rules VALUES(?,?,?,?,?,?)",
                    (
                        account,
                        chat,
                        kind,
                        rag_enabled,
                        s3_enabled,
                        json.dumps(sorted(set(content_types))),
                    ),
                )
            rows = db.execute(
                "SELECT account,chat FROM chats WHERE kind=?"
                + (" AND account=? AND chat=?" if chat else ""),
                (kind, account, chat) if chat else (kind,),
            ).fetchall()
            for row in rows:
                self.apply_chat(db, row["account"], row["chat"])
            db.execute("INSERT OR REPLACE INTO ingestion_state VALUES('seed',0)")
            # A newly selected type may have been skipped by an earlier policy.
            db.execute(
                "UPDATE media_jobs SET status='pending',error=NULL,retry_at=0 "
                "WHERE status='skipped'" + (" AND account=? AND chat=?" if chat else ""),
                (account, chat) if chat else (),
            )
        return self.policy(kind, account, chat)

    def enqueue(self, db, account, chat, message):
        attachment = message.get("attachment")
        if not isinstance(attachment, dict):
            return
        config = db.execute(
            "SELECT enabled,media_enabled FROM chats WHERE account=? AND chat=?", (account, chat)
        ).fetchone()
        if not config or not config["enabled"] or not config["media_enabled"]:
            return
        mid = str(message["id"])
        if db.execute(
            "SELECT 1 FROM media_tombstones WHERE account=? AND chat=? AND mid=?",
            (account, chat, mid),
        ).fetchone():
            return
        identity = hashlib.sha256(
            json.dumps([account, chat, mid, attachment], sort_keys=True).encode()
        ).hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO media_jobs "
            "(id,account,chat,mid,descriptor,source_date,priority,size) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                identity,
                account,
                chat,
                mid,
                json.dumps(attachment),
                message.get("edit_date") or message.get("date") or "",
                message.get("edit_date") or message.get("date") or "",
                int(attachment.get("size") or 0),
            ),
        )

    def seed(self, limit=500):
        with self.archive.connect() as db:
            checkpoint = db.execute("SELECT value FROM ingestion_state WHERE key='seed'").fetchone()
            offset = checkpoint[0] if checkpoint else 0
            rows = db.execute(
                "SELECT rowid,account,chat,snapshot FROM messages "
                "WHERE rowid>? AND deleted_at IS NULL ORDER BY rowid LIMIT ?",
                (offset, limit),
            ).fetchall()
            for row in rows:
                self.enqueue(db, row["account"], row["chat"], json.loads(row["snapshot"]))
            if rows:
                db.execute(
                    "INSERT OR REPLACE INTO ingestion_state VALUES('seed',?)", (rows[-1]["rowid"],)
                )
        return bool(rows)

    def delete_message(self, db, account, mid, chat=None):
        rows = db.execute(
            "SELECT account,chat,retain_deleted FROM chats WHERE account=? AND enabled=1 "
            + ("AND chat=?" if chat is not None else "AND is_channel=0"),
            (account, chat) if chat is not None else (account,),
        ).fetchall()
        for row in rows:
            db.execute(
                "INSERT OR IGNORE INTO media_tombstones VALUES(?,?,?)", (account, row["chat"], mid)
            )
            if not row["retain_deleted"]:
                db.execute(
                    "DELETE FROM media_jobs WHERE account=? AND chat=? AND mid=?",
                    (account, row["chat"], mid),
                )

    def job(self, ready):
        if not ready:
            return None
        with self.archive.connect() as db:
            row = db.execute(
                "SELECT j.*,c.kind FROM media_jobs j JOIN chats c USING(account,chat) "
                "WHERE c.enabled=1 AND c.media_enabled=1 "
                "AND j.status IN ('pending','downloading','error') AND j.retry_at<=? "
                "AND j.account IN (" + ",".join("?" for _ in ready) + ") "
                "ORDER BY priority DESC,id LIMIT 1",
                [time.time(), *sorted(ready)],
            ).fetchone()
        return dict(row) if row else None

    def update_job(self, identity, **fields):
        allowed = {
            "status",
            "downloaded",
            "size",
            "object_key",
            "sha256",
            "descriptor",
            "error",
            "retry_at",
        }
        if not fields or set(fields) - allowed:
            raise ValueError("Invalid media job update")
        with self.archive.connect() as db:
            db.execute(
                "UPDATE media_jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
                [*fields.values(), identity],
            )

    def status(self):
        with self.archive.connect() as db:
            counts = {
                r["status"]: r["n"]
                for r in db.execute("SELECT status,count(*) n FROM media_jobs GROUP BY status")
            }
            size = db.execute(
                "SELECT coalesce(sum(size),0) FROM "
                "(SELECT max(size) size FROM media_jobs WHERE status='uploaded' "
                "GROUP BY object_key)"
            ).fetchone()[0]
            deletions = db.execute("SELECT count(*),count(error) FROM media_deletions").fetchone()
            files = db.execute(
                "SELECT count(DISTINCT object_key) FROM media_jobs WHERE status='uploaded'"
            ).fetchone()[0]
            media_counts = {
                (r["account"], r["chat"]): dict(r)
                for r in db.execute(
                    "SELECT account,chat,"
                    "count(DISTINCT CASE WHEN status='uploaded' THEN object_key END) "
                    "media_uploaded,"
                    "sum(CASE WHEN status IN ('pending','downloading','error') "
                    "THEN 1 ELSE 0 END) media_pending,"
                    "sum(CASE WHEN status='error' THEN 1 ELSE 0 END) media_errors "
                    "FROM media_jobs GROUP BY account,chat"
                ).fetchall()
            }
            chats = [
                {
                    **dict(r),
                    **self.effective(db, r["kind"], r["account"], r["chat"]),
                    **{
                        key: media_counts.get((r["account"], r["chat"]), {}).get(key, 0)
                        for key in ("media_uploaded", "media_pending", "media_errors")
                    },
                }
                for r in db.execute(
                    "SELECT account,chat,title,kind,enabled FROM chats ORDER BY account,title"
                ).fetchall()
            ]
        return {
            "jobs": counts,
            "uploaded_bytes": size,
            "files_uploaded": files,
            "pending_deletions": deletions[0],
            "deletion_errors": deletions[1],
            "chats": chats,
            "defaults": {k: self.policy(k) for k in KINDS},
            "content_types": list(CONTENT_TYPES),
        }
