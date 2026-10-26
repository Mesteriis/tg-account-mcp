# Changelog

This project follows [Semantic Versioning](https://semver.org/). Until 1.0, minor releases may
contain breaking changes documented here.

## [Unreleased]

## [0.8.0] - 2026-10-26

### Added

- Continuous S3 attachment archival with resumable downloads, durable upload intents,
  integrity checks and shared adaptive Telegram pacing. Private chats capture all supported
  types; groups/channels have independent text/file defaults and per-chat overrides (schema 5).
- RAG monitoring workspace with account/type/state facets, search, sorting, pagination and
  inline rule editing; move default rules into Settings and preserve drafts during polling.
- Per-chat unique uploaded object counts, pending/error jobs and retry diagnostics.
- Fictional-data dashboard and settings screenshots in English and Russian documentation.
- Codex plugin 0.4.0 pins its discovery bridge to tg-account-mcp 0.8.0.

- Opt-in background RAG for all current/future ready user accounts, including groups/channels.
  Add immediate event discovery, fair automatic indexing, persistent reconnect head checkpoints,
  pause/purge exclusions, model readiness/retries and an admin-only progress tool (schema 3).

- Project memory with selected source chats, draft/approval states and message citations.
  Source edits make approved memory stale; deletion removes derived memory and vectors.
- Opt-in local Ollama embeddings with digest-bound indexes, bounded cosine retrieval and explicit
  partial coverage. Public destinations, redirects and implicit cloud fallback are rejected.
- Schema-1 to schema-2 archive migration and a synthetic real-model retrieval smoke script.

- Opt-in SQLite chat archives with live message/edit/deletion capture, resumable background
  history scans, literal full-text search, version retrieval, bounded JSON export and purge.
  Archive tools enforce account/chat token scopes; configuration and cleanup require admin.
  Deleted text is retained only when explicitly enabled. Account deletion purges its archive.

### Changed

- Queue archive discovery fairly and keep attachment transfers independent of slow history scans.
- Add filtered/sorted pagination over the activity panel's most recent 100 retained operations.
- This release also includes the trusted-LAN opt-in described under 0.7.1 below; that version
  was not published to GitHub Releases or PyPI.

### Improved

- Add scoped local-first message retrieval with keyword/semantic fusion, bounded Telegram
  fallback, freshness/local-only modes, UTC date filters and explicit coverage/provenance.
- Show server-sampled indexing/inflow rates, queue history and a net-drain ETA on the RAG page,
  with explicit warmup, paused, growing, stale and unavailable-account states.
- Speed up local RAG queue selection, allow fractional indexing pauses, and embed posts up to
  8192 characters without truncation; keep Telegram adaptive pacing independent.
- Retry each account independently of other accounts’ long-running history passes.
- Add a RAG dashboard page with history coverage, current-model text queue, errors and account pacing.
- Adapt background Telegram reads per account after FloodWait, persist cooldowns across restarts,
  and gradually recover after two hours of active successful loading (archive schema 4).

## [0.7.1] - 2026-10-18

### Added

- Optionally allow unauthenticated MCP requests from explicitly configured private LAN CIDRs.
  The opt-in bypass applies only to `/mcp` and uses the direct TCP peer address; all access is
  master-level, while requests with invalid credentials and clients outside those networks remain
  rejected.

## [0.7.0] - 2026-09-23

### Added

- Add confirmed account deletion to the dashboard and setup API. Deletion disconnects the account,
  removes it from the identity catalog, and deletes its local Telethon session files.

## [0.6.1] - 2026-09-23

### Fixed

- Version dashboard stylesheet and script URLs and serve static assets with `no-store`, preventing
  stale JavaScript from running against updated HTML after a deployment.

## [0.6.0] - 2026-09-23

### Changed

- Make the dashboard and setup API available without a Bearer token while keeping `/mcp`
  authenticated and preserving exact Host and browser Origin checks.
- Accept same-origin dashboard mutations automatically; `TG_MCP_ALLOWED_ORIGINS` remains available
  for a frontend hosted on a separate origin.

### Fixed

- Render the dashboard version from the running package instead of a stale hard-coded value.

### Documentation

- Document PyPI installation, the token-free trusted-network dashboard, and the current GitHub,
  PyPI, GHCR, MCP Registry, and verification status.

## [0.5.2] - 2026-09-18

### Fixed

- Match the case-sensitive MCP Registry namespace to the verified GitHub owner name.

## [0.5.1] - 2026-09-17

### Fixed

- Let the Codex bridge use the protected local server token automatically when it runs on the same
  machine.

## [0.5.0] - 2026-09-17

### Added

- Installable Codex plugin with a local MCP connection, repository marketplace metadata, and
  agent workflows for multi-account chat discovery, folder review, attachments, drafts, and
  idempotent sending.
- Authenticated local-network service discovery and a stdio bridge for clients whose MCP endpoint
  cannot be configured dynamically.

## [0.4.0] - 2026-09-16

### Added

- Multi-account QR onboarding with Telegram 2FA and local account labels.
- Optional, independently managed Telegram bots.
- Forty-four MCP tools for chat discovery, history, folders, inbox context, attachments, topics,
  mentions, updates, sending, scheduling, forwarding, reactions, drafts, and agent-token control.
- Folder-wide date queries with IANA timezone handling.
- Cyrillic/Latin transliteration matching for chat discovery.
- Chunked attachment downloads for files accepted by Telegram.
- Scoped agent tokens with identity and chat restrictions.
- Dashboard analytics that omit message and query content.
- Docker Compose deployment with Caddy HTTPS termination.

### Security

- Strict private-file ownership and permission checks.
- Exact Host and Origin allowlists, bundled web assets, CSP, and sanitized logs/errors.
- Idempotency receipts for message sending and one-time draft delivery.
