# Telegram MCP Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a deployable single-owner Telegram MCP server with QR onboarding and bearer-token access for concurrent agents.

**Architecture:** A single ASGI process owns the Telethon session. A small authenticated MCP surface calls separate user-account and Bot API adapters; an offline administrative CLI provisions credentials and session state under an exclusive lock.

**Tech Stack:** Python 3.12+, MCP SDK 2.2, Telethon 1.45, HTTPX, QRCode, Uvicorn, pytest, Ruff, Docker Compose and Caddy.

**Spec:** `docs/superpowers/specs/2026-09-16-telegram-mcp-design.md` (approved by user).

## Global Constraints

- One owner, one bot, one application worker; token holders share read/send rights.
- HTTPS externally; bearer authorization on every MCP request, explicit Host/Origin allowlists.
- State directory 0700 and credentials/session files 0600; no credentials or message text in logs.
- Never change sender on errors or automatically retry uncertain sends.
- No live Telegram send without a user-selected test destination.
- Project started empty, without a Git repository. Preserve design documents; no remote publication.

## Task 1: Configuration, storage, and authorization boundary

Files: `pyproject.toml`, `.gitignore`, `src/tg_mcp/config.py`, `src/tg_mcp/storage.py`, `src/tg_mcp/auth.py`, `tests/test_security.py`.

Interfaces: `Settings` loads non-secret server settings and private `Credentials`; `StateStore.lock()` protects session access; `BearerAuth(app, token, hosts, origins)` wraps the entire ASGI application.

- [x] Write regression tests for missing/wrong/duplicate authorization, wrong Host/Origin, non-HTTP lifespan forwarding, private state permissions and exclusive lock.
- [x] Run `uv run pytest tests/test_security.py -q`; record the initial failure before implementation.
- [x] Implement constant-time token comparison and exact authority/origin matching; atomically write private files and fail on symlinks or unowned state.
- [x] Run the focused tests until passing.

Core boundary example:

```python
response = await client.post("/mcp", headers={"Authorization": "Bearer wrong"})
assert response.status_code == 401
```

## Task 2: Telegram adapters and QR onboarding

Files: `src/tg_mcp/errors.py`, `src/tg_mcp/telegram.py`, `src/tg_mcp/bot.py`, `src/tg_mcp/onboarding.py`, `tests/test_telegram.py`, `tests/test_onboarding.py`.

Interfaces: user adapter exposes status, bounded dialogs/history/search and text send; bot adapter exposes getMe and text send. `login_with_qr(client, show_qr, ask_password)` handles expiry, 2FA and cancellation without storing passwords.

- [x] Test QR refresh on timeout, 2FA after QR acceptance, existing authorization, cancellation/disconnect ownership, user-only and bot-only sending, pagination, FloodWait and unknown send results.
- [x] Run focused tests and record failure before implementation.
- [x] Implement adapters against installed dependency signatures. Resolve peers before reads/sends, use decimal string IDs, disable parse modes, cap page sizes, and expose only sanitized errors.
- [x] Run focused tests. Verify bot HTTP requests use no transport retries and do not leak token-bearing URLs in errors.

Failure contract:

```python
assert error.code == "delivery_unknown"
assert "secret" not in str(error)
```

## Task 3: MCP tools and CLI lifecycle

Files: `src/tg_mcp/server.py`, `src/tg_mcp/cli.py`, `src/tg_mcp/__init__.py`, `tests/test_mcp.py`, `tests/test_cli.py`.

Interfaces: `create_app(settings, user, bot)` builds the authenticated MCP ASGI app; production lifespan connects/disconnects adapters under the session lock. `tg-mcp` commands: setup, login, set-bot, rotate-token, serve.

- [x] Test a real SDK client over local HTTP with fake adapters: initialize, list tools, call reads, explicit sender separation, invalid inputs and concurrent clients.
- [x] Test lifecycle cleanup on failure and CLI refusal to modify state while the service owns its lock.
- [x] Run tests to establish failures; implement the six approved tools with bounded inputs and safe error envelopes.
- [x] Implement CLI using hidden secret input, QR terminal rendering, atomic credential updates and no traceback containing secrets.
- [x] Run MCP and CLI checks; verify all mutating tools carry MCP mutation annotations.

Tool check:

```python
names = {tool.name for tool in (await client.list_tools()).tools}
assert {"send_as_user", "send_as_bot", "get_chat_history"} <= names
```

## Task 4: Deployment, documentation and completion checks

Files: `Dockerfile`, `compose.yaml`, `Caddyfile`, `.dockerignore`, `.env.example`, `README.md`, `uv.lock`, `.github/workflows/ci.yml`.

- [x] Document initial setup, QR/2FA, token provisioning, restart/rotation, HTTPS/DNS requirements, backups and permission limits in Russian.
- [x] Build a non-root image with frozen dependencies and a persistent private state directory; expose only Caddy ports in Compose.
- [x] Add a CI workflow running the same lint and test commands used locally.
- [x] Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`, `uv build`, and `docker compose config --quiet` with a synthetic domain. Build image if the Docker daemon is available.
- [x] Review security boundaries and final files; report actual outcomes and any unavailable live/deployment checks.

Deployment credentials and domain may arrive asynchronously; local implementation and tests do not depend on them.
