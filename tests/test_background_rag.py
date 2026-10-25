import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from tg_mcp.archive import ArchiveStore
from tg_mcp.background import BackgroundRAG
from tg_mcp.config import Settings
from tg_mcp.errors import GatewayError
from tg_mcp.storage import StateStore
from tg_mcp.telegram import UserGateway

A = "acct_aaaaaaaaaaaaaaaa"
B = "acct_bbbbbbbbbbbbbbbb"


@pytest.fixture
def worker(tmp_path):
    archive = ArchiveStore(StateStore(tmp_path))
    accounts = [{"account_id": A, "status": "ready", "enabled": True}]
    manager = SimpleNamespace(
        archive=archive, list_accounts=lambda: accounts, user_gateway=AsyncMock()
    )
    settings = Settings(
        state_dir=tmp_path,
        allowed_hosts=["localhost"],
        background_rag=True,
        embedding_url="http://localhost:11434",
        embedding_model="synthetic:local",
    )
    rag = BackgroundRAG(manager, settings)
    rag.provider = SimpleNamespace(
        model_key=AsyncMock(return_value="synthetic"),
        embed=AsyncMock(side_effect=lambda texts, key: [[1.0, 0.0] for _ in texts]),
    )
    rag.index.provider = rag.provider
    return rag, accounts


async def test_discovery_includes_future_accounts_and_skips_disabled_accounts(worker):
    rag, accounts = worker
    gateway = SimpleNamespace(discover_archives=AsyncMock())
    rag.manager.user_gateway.return_value = gateway
    await rag.discover()
    assert rag.manager.user_gateway.await_count == 1
    accounts.append({"account_id": B, "status": "ready", "enabled": True})
    await rag.discover()
    assert rag.manager.user_gateway.await_count == 3
    accounts[1]["enabled"] = False
    await rag.discover()
    assert rag.manager.user_gateway.await_count == 4


async def test_discovery_rate_limit_does_not_stop_other_accounts(worker):
    rag, accounts = worker
    accounts.append({"account_id": B, "status": "ready"})
    first = SimpleNamespace(
        discover_archives=AsyncMock(side_effect=GatewayError("rate_limited", "Wait", 120))
    )
    second = SimpleNamespace(discover_archives=AsyncMock())
    rag.manager.user_gateway.side_effect = lambda account: first if account == A else second
    await rag.discover()
    await rag.discover()
    assert first.discover_archives.await_count == 1
    assert second.discover_archives.await_count == 2


async def test_fair_queue_reindexes_edits_and_resumes_after_restart(worker):
    rag, _ = worker
    for chat in ["123", "456"]:
        rag.archive.configure(A, chat, "Synthetic", enabled=True, retain_deleted=False)
        rag.archive.ingest_page(
            A, chat, [{"id": str(i), "text": "sample"} for i in range(1, 6)], None
        )
    await rag.index_once()
    await rag.index_once()
    with rag.archive.connect() as db:
        counts = db.execute(
            "SELECT m.chat,count(*) FROM message_vectors v JOIN messages m "
            "ON m.rowid=v.message GROUP BY m.chat"
        ).fetchall()
        assert {row[0]: row[1] for row in counts} == {"123": 4, "456": 4}
    restarted = BackgroundRAG(rag.manager, rag.settings)
    restarted.provider = rag.provider
    restarted.index.provider = rag.provider
    await restarted.index_once()
    assert restarted.indexed == 1
    rag.archive.record(
        A,
        "edited_message",
        {
            "chat_id": "123",
            "message": {"id": "1", "text": "changed", "edit_date": "2026-10-25T12:00:00+00:00"},
        },
    )
    assert any(job[2] == "123" for job in rag.jobs("synthetic"))
    rag.archive.purge(A, "123")
    assert all(job[2] != "123" for job in rag.jobs("synthetic"))


async def test_index_loop_backoff_and_error_are_observable(worker, monkeypatch):
    rag, _ = worker
    rag.index_once = AsyncMock(side_effect=GatewayError("embedding_timeout", "Timed out"))
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr("tg_mcp.background.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await rag.index_loop()
    sleep.assert_awaited_once_with(10)
    assert rag.status()["last_error"] == "embedding_timeout"


async def test_worker_tasks_cancel_cleanly(worker):
    rag, _ = worker
    rag.discover = AsyncMock()
    rag.index_once = AsyncMock()
    rag.start()
    tasks = list(rag.tasks)
    await asyncio.sleep(0)
    await rag.close()
    assert all(t.done() for t in tasks)
    assert rag.status()["running"] is False


async def test_gateway_discovery_has_no_tool_dialog_cap_and_respects_exclusions(worker):
    rag, _ = worker

    async def dialogs(**kwargs):
        assert kwargs == {"limit": None}
        for chat, channel in [(1, False), (-2, False), (-1000000000003, True)]:
            yield SimpleNamespace(id=chat, name="Synthetic", is_channel=channel)

    client = SimpleNamespace(is_user_authorized=AsyncMock(return_value=True), iter_dialogs=dialogs)
    gateway = UserGateway(client, "t" * 43, A, archive=rag.archive)
    rag.archive.configure(A, "-2", "Paused", enabled=False, retain_deleted=False)
    assert await gateway.discover_archives() == 2
    assert rag.archive.status(A, "-2")["enabled"] is False
    assert rag.archive.status(A, "-1000000000003")["is_channel"] is True
    rag.archive.purge(A, "1")
    await gateway.discover_archives()
    with pytest.raises(GatewayError, match="archive_not_configured"):
        rag.archive.status(A, "1")
    rag.archive.configure(A, "1", "Resume", enabled=True, retain_deleted=False)
    assert rag.archive.status(A, "1")["enabled"]


async def test_new_chat_is_captured_immediately_but_not_after_account_removal(worker):
    rag, _ = worker
    active = True
    gateway = UserGateway(
        SimpleNamespace(), "t" * 43, A, archive=rag.archive, auto_archive=lambda: active
    )
    event = SimpleNamespace(
        chat_id=123,
        chat=None,
        is_channel=False,
        message=SimpleNamespace(
            id=1,
            message="synthetic",
            date=datetime(2026, 10, 25, tzinfo=UTC),
            sender_id=1,
            out=False,
            reply_to_msg_id=None,
            media=None,
        ),
    )
    await gateway._on_new_message(event)
    assert rag.archive.status(A, "123")["message_count"] == 1
    active = False
    rag.archive.purge(A)
    await gateway._on_new_message(event)
    with pytest.raises(GatewayError, match="archive_not_configured"):
        rag.archive.status(A, "123")


def test_recent_head_catchup_survives_live_messages_and_restart(worker):
    rag, _ = worker
    archive = rag.archive
    archive.configure(A, "123", "Synthetic", enabled=True, retain_deleted=False)

    def msg(i):
        return {"id": str(i), "text": f"sample {i}"}

    archive.ingest_head(A, "123", [msg(10), msg(9)], "older")
    assert archive.head_progress(A, "123")["high_id"] == 10
    # More than one page arrived while offline; a live event must not advance the checkpoint.
    archive.record(A, "new_message", {"chat_id": "123", "message": msg(40)})
    archive.ingest_head(A, "123", [msg(40), msg(30)], "page2")
    assert archive.head_progress(A, "123")["cursor"] == "page2"
    reopened = ArchiveStore(archive.store)
    reopened.ingest_head(A, "123", [msg(20), msg(10)], "page3")
    progress = reopened.head_progress(A, "123")
    assert progress["cursor"] is None and progress["high_id"] == 40
    assert reopened.search(A, "123", "sample 20")["messages"]
    reopened.reset_sync(A, "123")
    assert reopened.head_progress(A, "123")["high_id"] == 0


def test_background_mode_requires_embeddings(tmp_path):
    with pytest.raises(ValidationError):
        Settings(state_dir=tmp_path, allowed_hosts=["localhost"], background_rag=True)


async def test_invalid_signed_checkpoint_resets_without_deleting_data(worker):
    rag, _ = worker
    archive = rag.archive
    archive.configure(A, "123", "Synthetic", enabled=True, retain_deleted=False)
    archive.ingest_page(A, "123", [{"id": "1", "text": "preserve"}], "invalid-old-key")
    gateway = UserGateway(SimpleNamespace(), "t" * 43, A, archive=archive)
    gateway.history = AsyncMock(side_effect=GatewayError("invalid_cursor", "Use a fresh cursor"))
    with pytest.raises(GatewayError, match="invalid_cursor"):
        await gateway.sync_archive_chat("123")
    assert archive.sync_config(A, "123")["cursor"] is None
    assert archive.search(A, "123", "preserve")["messages"]


def test_automatic_metadata_refresh_does_not_erase_chat_title(worker):
    rag, _ = worker
    rag.archive.discover(A, "123", "Known title", False)
    rag.archive.discover(A, "123", "", False)
    assert rag.archive.status(A, "123")["title"] == "Known title"


def test_progress_counts_only_active_nonempty_text_and_current_model(worker):
    rag, _ = worker
    archive = rag.archive
    archive.configure(A, "1", "Synthetic", enabled=True, retain_deleted=False)
    archive.ingest_page(
        A,
        "1",
        [
            {"id": "1", "text": "useful"},
            {"id": "2", "text": "\u2003\n"},
            {"id": "3", "text": ""},
        ],
        None,
    )
    with archive.connect() as db:
        mid = db.execute("SELECT rowid FROM messages WHERE mid='1'").fetchone()[0]
        db.execute("INSERT INTO message_vectors VALUES(?,?,?,?)", (mid, "old", "fp", "[1,0]"))
    rag.model_key = "current"
    status = rag.status(details=True)
    assert status["archived_messages"] == 3
    assert status["eligible_messages"] == status["pending_messages"] == 1
    assert status["indexed_messages"] == 0
    assert status["history_complete_chats"] == 1
    assert status["chats"][0]["title"] == "Synthetic"
    assert "useful" not in str(status)


def test_fractional_index_interval_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TG_MCP_RAG_INDEX_INTERVAL", "0.1")
    assert Settings.from_env(tmp_path).rag_index_interval == 0.1
    for invalid in ["0", "0.01", "nan", "inf", "301"]:
        monkeypatch.setenv("TG_MCP_RAG_INDEX_INTERVAL", invalid)
        with pytest.raises(ValidationError):
            Settings.from_env(tmp_path)


async def test_pending_scopes_exclude_complete_disabled_and_wrong_accounts(worker):
    rag, _ = worker
    for account, chat in [(A, "1"), (A, "2"), (A, "3"), (B, "4")]:
        rag.archive.configure(account, chat, "Synthetic", enabled=True, retain_deleted=False)
        rag.archive.ingest_page(account, chat, [{"id": "1", "text": "sample"}], None)
    await rag.index.index("archive", A, "1")
    rag.archive.configure(A, "3", "Paused", enabled=False, retain_deleted=False)
    assert set(rag.jobs("synthetic")) == {("archive", A, "2")}
    assert set(rag.jobs("new-model")) == {("archive", A, "1"), ("archive", A, "2")}


@pytest.mark.parametrize("worked,delay", [(True, 0.1), (False, 1)])
async def test_fast_indexing_yields_but_idle_queue_does_not_busy_poll(
    worker, monkeypatch, worked, delay
):
    rag, _ = worker
    rag.settings = rag.settings.model_copy(update={"rag_index_interval": 0.1})
    rag.index_once = AsyncMock(return_value=worked)
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr("tg_mcp.background.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await rag.index_loop()
    sleep.assert_awaited_once_with(delay)


async def test_server_metrics_sample_archive_without_dashboard_polling(worker, monkeypatch):
    rag, _ = worker
    stamp = [0]
    monkeypatch.setattr("tg_mcp.background.monotonic", lambda: stamp[0])
    rag.archive.configure(A, "1", "Synthetic", enabled=True, retain_deleted=False)
    rag.archive.ingest_page(A, "1", [{"id": str(i), "text": "sample"} for i in range(20)], None)
    for t in range(0, 31, 10):
        stamp[0] = t
        rag.archive.ingest_page(
            A, "1", [{"id": str(20 + t + i), "text": "new sample"} for i in range(2)], None
        )
        await rag.index_once()
        rag.sample_metrics()
    result = rag.metrics.snapshot(30, rag.metrics.scope, 12)
    assert result["index_per_second"] == 0.4
    assert result["incoming_per_second"] == 0.2
    assert result["queue_per_second"] == -0.2
    assert result["eta_seconds"] == 60
