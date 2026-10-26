import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_mcp.archive import ArchiveStore
from tg_mcp.errors import GatewayError
from tg_mcp.ingestion import CONTENT_TYPES
from tg_mcp.media_archive import MediaArchive
from tg_mcp.storage import StateStore

A = "acct_aaaaaaaaaaaaaaaa"


def message(mid="1", **extra):
    return {
        "id": mid,
        "text": "Synthetic caption",
        "date": "2026-10-26T00:00:00+00:00",
        "attachment": {"kind": "document", "media_id": "42", "size": 3, "file_name": "fixture.bin"},
        **extra,
    }


@pytest.fixture
def archive(tmp_path):
    value = ArchiveStore(StateStore(tmp_path))
    value.configure(A, "123", "Synthetic", enabled=True, retain_deleted=False)
    value.discover(A, "-1001", "Synthetic group", is_channel=True, chat_kind="group")
    return value


def test_private_fixed_group_override_and_inheritance(archive):
    q = archive.ingestion
    assert q.policy("private")["s3_enabled"]
    with pytest.raises(GatewayError):
        q.set_policy("private", True, False, list(CONTENT_TYPES))
    assert not q.policy("group")["s3_enabled"]
    q.set_policy("group", False, True, ["photo"])
    assert q.policy("group", A, "-1001")["content_types"] == ["photo"]
    q.set_policy("group", True, False, ["document"], account=A, chat="-1001")
    q.set_policy("group", False, True, ["video"])
    assert q.policy("group", A, "-1001")["content_types"] == ["document"]
    q.set_policy("group", True, False, [], account=A, chat="-1001", inherit=True)
    assert q.policy("group", A, "-1001")["content_types"] == ["video"]
    with pytest.raises(GatewayError):
        q.set_policy("group", False, False, [], account=A, chat="123")
    with pytest.raises(GatewayError):
        q.set_policy("group", True, True, ["unknown"])


def test_media_only_and_reenable_history(archive):
    q = archive.ingestion
    q.set_policy("group", False, True, ["document"])
    archive.ingest_page(A, "-1001", [message()], None)
    assert not archive.search(A, "-1001", "Synthetic")["messages"]
    assert q.job({A})["chat"] == "-1001"
    q.set_policy("group", True, True, ["document"])
    assert not archive.status(A, "-1001")["backfill_complete"]


def test_queue_idempotence_and_purge_cleanup(archive):
    for _ in range(2):
        archive.ingest_page(A, "123", [message()], None)
    q = archive.ingestion
    job = q.job({A})
    assert q.status()["jobs"] == {"pending": 1}
    q.update_job(
        job["id"], status="uploaded", object_key="telegram/object", sha256="digest", size=3
    )
    assert archive.purge(A, "123")["media_cleanup_pending"] == 1
    assert q.status()["jobs"] == {}


def test_deleted_media_only_cannot_resurrect(archive):
    q = archive.ingestion
    q.set_policy("group", False, True, ["document"])
    archive.ingest_page(A, "-1001", [message()], None)
    archive.record(A, "deleted_messages", {"chat_id": "-1001", "message_ids": ["1"]})
    archive.ingest_page(A, "-1001", [message()], None)
    assert q.job({A}) is None


def test_seed_is_persistent_and_backfills_new_policy(archive):
    archive.ingest_page(A, "-1001", [message()], None)
    assert not archive.ingestion.job({A})
    archive.ingestion.seed()
    archive.ingestion.set_policy("group", True, True, ["document"])
    assert archive.ingestion.seed()
    assert archive.ingestion.job({A})
    assert not archive.ingestion.seed()
    assert not ArchiveStore(archive.store).ingestion.seed()


class Storage:
    prefix = "telegram"

    def __init__(self):
        self.objects = {}
        self.calls = 0
        self.fail = False

    def head(self, key):
        if key not in self.objects:
            return None
        data, digest = self.objects[key]
        return {"ContentLength": len(data), "Metadata": {"sha256": digest}}

    def upload(self, path, key, size, digest, mime):
        self.calls += 1
        if self.fail:
            raise OSError("synthetic")
        data = path.read_bytes()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == digest
        self.objects[key] = (data, digest)

    def delete(self, key):
        self.objects.pop(key, None)


def worker(archive):
    storage = Storage()
    gateway = SimpleNamespace(
        archive_media_part=AsyncMock(
            return_value={
                "data": b"abc",
                "size": 3,
                "complete": True,
                "descriptor": message()["attachment"],
            }
        )
    )
    manager = SimpleNamespace(
        archive=archive, store=archive.store, user_gateway=AsyncMock(return_value=gateway)
    )
    return MediaArchive(manager, None, storage), gateway, storage


async def test_upload_failure_resumes_complete_spool_without_redownload(archive):
    archive.ingest_page(A, "123", [message()], None)
    w, g, s = worker(archive)
    job = w.queue.job({A})
    s.fail = True
    with pytest.raises(OSError):
        await w.transfer(job)
    assert w._path(job).read_bytes() == b"abc"
    s.fail = False
    await w.transfer(w.queue.job({A}))
    assert g.archive_media_part.await_count == 1
    assert w.queue.status()["files_uploaded"] == 1
    assert not w._path(job).exists()
    archive.purge(A, "123")
    await w.cleanup()
    assert not s.objects


async def test_upload_intent_recovers_and_concurrent_purge_cleans(archive):
    archive.ingest_page(A, "123", [message()], None)
    w, g, s = worker(archive)
    job = w.queue.job({A})
    key = "telegram/object"
    digest = hashlib.sha256(b"abc").hexdigest()
    s.objects[key] = (b"abc", digest)
    with archive.connect() as db:
        db.execute("INSERT INTO media_uploads VALUES(?,?,?,?,?)", (key, job["id"], digest, 3, 0))
    archive.purge(A, "123")
    await w.reconcile()
    assert w.queue.status()["pending_deletions"] == 1
    await w.cleanup()
    assert not s.objects


async def test_duplicate_file_versions_share_object_until_last_deleted(archive):
    archive.ingest_page(A, "123", [message()], None)
    w, g, s = worker(archive)
    await w.transfer(w.queue.job({A}))
    archive.ingest_page(
        A,
        "123",
        [
            message(
                attachment={**message()["attachment"], "file_name": "renamed.bin"},
                edit_date="2026-10-26T01:00:00+00:00",
            )
        ],
        None,
    )
    await w.transfer(w.queue.job({A}))
    assert s.calls == 1 and w.queue.status()["files_uploaded"] == 1
    with archive.connect() as db:
        first = db.execute("SELECT id FROM media_jobs LIMIT 1").fetchone()[0]
        db.execute("DELETE FROM media_jobs WHERE id=?", (first,))
    assert w.queue.status()["pending_deletions"] == 0
    archive.purge(A, "123")
    assert w.queue.status()["pending_deletions"] == 1


async def test_type_exclusion_discards_spool(archive):
    archive.ingestion.set_policy("group", True, True, ["photo"])
    archive.ingest_page(A, "-1001", [message()], None)
    w, g, s = worker(archive)
    job = w.queue.job({A})
    g.archive_media_part.return_value = {"skipped": True}
    await w.transfer(job)
    assert w.queue.status()["jobs"] == {"skipped": 1}
    assert not s.objects


async def test_unaligned_partial_is_resumed_at_safe_boundary(archive):
    archive.ingest_page(A, "123", [message()], None)
    w, g, s = worker(archive)
    job = w.queue.job({A})
    path = w._path(job)
    import os

    with os.fdopen(w.spool_store.open_private(path, os.O_CREAT | os.O_WRONLY), "wb") as out:
        out.write(b"x")
    await w.transfer(job)
    assert g.archive_media_part.call_args.args[2] == 0
    assert w.queue.status()["files_uploaded"] == 1


def test_spool_symlink_is_rejected(archive, tmp_path):
    archive.ingest_page(A, "123", [message()], None)
    w, g, s = worker(archive)
    job = w.queue.job({A})
    path = w._path(job)
    path.symlink_to(tmp_path / "outside")
    from tg_mcp.errors import LocalError

    with pytest.raises(LocalError):
        w._path(job)


def test_s3_settings_require_private_endpoint_complete_credentials_and_background(tmp_path):
    from pydantic import ValidationError

    from tg_mcp.config import Settings

    kwargs = dict(
        state_dir=tmp_path,
        allowed_hosts=["localhost"],
        background_rag=True,
        embedding_url="http://127.0.0.1:11434",
        embedding_model="local",
        s3_endpoint="http://127.0.0.1:3900",
        s3_bucket="archive",
        s3_access_key="synthetic",
        s3_secret_key="private-synthetic-secret",
    )
    assert Settings(**kwargs).s3_secret_key.get_secret_value() == "private-synthetic-secret"
    for extra in [
        dict(s3_secret_key=None),
        dict(background_rag=False),
        dict(s3_endpoint="https://example.com"),
    ]:
        with pytest.raises(ValidationError) as failure:
            Settings(**{**kwargs, **extra})
        assert "private-synthetic-secret" not in str(failure.value)


def test_chat_status_counts_unique_objects_and_retains_separate_queues(archive):
    q = archive.ingestion
    archive.ingest_page(A, "123", [message(), message("2"), message("3")], None)
    with archive.connect() as db:
        jobs = db.execute("SELECT id FROM media_jobs ORDER BY mid").fetchall()
    for job in jobs[:2]:
        q.update_job(job["id"], status="uploaded", object_key="telegram/same-file")
    q.update_job(jobs[2]["id"], status="error", error="synthetic")
    status = q.status()
    c = next(c for c in status["chats"] if c["chat"] == "123")
    assert c["media_uploaded"] == 1 and c["media_pending"] == 1 and c["media_errors"] == 1
    other = next(c for c in status["chats"] if c["chat"] == "-1001")
    assert other["media_uploaded"] == other["media_pending"] == other["media_errors"] == 0
    assert "object_key" not in c and "descriptor" not in c
