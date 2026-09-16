# Multi-account Web Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start the MCP server without a Telegram session, authorize multiple user accounts through a protected web QR/2FA flow, and manage multiple optional bots.

**Architecture:** A persistent identity catalog owns stable account/bot IDs and separate Telethon session files. A runtime manager connects identities independently and supplies explicitly selected gateways to MCP tools. A static same-origin setup page calls bearer-protected JSON endpoints; loopback-only service may use those endpoints without a token.

**Tech Stack:** Python 3.12, MCP SDK 2.2, Starlette, Telethon 1.45, HTTPX, QRCode SVG, Pydantic, pytest, Uvicorn.

**Spec:** `docs/superpowers/specs/2026-09-16-multi-account-web-onboarding-design.md`

## Global Constraints

- `/mcp` remains the protocol endpoint; `/` is the setup UI.
- Every remote setup API and MCP request requires the shared Bearer token; only a server bound to loopback may bypass setup API authentication from a loopback client.
- Each account uses one private session file and every tool requires an explicit stable identity ID.
- Bot configuration is optional and independent of user-account readiness.
- Secrets, QR URLs, message contents and upstream exception details never enter logs or error payloads.
- The existing single-account state migrates atomically. This workspace has no Git repository, so task checkpoints cannot be committed.

---

### Task 1: Persistent identity catalog and migration ✅

**Files:**
- Create: `src/tg_mcp/identities.py`
- Modify: `src/tg_mcp/storage.py`
- Modify: `src/tg_mcp/config.py`
- Test: `tests/test_identities.py`

**Interfaces:**
- Produces `IdentityCatalog`, `AccountRecord`, `BotRecord`, `IdentityDocument`.
- Produces `StateStore.load_identities()`, `save_identities()`, `account_session_path(account_id)` and `migrate_legacy(credentials)`.

- [x] Write failing tests that create legacy `credentials.json`/`account.session`, migrate exactly once, retain an interrupted source, enforce `acct_`/`bot_` IDs and preserve 0700/0600 permissions.
- [x] Run `uv run pytest tests/test_identities.py -q` and confirm import/interface failures.
- [x] Implement Pydantic records with strict labels, enabled flags, Telegram metadata and redacted bot tokens. Use atomic JSON writes and safe copy-before-publish migration for a validated regular legacy session.
- [x] Run the focused suite and confirm migration retry, duplicate label and unsafe-file cases pass.
- [x] Mark Task 1 complete in this plan; no commit is possible because the workspace is not a Git repository.

Record contract:

```python
account = catalog.add_account("Personal")
assert account.account_id.startswith("acct_")
assert store.account_session_path(account.account_id).parent.name == "accounts"
```

### Task 2: Runtime manager and concurrent QR/2FA flows ✅

**Files:**
- Create: `src/tg_mcp/manager.py`
- Modify: `src/tg_mcp/telegram.py`
- Modify: `src/tg_mcp/bot.py`
- Modify: `src/tg_mcp/onboarding.py`
- Test: `tests/test_manager.py`
- Modify: `tests/test_telegram.py`
- Modify: `tests/test_onboarding.py`

**Interfaces:**
- Produces `IdentityManager.start()`, `close()`, `list_accounts()`, `list_bots()`, `add_account(label)`, `login_state(account_id)`, `submit_password(account_id, password)`, `user_gateway(account_id)`, `add_bot(label, token)` and `bot_gateway(bot_id)`.
- `UserGateway(client, cursor_secret, identity_id)` binds cursors to one account.

- [x] Write failing async tests for start with zero sessions, two simultaneous QR flows, QR expiry, 2FA, duplicate Telegram ID, independent connection failure, hot add/disable/enable and multiple bot selection.
- [x] Run focused tests and confirm failures precede implementation.
- [x] Implement per-identity clients and locks. Start QR listeners before publishing SVG data, refresh expired QR, cap 2FA failures at three, finalize metadata only after `get_me`, and reject a duplicate Telegram user ID.
- [x] Implement bot verification before catalog save and exact gateway lookup errors (`identity_not_found`, `identity_disabled`, `not_authorized`, `unavailable`).
- [x] Run focused tests and mark Task 2 complete; no Git commit is available.

Selection contract:

```python
gateway = await manager.user_gateway("acct_example")
await gateway.send("123", "hello")
with pytest.raises(GatewayError, match="identity_not_found"):
    await manager.user_gateway("acct_missing")
```

### Task 3: Setup web API, browser page and multi-identity MCP tools ✅

**Files:**
- Create: `src/tg_mcp/web.py`
- Modify: `src/tg_mcp/auth.py`
- Modify: `src/tg_mcp/server.py`
- Modify: `src/tg_mcp/cli.py`
- Test: `tests/test_web.py`
- Modify: `tests/test_security.py`
- Modify: `tests/test_mcp.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `setup_routes(manager)` returns Starlette routes for `/` and `/setup/api/*`.
- `create_app(settings, manager, token, lifecycle)` registers setup routes and eight MCP tools.
- `BearerAuth` supports exact public paths and a loopback-only setup prefix when the service itself is loopback-bound.

- [x] Write failing tests for safe response headers, no setup data without remote Bearer auth, loopback direct QR access, body limits, account/bot CRUD actions that are in scope, and absence of token/QR/password in logs.
- [x] Add real HTTP MCP tests asserting `list_accounts`, `list_bots` and mandatory `account_id`/`bot_id`; verify overlapping chat IDs route to distinct gateways.
- [x] Implement the static no-dependency UI using text-safe DOM APIs, a memory-only bearer token, polling, QR image, 2FA field and separate optional bot section.
- [x] Implement setup JSON routes, security headers and updated MCP tools; keep `/mcp` protocol-only.
- [x] Update `serve` to acquire the state lock, create the manager and start HTTP with zero accounts; retain the previous CLI helpers as legacy migration paths.
- [x] Run web/MCP/security/CLI tests and mark Task 3 complete; no Git commit is available.

HTTP assertions:

```python
page = await client.get("/")
assert page.headers["cache-control"] == "no-store"
assert "Content-Security-Policy" in page.headers
unauthorized = await remote.get("/setup/api/status")
assert unauthorized.status_code == 401
```

### Task 4: Migration documentation, deployment and live local smoke test

**Files:**
- Modify: `README.md`
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `docs/verification.md`
- Modify: `docs/superpowers/specs/2026-09-16-telegram-mcp-design.md`

**Interfaces:**
- Local start: `TG_MCP_PORT=8765 uv run tg-mcp serve`, UI `/`, MCP `/mcp`.
- Docker start: UI `https://<domain>/`, MCP `https://<domain>/mcp`, setup API bearer-protected.

- [x] Document browser onboarding, multiple IDs, migration, local loopback behavior, remote token fragment, optional bots, disable/re-enable semantics and account-specific error recovery.
- [x] Update Compose health check and examples so `401` from `/mcp` and `200` from `/` both prove HTTP readiness without exposing setup data.
- [x] Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`, `uv build`, Compose config, Docker build and Caddy validation.
- [x] Start the local server on port 8765 using the imported Makosh application credentials; verify `/`, unauthorized `/mcp`, and setup API behavior. Open the UI for the owner to scan QR.
- [ ] After owner authorization, verify two account entries can independently reach `ready`; never send a live Telegram message without an explicit test-chat instruction.
- [ ] Record exact outcomes and mark Task 4 complete. Remote deployment and live bot send remain pending until the owner supplies a server/test chat.
