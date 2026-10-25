# Background RAG for all connected user accounts

Background mode is an explicit operator opt-in. It captures and indexes the text of every
accessible personal chat, group and channel for every currently ready user account and accounts
connected later. This is broader than selecting individual archives. Bot identities do not have
user-account history and are not substituted for user accounts. Attachments are recorded as
metadata; OCR, file parsing and voice transcription are not included.

Configure a local embedding provider and enable the worker on the server:

```sh
TG_MCP_EMBEDDING_URL=http://127.0.0.1:11434
TG_MCP_EMBEDDING_MODEL=qwen3-embedding:4b
TG_MCP_EMBEDDING_DIMENSIONS=256
TG_MCP_BACKGROUND_RAG=true
TG_MCP_RAG_DISCOVERY_INTERVAL=300
TG_MCP_RAG_INDEX_INTERVAL=1
TG_MCP_RAG_BATCH_SIZE=4
```

New personal/group/channel messages and edits register their chat immediately while the account
is ready. A separate discovery pass enumerates all accessible dialogs, without the interactive
tool's 10,000-position limit. It runs on startup and every 300 seconds by default. Newly connected
accounts are picked up by subsequent passes. Disabled or incomplete accounts are not processed.
Known enabled sessions that failed startup are retried; revoked sessions and incomplete logins
still require owner action. Discovered chats default to deleted-text retention **off**; existing retention settings survive.

The history worker refreshes each selected chat's recent head independently from its older-history
cursor. If more than one head page arrived during a disconnect, its persistent checkpoint keeps
paging to the previous watermark while old-history import proceeds. Live arrivals do not advance
that checkpoint and hide intervening messages. Importing older pages and storing the corresponding
progress are transactional. Historical scans repeat after reaching the end to reconcile surviving
older edits. Invalid signed cursors after token rotation are reset for the next retry.

A second worker finds missing/stale vectors in SQLite, processes bounded batches fairly across
account/chat/project scopes, and indexes only **approved** project memory. It never invents or
approves project facts. New messages, observed edits and deletions use the same invalidation
triggers as manual indexing. The queue is derived from persistent data, so restarts do not lose
pending work or re-embed unchanged records. A failed batch remains pending. Model errors use
bounded exponential retry delays (up to five minutes); discovery respects Telegram flood waits
per account. A blocked account does not stop discovery for other accounts.

Ollama requests keep the model resident for ten minutes. When the queue is idle, a synthetic
readiness probe every five minutes refreshes the model cache. This does not reserve exclusive
GPU capacity: the inference host may evict the model or become unavailable. Cold starts and
resource contention can still produce explicit errors; no cloud/keyword fallback is implicit.

## Progress and operator controls

`get_background_rag_status` requires admin and reports worker liveness, ready accounts, selected
chats, archived/indexed message counts, pending scopes, last activity and separate discovery/index
errors. The counters represent observed data, not proof that all Telegram history has been loaded.
Initial import/indexing can take substantial time for many dialogs. New message capture, history
fetching and embedding progress are separate; a large backlog does not mean a stopped worker.
The semantic search scan limit and `partial` reporting still apply.

Explicit chat controls remain effective. Disabling a chat archive saves a persistent exclusion;
automatic discovery and events cannot re-enable it. Purging a chat also excludes it, preventing
its data from reappearing during the next scan. This preserves an account/chat ID as operator
policy metadata, not message content. `configure_chat_archive(..., enabled=true)` removes that
exclusion. Deleting the account removes its exclusions. Pause/purge are deliberate exceptions to
all-dialog mode. Disabling the account also prevents its background discovery and indexing.

Set `TG_MCP_BACKGROUND_RAG=false` and restart to stop automatic discovery/embedding. Previously
selected archive capture remains enabled until explicitly paused; this switch is not a data purge.
Use archive/project purge tools to remove stored content as required. Existing token restrictions
still apply to every read, and the global progress tool is admin-only.

Telegram does not guarantee every deletion event; messages deleted before capture cannot be
recovered. Offline old-message edits/deletions may remain unknown until a later scan/event, and
absence from a page does not prove deletion. Coverage remains `observed_only`.

## Deployment and rollback

Archive schema 3 adds persistent head checkpoints and exclusions to schemas 1/2 without dropping
message or project content. Stop the service and take a consistent private state/code/config backup
before upgrading. A rollback needs the matching old database and package, not just the old code.
The usual test suite covers future accounts, fairness, reconnect checkpoints, exclusions, edits,
rate limits, cancellation and failed inference retries using synthetic data and fake providers.
