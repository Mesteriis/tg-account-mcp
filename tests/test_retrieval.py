from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tg_mcp.archive import ArchiveStore
from tg_mcp.errors import GatewayError
from tg_mcp.retrieval import MessageRetrieval
from tg_mcp.storage import StateStore

A = "acct_aaaaaaaaaaaaaaaa"
B = "acct_bbbbbbbbbbbbbbbb"


@pytest.fixture
def retrieval(tmp_path):
    archive = ArchiveStore(StateStore(tmp_path))
    for account, chat in [(A, "1"), (A, "2"), (B, "1")]:
        archive.configure(account, chat, "Synthetic", enabled=True, retain_deleted=False)
        archive.ingest_page(
            account,
            chat,
            [{"id": "1", "text": "queue plan", "date": "2026-10-26T10:00:00+00:00"}],
            None,
        )
    semantic = SimpleNamespace(
        search=AsyncMock(
            return_value={
                "results": [
                    {"id": "1", "chat_id": "1", "account_id": A, "text": "queue plan", "score": 0.8}
                ],
                "partial": False,
                "indexed_scanned": 1,
                "eligible_count": 1,
            }
        )
    )
    gateway = SimpleNamespace(
        history=AsyncMock(return_value={"messages": [], "next_cursor": None}),
        search_all=AsyncMock(return_value={"messages": [], "next_cursor": None}),
        message_context=AsyncMock(return_value={"messages": [{"id": "1", "text": "queue plan"}]}),
    )
    manager = SimpleNamespace(user_gateway=AsyncMock(return_value=gateway))
    return MessageRetrieval(manager, archive, semantic), gateway


async def test_complete_local_results_avoid_telegram_and_merge_duplicate_sources(retrieval):
    search, gateway = retrieval
    result = await search.search(A, "queue", chat="1", limit=1)
    assert result["stages"] == ["local_keyword", "local_semantic"]
    assert result["results"][0]["matched_by"] == ["keyword", "semantic"]
    assert result["results"][0]["semantic_score"] == 0.8
    assert not result["telegram"]["attempted"]
    gateway.history.assert_not_awaited()


async def test_partial_semantics_falls_back_but_live_snapshot_wins(retrieval):
    search, gateway = retrieval
    search.semantic.search.return_value["partial"] = True
    gateway.history.return_value = {
        "messages": [{"id": "1", "text": "queue changed"}],
        "next_cursor": "native",
    }
    result = await search.search(A, "queue", chat="1", limit=1)
    row = result["results"][0]
    assert row["text"] == "queue changed" and row["source"] == "telegram"
    assert row["local_snapshot_stale"] and "semantic_score" not in row
    assert result["partial"] and result["telegram"]["next_cursor"] == "native"


async def test_never_mode_makes_no_telegram_reads_even_for_context(retrieval):
    search, _ = retrieval
    search.semantic.search.side_effect = GatewayError("semantic_disabled", "Safe")
    result = await search.search(A, "queue", telegram="never", include_context=True)
    assert len(result["results"]) == 2
    assert {r["account_id"] for r in result["results"]} == {A}
    search.manager.user_gateway.assert_not_awaited()
    assert result["warnings"][0]["code"] == "semantic_disabled"


async def test_unknown_archive_and_rate_limit_are_explicit(retrieval):
    search, gateway = retrieval
    search.semantic.search.return_value = {"results": [], "partial": False, "indexed_scanned": 0}
    gateway.history.side_effect = GatewayError("rate_limited", "Wait", 120)
    result = await search.search(A, "queue", chat="999")
    assert result["partial"] and result["results"] == []
    assert result["warnings"] == [
        {"source": "telegram", "code": "rate_limited", "retry_after_seconds": 120}
    ]


async def test_dates_propagate_to_every_stage_and_invalid_dates_do_not_read(retrieval):
    search, gateway = retrieval
    result = await search.search(A, "queue", chat="1", telegram="always", date_from="2026-10-27")
    assert not any("keyword" in r["matched_by"] for r in result["results"])
    assert gateway.history.call_args.kwargs["date_from"] == "2026-10-27"
    assert search.semantic.search.call_args.kwargs["date_from"] == "2026-10-27"
    gateway.history.reset_mock()
    with pytest.raises(GatewayError):
        await search.search(A, "queue", date_from="2026-02-30")
    gateway.history.assert_not_awaited()


async def test_global_fallback_and_context_are_bounded(retrieval):
    search, gateway = retrieval
    gateway.search_all.return_value = {"messages": [{"id": "2", "chat_id": "2", "text": "queue"}]}
    result = await search.search(A, "queue", limit=100, include_context=True)
    assert gateway.search_all.call_args.kwargs["limit"] == 99
    assert result["telegram"]["succeeded"]
    gateway.message_context.assert_awaited_once()
    assert gateway.message_context.call_args.kwargs == {"before": 2, "after": 2}


async def test_source_scope_mismatch_never_leaks_to_results(retrieval):
    search, _ = retrieval
    search.semantic.search.return_value["results"] = [
        {"id": "5", "chat_id": "2", "account_id": B, "text": "private", "score": 1}
    ]
    result = await search.search(A, "queue", chat="1", telegram="never")
    assert "private" not in str(result)
    assert any(w["code"] == "invalid_source_scope" for w in result["warnings"])
