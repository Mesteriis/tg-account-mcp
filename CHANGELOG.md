# Changelog

This project follows [Semantic Versioning](https://semver.org/). Until 1.0, minor releases may
contain breaking changes documented here.

## [Unreleased]

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
