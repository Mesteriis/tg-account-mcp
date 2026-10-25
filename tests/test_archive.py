import os
import stat
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_mcp.archive import ArchiveStore
from tg_mcp.errors import GatewayError, LocalError
from tg_mcp.storage import StateStore
from tg_mcp.telegram import UserGateway

A = "acct_aaaaaaaaaaaaaaaa"
B = "acct_bbbbbbbbbbbbbbbb"


def msg(mid="1", text="Решили использовать SQLite для архива", **extra):
    return {"id": mid, "text": text, "date": "2026-10-25T10:00:00+00:00", "sender_id": "7", **extra}


@pytest.fixture
def archive(tmp_path):
    value = ArchiveStore(StateStore(tmp_path))
    value.configure(A, "123", "Synthetic chat", enabled=True, retain_deleted=True)
    return value


def test_persistence_fts_filters_and_versions(archive, tmp_path):
    archive.ingest_page(A, "123", [msg()], "next-page")
    archive.record(
        A,
        "edited_message",
        {
            "chat_id": "123",
            "message": msg(
                text="Решили использовать PostgreSQL для архива",
                edit_date="2026-10-25T11:00:00+00:00",
            ),
        },
    )
    # Replayed edits are idempotent, old history cannot replace a new edit.
    archive.record(
        A,
        "edited_message",
        {
            "chat_id": "123",
            "message": msg(
                text="Решили использовать PostgreSQL для архива",
                edit_date="2026-10-25T11:00:00+00:00",
            ),
        },
    )
    archive.ingest_page(A, "123", [msg()], None)
    loaded = ArchiveStore(StateStore(tmp_path))
    assert not loaded.search(A, "123", "SQLite")["messages"]
    assert len(loaded.search(A, "123", "PostgreSQL архива")["messages"]) == 1
    assert len(loaded.versions(A, "123", "1")["versions"]) == 2
    assert loaded.status(A, "123")["backfill_complete"] is True
    assert not loaded.search(A, "123", "архива", sender_id="8")["messages"]
    assert not loaded.search(A, "123", "архива", date_to="2026-10-24")["messages"]
    assert len(loaded.search(A, "123", "архива", date_from="2026-10-25")["messages"]) == 1


def test_scope_isolation_and_account_purge(archive):
    archive.configure(B, "123", "B", enabled=True, retain_deleted=True)
    archive.configure(A, "456", "Other", enabled=True, retain_deleted=True)
    for account, chat, text in [(A, "123", "alpha"), (B, "123", "bravo"), (A, "456", "charlie")]:
        archive.ingest_page(account, chat, [msg(text=text)], None)
    assert not archive.search(A, "123", "bravo")["messages"]
    assert not archive.search(A, "123", "charlie")["messages"]
    archive.purge(A)
    assert archive.search(B, "123", "bravo")["messages"]
    with archive.connect() as db:
        assert db.execute("SELECT count(*) FROM message_fts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 1


def test_retained_deletion_is_hidden_by_default_and_never_resurrected(archive):
    archive.ingest_page(A, "123", [msg()], None)
    archive.record(A, "deleted_messages", {"chat_id": "123", "message_ids": ["1"]})
    archive.ingest_page(A, "123", [msg()], None)
    assert not archive.search(A, "123", "SQLite")["messages"]
    result = archive.search(A, "123", "SQLite", include_deleted=True)["messages"]
    assert len(result) == 1 and result[0]["deleted_at"]
    archive.configure(A, "123", "Synthetic", enabled=True, retain_deleted=False)
    assert not archive.search(A, "123", "SQLite", include_deleted=True)["messages"]
    assert not archive.versions(A, "123", "1")["versions"]
    archive.ingest_page(A, "123", [msg()], None)
    assert not archive.search(A, "123", "SQLite", include_deleted=True)["messages"]


def test_unknown_channel_deletion_before_backfill_creates_tombstone(archive):
    archive.record(A, "deleted_messages", {"chat_id": "123", "message_ids": ["1"]})
    archive.ingest_page(A, "123", [msg()], None)
    assert not archive.search(A, "123", "SQLite", include_deleted=True)["messages"]
    assert not archive.versions(A, "123", "1")["versions"]


def test_missing_peer_deletion_is_account_scoped_and_excludes_channels(archive):
    # A basic group whose numeric ID starts with 100 must not be mistaken for a channel.
    archive.configure(A, "-10023", "Basic group", enabled=True, retain_deleted=True)
    archive.configure(
        A, "-1000000000023", "Channel", enabled=True, retain_deleted=True, is_channel=True
    )
    archive.configure(B, "123", "Other account", enabled=True, retain_deleted=True)
    for account, chat in [(A, "-10023"), (A, "-1000000000023"), (B, "123")]:
        archive.ingest_page(account, chat, [msg()], None)
    archive.record(A, "deleted_messages", {"chat_id": None, "message_ids": ["1"]})
    assert not archive.search(A, "-10023", "SQLite")["messages"]
    assert archive.search(A, "-1000000000023", "SQLite")["messages"]
    assert archive.search(B, "123", "SQLite")["messages"]


def test_disabled_and_unselected_chats_are_not_captured(archive):
    archive.configure(A, "123", "Synthetic", enabled=False, retain_deleted=True)
    for chat in ["123", "456"]:
        archive.record(A, "new_message", {"chat_id": chat, "message": msg()})
        archive.ingest_page(A, chat, [msg()], None)
    assert archive.status(A, "123")["message_count"] == 0
    with pytest.raises(GatewayError, match="archive_not_configured"):
        archive.status(A, "456")


def test_pagination_export_and_purge(archive):
    archive.ingest_page(A, "123", [msg(str(i)) for i in range(1, 4)], None)
    first = archive.search(A, "123", "SQLite", limit=2)
    second = archive.search(A, "123", "SQLite", limit=2, offset=2)
    assert first["has_more"] and not second["has_more"]
    assert {m["id"] for m in first["messages"]}.isdisjoint(m["id"] for m in second["messages"])
    assert [m["id"] for m in archive.export(A, "123")["messages"]] == ["1", "2", "3"]
    archive.purge(A, "123")
    with archive.connect() as db:
        for table in ["messages", "versions", "message_fts", "chats"]:
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize(
    "query", ['" OR 1=1 --', "NEAR(sqlite,archiva)", "*", '"', "SQLite OR secrets"]
)
def test_queries_are_literal_and_cannot_inject_fts_or_sql(archive, query):
    archive.ingest_page(A, "123", [msg()], None)
    assert not archive.search(A, "123", query)["messages"]
    assert archive.status(A, "123")["message_count"] == 1


def test_private_database_and_symlink_rejection(tmp_path):
    state = StateStore(tmp_path)
    archive = ArchiveStore(state)
    assert stat.S_IMODE(archive.path.stat().st_mode) == 0o600
    archive.path.unlink()
    target = tmp_path / "target"
    target.write_text("do not change")
    archive.path.symlink_to(target)
    with pytest.raises(LocalError):
        ArchiveStore(state)
    assert target.read_text() == "do not change"


def test_journal_links_are_rejected(archive, tmp_path):
    target = tmp_path / "unrelated"
    target.write_text("preserve")
    os.chmod(target, 0o600)
    (tmp_path / "archive.sqlite3-journal").symlink_to(target)
    with pytest.raises(LocalError):
        archive.status(A, "123")


async def test_gateway_sync_resume_events_and_error_status(archive):
    client = SimpleNamespace()
    gateway = UserGateway(client, "t" * 43, A, archive=archive)
    gateway.history = AsyncMock(return_value={"messages": [msg()], "next_cursor": "page2"})
    await gateway.sync_archive_chat("123")
    restarted = UserGateway(client, "t" * 43, A, archive=archive)
    restarted.history = AsyncMock(return_value={"messages": [msg("2")], "next_cursor": None})
    await restarted.sync_archive_chat("123")
    restarted.history.assert_awaited_once_with("123", limit=100, cursor="page2")
    assert archive.status(A, "123")["backfill_complete"]
    await restarted._on_edited_message(
        SimpleNamespace(
            chat_id=123,
            message=SimpleNamespace(
                id=1,
                date=datetime(2026, 10, 25, 10, tzinfo=UTC),
                edit_date=datetime(2026, 10, 25, 11, tzinfo=UTC),
                message="Changed decision",
                sender_id=7,
                out=False,
                reply_to_msg_id=None,
                media=None,
            ),
        )
    )
    assert archive.search(A, "123", "Changed")["messages"]
    restarted.history.side_effect = GatewayError("rate_limited", "Wait.", 120)
    with pytest.raises(GatewayError):
        await restarted.sync_archive_chat("123")
    assert archive.status(A, "123")["error"] == "rate_limited"
    restarted.history.reset_mock()
    with pytest.raises(GatewayError, match="rate_limited"):
        await restarted.sync_archive_chat("123", restart=True)
    restarted.history.assert_not_awaited()
    restarted._archive_retry_until = 0
    restarted.history.side_effect = None
    await restarted.sync_archive_chat("123", restart=True)
    assert restarted.history.call_args.kwargs["cursor"] is None


def test_page_and_progress_commit_atomically(archive):
    with pytest.raises(KeyError):
        archive.ingest_page(A, "123", [msg(), {"text": "invalid"}], "next")
    assert archive.status(A, "123")["message_count"] == 0
    assert archive.configured(A)[0]["cursor"] is None
    with archive.connect() as db:
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM message_fts").fetchone()[0] == 0


def test_unknown_schema_is_rejected(archive, tmp_path):
    with archive.connect() as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(GatewayError, match="archive_version"):
        ArchiveStore(StateStore(tmp_path))
