# Verification record

Date: 2026-09-23. Local environment: macOS, Python 3.12. Container target: Linux,
Python 3.12, UID/GID 10001.

| Check | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 51 files |
| `uv run pytest -q` | PASS, 129 tests |
| `uv build` | PASS, wheel and source distribution built for 0.5.2 |
| `TG_MCP_DOMAIN=mcp.example.test docker compose config --quiet` | PASS |
| `docker build -t tg-account-mcp:docs-audit .` | PASS |
| Tool catalog comparison | PASS, 44 implementation tools and 44 documented tools; no differences |
| Local Markdown link check | PASS |

The tests cover empty startup, atomic legacy-session migration, the QR → optional 2FA → account
name wizard, duplicate Telegram-user rejection, independent account failures, QR expiry, the
three-attempt password limit, hot enable/disable, multiple accounts and bots, cursors, attachment
chunks, folders, global search, drafts, idempotent writes, scoped tokens, and authenticated LAN
discovery. They use fake Telegram adapters and do not send real messages.

HTTP coverage includes the public data-free page shell, Bearer authentication for remote setup
and MCP requests, the strict loopback exception, exact Host and Origin allowlists, CSP and
`no-store`, request-size limits, and sanitized errors. The dashboard receives its displayed
version from the authenticated status response rather than from hard-coded HTML.

A direct-LAN deployment reproduced the documented Origin failure safely: with no allowed browser
Origin, an authenticated PATCH returned boundary-level `403 forbidden`; after adding the exact
dashboard Origin, the same request against a deliberately nonexistent identity reached
application validation and returned `400 identity_not_found`. No real identity changed during
that check.

An installed Codex plugin bridge with no fixed endpoint discovered an authenticated private LAN
service, initialized server version 0.5.2, and listed all 44 tools. No account names, tokens,
session data, message content, or Telegram credentials were recorded.

Publication status was checked against primary endpoints on 2026-09-23: GitHub release `v0.5.2`
and its release workflow are successful, PyPI reports 0.5.2, the matching GHCR manifest is
available, and the official MCP Registry returns the case-sensitive name
`io.github.Mesteriis/tg-account-mcp`.
