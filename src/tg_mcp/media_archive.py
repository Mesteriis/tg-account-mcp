"""Private S3 media archival: bounded resumable downloads, durable upload intents."""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import stat
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from tg_mcp.errors import GatewayError, LocalError
from tg_mcp.storage import StateStore

RESERVE = 5 * 1024**3


class S3Storage:
    def __init__(self, settings):
        self.bucket, self.prefix = settings.s3_bucket, settings.s3_prefix
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(
                connect_timeout=5,
                read_timeout=30,
                proxies={},
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def head(self, key):
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return None
            raise

    def upload(self, path, key, size, digest, mime):
        existing = self.head(key)
        if (
            existing
            and existing.get("ContentLength") == size
            and existing.get("Metadata", {}).get("sha256") == digest
        ):
            return
        with path.open("rb") as body:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentLength=size,
                ContentType=mime or "application/octet-stream",
                Metadata={"sha256": digest},
            )
        result = self.head(key)
        if (
            not result
            or result["ContentLength"] != size
            or result.get("Metadata", {}).get("sha256") != digest
        ):
            raise GatewayError("storage_integrity", "S3 upload verification failed.")

    def delete(self, key):
        if not key.startswith(self.prefix + "/"):
            raise GatewayError("storage_scope", "Refusing an object outside this archive prefix.")
        self.client.delete_object(Bucket=self.bucket, Key=key)


class MediaArchive:
    def __init__(self, manager, settings, storage=None):
        self.manager, self.archive = manager, manager.archive
        self.queue = self.archive.ingestion
        self.storage = storage or S3Storage(settings)
        self.spool = manager.store.root / "media-spool"
        self.spool.mkdir(mode=0o700, exist_ok=True)
        info = self.spool.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise LocalError("Media spool must be a private owned directory.")
        self.spool_store = StateStore(self.spool)
        self.tasks = []
        self.error = None
        self.seed_error = None
        self._upload_task = None
        self._served = {}

    def start(self):
        self.tasks = [
            asyncio.create_task(self.seed_loop(), name="tg-media-seed"),
            asyncio.create_task(self.transfer_loop(), name="tg-media-transfer"),
        ]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # A synchronous SDK upload cannot be cancelled by cancelling its awaiter.
        if self._upload_task:
            with contextlib.suppress(GatewayError, BotoCoreError, ClientError, OSError):
                await self._upload_task
        self.tasks = []
        if isinstance(self.storage, S3Storage):
            self.storage.client.close()

    def ready(self):
        return {
            a["account_id"]
            for a in self.manager.list_accounts()
            if a["status"] == "ready" and a.get("enabled", True)
        }

    def _path(self, job):
        identity = job["id"]
        if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise LocalError("Invalid media spool identity.")
        path = self.spool / (identity + ".part")
        self.manager.store._check_file(path)
        return path

    def clean_spool(self):
        for path in self.spool.glob("*.part"):
            identity = path.stem
            if len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
                continue
            self.manager.store._check_file(path)
            with self.archive.connect() as db:
                row = db.execute("SELECT status FROM media_jobs WHERE id=?", (identity,)).fetchone()
                intent = db.execute(
                    "SELECT 1 FROM media_uploads WHERE job_id=?", (identity,)
                ).fetchone()
            if not intent and (not row or row["status"] in ("uploaded", "skipped")):
                path.unlink(missing_ok=True)

    async def seed_loop(self):
        while True:
            try:
                work = self.queue.seed()
                if not work:
                    self.clean_spool()
                self.seed_error = None
            except (OSError, LocalError, sqlite3.Error):
                self.seed_error = "media_queue_unavailable"
                work = False
            await asyncio.sleep(0.1 if work else 30)

    async def cleanup(self):
        with self.archive.connect() as db:
            row = db.execute(
                "SELECT * FROM media_deletions WHERE retry_at<=? LIMIT 1", (time.time(),)
            ).fetchone()
        if row:
            try:
                await asyncio.to_thread(self.storage.delete, row["object_key"])
                with self.archive.connect() as db:
                    db.execute(
                        "DELETE FROM media_deletions WHERE object_key=?", (row["object_key"],)
                    )
            except (BotoCoreError, ClientError, GatewayError):
                with self.archive.connect() as db:
                    db.execute(
                        "UPDATE media_deletions SET retry_at=?,error='storage_unavailable' "
                        "WHERE object_key=?",
                        (time.time() + 60, row["object_key"]),
                    )
            return True
        return False

    def _finish(self, job, key, digest, size):
        with self.archive.connect() as db:
            active = db.execute(
                "SELECT c.enabled,c.media_enabled,c.kind,j.descriptor,j.account,j.chat "
                "FROM media_jobs j JOIN chats c USING(account,chat) WHERE j.id=?",
                (job["id"],),
            ).fetchone()
            allowed = active and self.queue.effective(
                db, active["kind"], active["account"], active["chat"]
            )
            if (
                active
                and active["enabled"]
                and active["media_enabled"]
                and json.loads(active["descriptor"]).get("kind", "document")
                in allowed["content_types"]
            ):
                db.execute(
                    "UPDATE media_jobs SET status='uploaded',object_key=?,sha256=?,size=?,"
                    "error=NULL,retry_at=0 WHERE id=?",
                    (key, digest, size, job["id"]),
                )
            else:
                if not db.execute(
                    "SELECT 1 FROM media_jobs WHERE object_key=? AND status='uploaded'", (key,)
                ).fetchone():
                    db.execute(
                        "INSERT OR IGNORE INTO media_deletions(object_key) VALUES(?)", (key,)
                    )
                db.execute(
                    "UPDATE media_jobs SET status='skipped',error='policy_disabled' WHERE id=?",
                    (job["id"],),
                )
            db.execute("DELETE FROM media_uploads WHERE object_key=?", (key,))

    async def reconcile(self):
        with self.archive.connect() as db:
            rows = db.execute("SELECT * FROM media_uploads ORDER BY created LIMIT 10").fetchall()
        for row in rows:
            with self.archive.connect() as db:
                job = db.execute("SELECT * FROM media_jobs WHERE id=?", (row["job_id"],)).fetchone()
            obj = await asyncio.to_thread(self.storage.head, row["object_key"])
            if (
                obj
                and obj.get("ContentLength") == row["size"]
                and obj.get("Metadata", {}).get("sha256") == row["sha256"]
            ):
                self._finish(
                    dict(job) if job else {"id": row["job_id"]},
                    row["object_key"],
                    row["sha256"],
                    row["size"],
                )
            elif not job and time.time() - row["created"] > 300:
                await asyncio.to_thread(self.storage.delete, row["object_key"])
                with self.archive.connect() as db:
                    db.execute("DELETE FROM media_uploads WHERE object_key=?", (row["object_key"],))

    async def transfer(self, job):
        path = self._path(job)
        with self.archive.connect() as db:
            config = db.execute(
                "SELECT enabled,media_enabled FROM chats WHERE account=? AND chat=?",
                (job["account"], job["chat"]),
            ).fetchone()
        if not config or not config["enabled"] or not config["media_enabled"]:
            return
        policy = self.queue.policy(job["kind"], job["account"], job["chat"])
        offset = path.stat().st_size if path.exists() else 0
        if shutil.disk_usage(self.spool).free < max(0, job["size"] - offset) + RESERVE:
            raise GatewayError("storage_full", "Free disk reserve would be exceeded.")
        descriptor = json.loads(job["descriptor"])
        if path.exists() and offset == job["size"]:
            part = {
                "data": b"",
                "descriptor": descriptor,
                "size": job["size"],
                "complete": True,
                "skipped": descriptor.get("kind", "document") not in policy["content_types"],
            }
        else:
            if offset % (512 * 1024):
                offset = offset // (512 * 1024) * (512 * 1024)
                fd = self.spool_store.open_private(path, os.O_RDWR)
                with os.fdopen(fd, "r+b") as output:
                    output.truncate(offset)
            gateway = await self.manager.user_gateway(job["account"])
            async with asyncio.timeout(180):
                part = await gateway.archive_media_part(
                    job["chat"], job["mid"], offset, policy["content_types"], descriptor
                )
        if part.get("skipped"):
            self.queue.update_job(job["id"], status="skipped", error="type_excluded")
            if path.exists():
                path.unlink()
            return
        current = part["descriptor"]
        with self.archive.connect() as db:
            if db.execute("SELECT 1 FROM media_jobs WHERE id=?", (job["id"],)).fetchone() is None:
                if path.exists():
                    path.unlink()
                return
            # Reuse a previously stored version of the same Telegram file in this message.
            completed = db.execute(
                "SELECT * FROM media_jobs WHERE account=? AND chat=? AND mid=? "
                "AND status='uploaded'",
                (job["account"], job["chat"], job["mid"]),
            ).fetchall()
        self.queue.update_job(job["id"], descriptor=json.dumps(current))
        for old in completed:
            if (
                current.get("media_id")
                and json.loads(old["descriptor"]).get("media_id") == current["media_id"]
            ):
                self._finish(job, old["object_key"], old["sha256"], old["size"])
                if path.exists():
                    path.unlink()
                return
        if part["size"] < offset or (not part["complete"] and not part["data"]):
            raise GatewayError("source_changed", "Attachment size changed.")
        fd = self.spool_store.open_private(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND)
        with os.fdopen(fd, "ab") as output:
            output.write(part["data"])
            output.flush()
            os.fsync(output.fileno())
        downloaded = offset + len(part["data"])
        self.queue.update_job(
            job["id"],
            status="downloading",
            downloaded=downloaded,
            size=part["size"],
            descriptor=json.dumps(current),
            error=None,
            retry_at=0,
        )
        if not part["complete"]:
            return
        if downloaded != part["size"]:
            raise GatewayError("storage_integrity", "Attachment length mismatch.")

        def digest_file():
            with path.open("rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest()

        digest = await asyncio.to_thread(digest_file)
        key = f"{self.storage.prefix}/{job['account']}/{job['chat']}/{job['mid']}/{job['id']}"
        with self.archive.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO media_uploads VALUES(?,?,?,?,?)",
                (key, job["id"], digest, downloaded, time.time()),
            )
        self._upload_task = asyncio.create_task(
            asyncio.to_thread(
                self.storage.upload, path, key, downloaded, digest, current.get("mime_type")
            )
        )
        try:
            await asyncio.shield(self._upload_task)
        finally:
            if self._upload_task.done():
                self._upload_task = None
        self._finish(job, key, digest, downloaded)
        path.unlink(missing_ok=True)

    async def transfer_loop(self):
        reconciled = False
        while True:
            job = None
            try:
                if not reconciled:
                    await self.reconcile()
                    reconciled = True
                if await self.cleanup():
                    await asyncio.sleep(0)
                ready = self.ready()
                self._served = {a: t for a, t in self._served.items() if a in ready}
                jobs = [j for a in ready if (j := self.queue.job({a})) is not None]
                job = (
                    min(jobs, key=lambda j: (self._served.get(j["account"], 0), j["id"]))
                    if jobs
                    else None
                )
                if job:
                    self._served[job["account"]] = time.monotonic()
                if job:
                    await self.transfer(job)
                self.error = None
            except GatewayError as exc:
                self.error = exc.code
                if job:
                    terminal = exc.code in {"source_changed", "file_unavailable", "invalid_offset"}
                    self.queue.update_job(
                        job["id"],
                        status="skipped" if terminal else "error",
                        error=exc.code,
                        retry_at=time.time() + max(10, exc.retry_after or 60),
                    )
            except (BotoCoreError, ClientError, OSError, TimeoutError, sqlite3.Error):
                self.error = "media_transfer_unavailable"
                if job:
                    self.queue.update_job(
                        job["id"], status="error", error=self.error, retry_at=time.time() + 60
                    )
            except Exception:
                self.error = "media_worker_failed"
                logging.getLogger("tg_mcp").error("Media archive worker failed")
                if job:
                    self.queue.update_job(
                        job["id"], status="error", error=self.error, retry_at=time.time() + 60
                    )
            await asyncio.sleep(0.1 if job and not self.error else 1)

    def status(self):
        return {
            "configured": True,
            "running": bool(self.tasks) and all(not t.done() for t in self.tasks),
            "last_error": self.error or self.seed_error,
            **self.queue.status(),
        }
