# Project memory and local semantic retrieval

The archive preserves observed Telegram sources. Project memory holds explicitly approved
interpretations of those sources. A draft is not a verified fact, and similarity is not a truth
score. Neither layer automatically generates answers, extracts decisions, or approves content.

## Project workflow

1. Configure the selected chat archives and import the relevant source messages.
2. `create_memory_project(account_id, title, chat_ids)` creates an isolated project. Projects
   belong to one account and select 1–100 existing archives; an account supports up to 100 projects.
3. `propose_project_memory(account_id, project_id, text, sources)` saves a pending draft. Supply
   1–20 `{chat_id, message_id}` references to active archived messages in that project. Text is
   limited to 4,096 characters. Source fingerprints bind the proposal to the reviewed snapshots.
4. Present the draft and its citations to the user. Call `approve_project_memory` only after
   the user explicitly approves that exact draft. The approval tool requires admin privileges
   and verifies that every source is still unchanged and not deleted.
5. Read with `list_project_memory` or `search_project_memory`. Ordinary reads return only
   approved entries. Listing pending/stale entries requires admin. Keyword search is available
   without an embedding provider and performs Unicode case-insensitive literal matching.
6. `delete_project_memory` removes one entry and its vectors. `delete_memory_project` removes
   a project and all its derived memory, while keeping its chat archives. Both require admin.

Edits to any cited source make the associated memory **stale**, remove its approval and discard
its vectors. Replayed older history cannot undo this transition. Propose a replacement from
current sources rather than reapproving the stale draft. Deleting a source removes its derived
memories and vectors even if retention preserves the raw deleted message. Purging a chat removes
memory derived from it; the project keeps its original source-chat scope so a purge cannot
widen token access. Recreate the project to deliberately change that scope. Deleting an account
also removes its projects. This avoids retaining
untraceable summaries after their sources disappear. Only observed edits/deletions can trigger
these actions; Telegram coverage limitations still apply.

Every project operation checks the account and **all** selected source chats. A token allowed to
read one chat cannot retrieve a project that also includes an unauthorized chat. Such projects
are omitted from `list_memory_projects`. Disabled accounts cannot read project memory. Creating,
proposing, approving, indexing and deleting require admin; proposed drafts are never automatically
promoted. An approved entry remains untrusted input to an agent and does not authorize actions.

## Configure local embeddings

Semantic retrieval is disabled by default. Configure both environment variables on the **server**:

```sh
TG_MCP_EMBEDDING_URL=http://127.0.0.1:11434
TG_MCP_EMBEDDING_MODEL=qwen3-embedding:4b
TG_MCP_EMBEDDING_DIMENSIONS=256
```

The URL accepts loopback or a private numeric RFC1918/ULA address. Arbitrary hostnames, public
addresses, URL credentials, paths, queries, redirects and environment HTTP proxies are not used.
The operator must trust the configured local inference server: indexing sends selected content
to it, and searching sends the query. No cloud fallback or model pull is performed. The model
must already appear in Ollama's local GGUF catalog. This does not replace network policy on the
inference server itself.

`get_capabilities.features.semantic_search` means a provider is configured, not that it is
currently healthy. A local request has a 30-second timeout within the MCP operation's overall
45-second limit. A cold model can exceed that limit; warm it on the inference host or reduce
indexing batches. The service returns a safe `embedding_timeout`/`embedding_unavailable` error,
without upstream bodies or silent fallback to keyword search. Inputs exceeding the model's
context window fail rather than being silently truncated.

Use `index_archive_semantics(account_id, chat_id, limit)` for one explicit batch of active
messages, or `index_project_memory(account_id, project_id, limit)` for approved memories. A batch
contains at most 16 entries. Repeat while `has_more` is true. These tools authorize local content
processing and require admin. Background embedding is off by default; [all-account background mode](background-rag.md)
can be explicitly enabled by the operator.

Use `semantic_search_archive` for one chat, or `search_project_memory(..., mode="semantic")` for
one project. Both return cosine-ranked results with source IDs. Deleted messages, pending drafts
and stale memory are excluded. `semantic_search_archive` does not replace Telegram live search.

The provider uses [Ollama embeddings](https://docs.ollama.com/api/embed) and the
[local model catalog](https://docs.ollama.com/api/tags).

The index binds normalized vectors to the endpoint, model name, local weight digest, dimensions
and embedding-format version. A changed digest does not mix old and new vectors: reindex the
selected sources. Changes during an inference request or before committing vectors are rejected
or skipped. A concurrent edit or purge cannot recreate stale vectors. Query text is not stored.

Retrieval scans at most 2,000 indexed entries in the requested scope, ordered newest first.
`partial`, `eligible_count` and `indexed_scanned` disclose incomplete indexing or that scan limit.
Keyword memory search scans at most 2,000 approved entries and reports its own `partial` flag.
Results from a partial scan are not an exhaustive account of project knowledge. This initial
implementation uses exact cosine calculations over the bounded subset, not an approximate vector
service, hybrid rank fusion or a reranker. Vectors are sensitive private state and share archive
retention/cleanup rules; logical deletion does not erase external backups or filesystem snapshots.

## Schema and verification

Opening an existing schema-1 archive adds the project tables, vectors and invalidation triggers,
then sets SQLite `user_version=2`. Existing message snapshots, FTS entries and cursors remain.
Before deploying, stop the service and back up the complete private state. Rolling back to
schema-1 software requires restoring its matching archive backup as well as the old package;
there is no automatic downgrade migration. [Background mode](background-rag.md) adds schema 3. A consistent code/dependency backup is also needed.

The normal test suite uses deterministic vectors and fake HTTP providers for permission, approval,
migration, ranking, digest changes, stale writes and deletion checks. It does not establish model
retrieval quality. For a separate real-model smoke test using **only synthetic data**:

```sh
uv run python scripts/evaluate_semantic.py \
  --url http://127.0.0.1:11434 --model qwen3-embedding:4b
```

The smoke contains five Russian snippets and three paraphrased questions. In the initial run,
the warmed local Qwen3 4B model at 256 dimensions returned the expected source first for 3/3
questions; the available mxbai model returned 0/3. The Qwen cold-start attempt timed out. These
small observations do not establish general accuracy, a model ranking or a production latency
budget. Evaluate on a larger authorized question/source set before relying on semantic retrieval.
