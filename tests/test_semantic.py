import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from tg_mcp.archive import ArchiveStore
from tg_mcp.config import Settings
from tg_mcp.errors import GatewayError
from tg_mcp.memory import ProjectMemory
from tg_mcp.semantic import OllamaEmbeddings, SemanticIndex, normalized
from tg_mcp.storage import StateStore

A = "acct_aaaaaaaaaaaaaaaa"


class FakeEmbeddings:
    enabled = True
    key = "synthetic-model"
    hook = None

    async def model_key(self):
        return self.key

    async def embed(self, texts, model_key):
        if self.hook:
            self.hook()
        # Deterministic fixtures test ranking and isolation, not language-model quality.
        return [
            normalized([1, 0] if "queue" in text or "durable" in text else [0, 1]) for text in texts
        ]


@pytest.fixture
def index(tmp_path):
    archive = ArchiveStore(StateStore(tmp_path))
    for account, chat in [(A, "123"), (A, "456"), ("acct_bbbbbbbbbbbbbbbb", "123")]:
        archive.configure(account, chat, "Synthetic", enabled=True, retain_deleted=True)
        archive.ingest_page(
            account,
            chat,
            [{"id": "1", "text": "durable queue"}, {"id": "2", "text": "garden flowers"}],
            None,
        )
    provider = FakeEmbeddings()
    return archive, provider, SemanticIndex(archive, provider)


async def test_ranking_incremental_index_and_scope(index):
    archive, provider, semantic = index
    first = await semantic.index("archive", A, "123", limit=1)
    assert first["indexed"] == 1 and first["has_more"]
    second = await semantic.index("archive", A, "123", limit=1)
    assert second["indexed"] == 1 and not second["has_more"]
    assert (await semantic.index("archive", A, "123"))["indexed"] == 0
    result = await semantic.search("archive", A, "123", "durable queue")
    assert result["results"][0]["id"] == "1" and result["results"][0]["score"] == 1
    assert not result["partial"] and result["eligible_count"] == 2
    assert all(r["chat_id"] == "123" and r["account_id"] == A for r in result["results"])
    assert not (await semantic.search("archive", A, "456", "queue"))["results"]
    provider.key = "changed-digest"
    assert (await semantic.search("archive", A, "123", "queue"))["partial"]
    assert (await semantic.index("archive", A, "123"))["indexed"] == 2
    archive.purge(A, "123")
    with archive.connect() as db:
        assert db.execute("SELECT count(*) FROM message_vectors").fetchone()[0] == 0


async def test_edit_during_embedding_never_commits_stale_vectors(index):
    archive, provider, semantic = index
    provider.hook = lambda: archive.ingest_page(
        A,
        "123",
        [{"id": "1", "text": "updated garden", "edit_date": "2026-10-25T12:00:00+00:00"}],
        None,
    )
    result = await semantic.index("archive", A, "123")
    assert result["skipped_changed"] == 1 and result["has_more"]
    provider.hook = None
    await semantic.index("archive", A, "123")
    archive.record(A, "deleted_messages", {"chat_id": "123", "message_ids": ["1"]})
    assert all(
        r["id"] != "1" for r in (await semantic.search("archive", A, "123", "queue"))["results"]
    )


async def test_only_approved_project_memory_is_indexed(index):
    archive, _, semantic = index
    memories = ProjectMemory(archive)
    project = memories.create(A, "Synthetic", ["123"])["project_id"]
    draft = memories.propose(A, project, "durable queue", [{"chat_id": "123", "message_id": "1"}])[
        "memory_id"
    ]
    assert (await semantic.index("memory", A, project))["indexed"] == 0
    memories.approve(A, project, draft)
    assert (await semantic.index("memory", A, project))["indexed"] == 1
    assert (await semantic.search("memory", A, project, "queue"))["results"][0][
        "memory_id"
    ] == draft
    memories.delete(A, project, draft)
    assert not (await semantic.search("memory", A, project, "queue"))["results"]


@pytest.mark.parametrize(
    "vector", [[0, 0], [float("nan"), 1], [float("inf")], [], [True, 1], ["1"], None]
)
def test_invalid_provider_vectors_are_rejected(vector):
    with pytest.raises(GatewayError, match="invalid_embedding"):
        normalized(vector)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://8.8.8.8",
        "http://0.0.0.0",
        "http://user:password@localhost",
        "http://localhost/api/embed",
        "http://169.254.169.254",
    ],
)
def test_embedding_configuration_rejects_public_or_ambiguous_destinations(tmp_path, url):
    with pytest.raises(ValidationError):
        Settings(
            state_dir=tmp_path,
            allowed_hosts=["localhost"],
            embedding_url=url,
            embedding_model="synthetic:local",
        )


def local_provider(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        "tg_mcp.semantic.httpx.AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return OllamaEmbeddings(
        SimpleNamespace(
            embedding_url="http://127.0.0.1:11434",
            embedding_model="synthetic:local",
            embedding_dimensions=32,
        )
    )


def tags(digest="a" * 64):
    return {
        "models": [
            {
                "name": "synthetic:local",
                "digest": digest,
                "size": 100,
                "details": {"format": "gguf"},
            }
        ]
    }


async def test_provider_validates_model_digest_and_explicit_no_truncation(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags())
        body = json.loads(request.content)
        assert body["truncate"] is False and body["dimensions"] == 32
        return httpx.Response(200, json={"embeddings": [[1] + [0] * 31 for _ in body["input"]]})

    provider = local_provider(monkeypatch, handler)
    key = await provider.model_key()
    result = await provider.embed(["synthetic only"], key)
    assert len(result[0]) == 32 and result[0][0] == 1
    assert calls == ["/api/tags", "/api/tags", "/api/embed", "/api/tags"]


async def test_model_change_during_embedding_and_redirect_are_rejected(monkeypatch):
    digest = "a" * 64

    def handler(request):
        nonlocal digest
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags(digest))
        digest = "b" * 64
        return httpx.Response(200, json={"embeddings": [[1] + [0] * 31]})

    provider = local_provider(monkeypatch, handler)
    with pytest.raises(GatewayError, match="embedding_model_changed"):
        await provider.embed(["synthetic"], await provider.model_key())


async def test_provider_does_not_follow_redirects_or_leak_upstream_errors(monkeypatch):
    provider = local_provider(
        monkeypatch,
        lambda request: httpx.Response(
            302, headers={"Location": "https://example.com/private"}, text="sensitive detail"
        ),
    )
    with pytest.raises(GatewayError) as error:
        await provider.model_key()
    assert "sensitive" not in str(error.value)


async def test_disabled_provider_fails_without_network(tmp_path):
    provider = OllamaEmbeddings(Settings(state_dir=tmp_path, allowed_hosts=["localhost"]))
    with pytest.raises(GatewayError, match="semantic_disabled"):
        await provider.model_key()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://10.1.2.3:11434",
        "https://[::1]:11434",
        "http://[fd00::1]:11434",
    ],
)
def test_private_provider_configuration_is_accepted(tmp_path, url):
    settings = Settings(
        state_dir=tmp_path,
        allowed_hosts=["localhost"],
        embedding_url=url,
        embedding_model="synthetic:local",
    )
    assert OllamaEmbeddings(settings).enabled


@pytest.mark.parametrize(
    "url",
    [
        "http://203.0.113.1",
        "http://100.64.0.1",
        "http://localhost:0",
        "http://localhost:99999",
        "http://localhost:invalid",
    ],
)
def test_reserved_destinations_and_invalid_ports_are_rejected(tmp_path, url):
    with pytest.raises(ValidationError):
        Settings(
            state_dir=tmp_path,
            allowed_hosts=["localhost"],
            embedding_url=url,
            embedding_model="synthetic:local",
        )


def test_partial_embedding_configuration_is_rejected(tmp_path):
    for values in [
        {"embedding_url": "http://localhost:11434"},
        {"embedding_model": "synthetic:local"},
    ]:
        with pytest.raises(ValidationError):
            Settings(state_dir=tmp_path, allowed_hosts=["localhost"], **values)


async def test_scan_limit_is_reported_as_partial(index, monkeypatch):
    _, _, semantic = index
    await semantic.index("archive", A, "123")
    monkeypatch.setattr("tg_mcp.semantic.MAX_SCAN", 1)
    result = await semantic.search("archive", A, "123", "queue")
    assert result["partial"] and result["eligible_count"] == 2 and result["indexed_scanned"] == 1


async def test_purge_during_embedding_cannot_recreate_vectors(index):
    archive, provider, semantic = index
    provider.hook = lambda: archive.purge(A, "123")
    result = await semantic.index("archive", A, "123")
    assert result["indexed"] == 0 and result["skipped_changed"] == 2
    with archive.connect() as db:
        assert db.execute("SELECT count(*) FROM message_vectors").fetchone()[0] == 0


async def test_timeout_error_is_safe_and_actionable(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("sensitive upstream detail")

    provider = local_provider(monkeypatch, handler)
    with pytest.raises(GatewayError) as error:
        await provider.model_key()
    assert error.value.code == "embedding_timeout"
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("details", [None, [], "gguf"])
async def test_malformed_model_catalog_fails_closed(monkeypatch, details):
    data = tags()
    data["models"][0]["details"] = details
    provider = local_provider(monkeypatch, lambda request: httpx.Response(200, json=data))
    with pytest.raises(GatewayError, match="invalid_embedding"):
        await provider.model_key()


async def test_blank_messages_do_not_block_indexing(index):
    archive, _, semantic = index
    archive.ingest_page(A, "123", [{"id": "3", "text": " \n\t\u00a0\u3000"}], None)
    result = await semantic.index("archive", A, "123")
    assert result["indexed"] == 2 and not result["has_more"]
    found = await semantic.search("archive", A, "123", "queue")
    assert not found["partial"] and found["eligible_count"] == 2


async def test_bounded_retrieval_prefers_newest_messages_not_backfill_insert_order(
    index, monkeypatch
):
    archive, _, semantic = index
    archive.ingest_page(
        A, "123", [{"id": "99", "text": "queue newest"}, {"id": "3", "text": "queue oldest"}], None
    )
    await semantic.index("archive", A, "123")
    monkeypatch.setattr("tg_mcp.semantic.MAX_SCAN", 1)
    found = await semantic.search("archive", A, "123", "queue")
    assert found["results"][0]["id"] == "99"


async def test_project_vector_filter_also_binds_account(index):
    archive, _, semantic = index
    memories = ProjectMemory(archive)
    project = memories.create(A, "Synthetic", ["123"])["project_id"]
    memory = memories.propose(A, project, "durable queue", [{"chat_id": "123", "message_id": "1"}])[
        "memory_id"
    ]
    memories.approve(A, project, memory)
    await semantic.index("memory", A, project)
    wrong = await semantic.search("memory", "acct_bbbbbbbbbbbbbbbb", project, "queue")
    assert not wrong["results"] and wrong["eligible_count"] == 0


async def test_long_post_is_embedded_in_full_and_larger_input_fails_explicitly(monkeypatch):
    inputs = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags())
        body = json.loads(request.content)
        assert body["truncate"] is False
        inputs.extend(body["input"])
        return httpx.Response(200, json={"embeddings": [[1] + [0] * 31]})

    provider = local_provider(monkeypatch, handler)
    key = await provider.model_key()
    text = "long post " * 819 + "!!"
    assert len(text) == 8192
    assert len(await provider.embed([text], key)) == 1
    assert inputs == [text]
    with pytest.raises(GatewayError, match="invalid_request"):
        await provider.embed([text + "!"], key)
    assert inputs == [text]
