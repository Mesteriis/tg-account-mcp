import pytest

from tg_mcp.archive import ArchiveStore
from tg_mcp.errors import GatewayError
from tg_mcp.memory import ProjectMemory
from tg_mcp.storage import StateStore

ACCOUNT = "acct_aaaaaaaaaaaaaaaa"


@pytest.fixture
def state(tmp_path):
    archive = ArchiveStore(StateStore(tmp_path))
    for chat in ["123", "456"]:
        archive.configure(ACCOUNT, chat, "Synthetic", enabled=True, retain_deleted=True)
        archive.ingest_page(
            ACCOUNT,
            chat,
            [{"id": "1", "text": "original decision", "date": "2026-10-25T10:00:00+00:00"}],
            None,
        )
    memories = ProjectMemory(archive)
    project = memories.create(ACCOUNT, "Project A", ["123"])["project_id"]
    return archive, memories, project


def proposal(memories, project):
    return memories.propose(
        ACCOUNT, project, "Use a durable queue", [{"chat_id": "123", "message_id": "1"}]
    )["memory_id"]


def test_proposal_requires_approval_and_preserves_citations(state, tmp_path):
    archive, memories, project = state
    mid = proposal(memories, project)
    assert memories.entries(ACCOUNT, project)["memories"] == []
    assert memories.entries(ACCOUNT, project, state="pending")["memories"][0]["memory_id"] == mid
    memories.approve(ACCOUNT, project, mid)
    approved = memories.entries(ACCOUNT, project)["memories"][0]
    assert approved["approved_at"]
    reopened = ProjectMemory(ArchiveStore(StateStore(tmp_path)))
    assert reopened.entries(ACCOUNT, project)["memories"][0] == approved
    assert approved["sources"] == [{"account_id": ACCOUNT, "chat_id": "123", "message_id": "1"}]
    memories.approve(ACCOUNT, project, mid)  # idempotent
    assert (
        memories.entries(ACCOUNT, project)["memories"][0]["approved_at"] == approved["approved_at"]
    )
    with archive.connect() as db:
        # Source text is not duplicated in project memory metadata.
        assert len(db.execute("SELECT fingerprint FROM memory_sources").fetchone()[0]) == 64


def test_other_projects_accounts_chats_and_missing_sources_are_rejected(state):
    _, memories, project = state
    with pytest.raises(GatewayError, match="project_not_found"):
        memories.entries("acct_bbbbbbbbbbbbbbbb", project)
    for source, code in [
        ({"chat_id": "456", "message_id": "1"}, "forbidden"),
        ({"chat_id": "123", "message_id": "99"}, "source_unavailable"),
    ]:
        with pytest.raises(GatewayError, match=code):
            memories.propose(ACCOUNT, project, "draft", [source])
    assert memories.entries(ACCOUNT, project, state="all")["memories"] == []
    other = memories.create(ACCOUNT, "B", ["456"])["project_id"]
    mid = proposal(memories, project)
    with pytest.raises(GatewayError, match="memory_not_found"):
        memories.approve(ACCOUNT, other, mid)


def test_source_edit_makes_memory_stale_and_clears_vectors(state):
    archive, memories, project = state
    mid = proposal(memories, project)
    memories.approve(ACCOUNT, project, mid)
    with archive.connect() as db:
        db.execute("INSERT INTO memory_vectors VALUES(?,?,?,?)", (mid, "model", "hash", "[1,0]"))
    archive.ingest_page(
        ACCOUNT,
        "123",
        [
            {
                "id": "1",
                "text": "new decision",
                "date": "2026-10-25T10:00:00+00:00",
                "edit_date": "2026-10-25T11:00:00+00:00",
            }
        ],
        None,
    )
    assert not memories.entries(ACCOUNT, project)["memories"]
    assert memories.entries(ACCOUNT, project, state="stale")["memories"]
    with pytest.raises(GatewayError, match="source_changed"):
        memories.approve(ACCOUNT, project, mid)
    with archive.connect() as db:
        assert db.execute("SELECT count(*) FROM memory_vectors").fetchone()[0] == 0


@pytest.mark.parametrize("retain", [True, False])
def test_source_deletion_removes_derived_memories_even_when_raw_retention_is_enabled(state, retain):
    archive, memories, project = state
    archive.configure(ACCOUNT, "123", "Synthetic", enabled=True, retain_deleted=retain)
    mid = proposal(memories, project)
    memories.approve(ACCOUNT, project, mid)
    archive.record(ACCOUNT, "deleted_messages", {"chat_id": "123", "message_ids": ["1"]})
    assert not memories.entries(ACCOUNT, project, state="all")["memories"]
    assert not memories.sources(project, mid)


def test_project_and_account_purge_remove_memory_without_cross_project_loss(state):
    archive, memories, project = state
    proposal(memories, project)
    other = memories.create(ACCOUNT, "B", ["456"])["project_id"]
    memories.propose(ACCOUNT, other, "other", [{"chat_id": "456", "message_id": "1"}])
    archive.purge(ACCOUNT, "123")
    assert not memories.entries(ACCOUNT, project, state="all")["memories"]
    assert memories.entries(ACCOUNT, other, state="all")["memories"]
    memories.delete(ACCOUNT, other)
    assert archive.status(ACCOUNT, "456")["message_count"] == 1
    archive.purge(ACCOUNT)
    assert not memories.projects(ACCOUNT)
    with archive.connect() as db:
        for table in [
            "project_memories",
            "memory_sources",
            "project_chats",
            "message_vectors",
            "memory_vectors",
        ]:
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_upgrade_version_one_preserves_existing_archive(state, tmp_path):
    archive, _, _ = state
    with archive.connect() as db:
        for trigger in [
            "archive_delete_derived",
            "archive_edit_derived",
            "archive_tombstone_derived",
        ]:
            db.execute(f"DROP TRIGGER {trigger}")
        for table in [
            "message_vectors",
            "memory_vectors",
            "memory_sources",
            "project_memories",
            "project_chats",
            "projects",
        ]:
            db.execute(f"DROP TABLE {table}")
        db.execute("PRAGMA user_version=1")
    upgraded = ArchiveStore(StateStore(tmp_path))
    assert upgraded.search(ACCOUNT, "123", "original")["messages"]
    with upgraded.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
