# Verification record

Date: 2026-09-23. Local environment: macOS, Python 3.12. Container target: Linux,
Python 3.12, UID/GID 10001.

| Check | Result |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 51 files |
| `uv run pytest -q` | PASS, 130 tests |
| `uv build` | PASS, wheel and source distribution built for 0.6.0 |
| `TG_MCP_DOMAIN=mcp.example.test docker compose config --quiet` | PASS |
| `docker build -t tg-account-mcp:0.6.0-rc .` | PASS |
| Tool catalog comparison | PASS, 44 implementation tools and 44 documented tools; no differences |
| Local Markdown link check | PASS |

The tests cover empty startup, atomic legacy-session migration, the QR → optional 2FA → account
name wizard, duplicate Telegram-user rejection, independent account failures, QR expiry, the
three-attempt password limit, hot enable/disable, multiple accounts and bots, cursors, attachment
chunks, folders, global search, drafts, idempotent writes, scoped tokens, and authenticated LAN
discovery. They use fake Telegram adapters and do not send real messages.

HTTP coverage includes the token-free dashboard and setup API, Bearer authentication for every
MCP method, exact Host and browser Origin checks, rejection of a foreign Origin, CSP and
`no-store`, request-size limits, and sanitized errors. The dashboard receives its displayed
version from the status response rather than from hard-coded HTML.

A direct-LAN deployment was previously used to validate the exact Origin boundary. The 0.6.0
regression suite now verifies that the dashboard's own Origin works without configuration or a
Bearer token while a foreign Origin still returns boundary-level `403 forbidden`.

An installed Codex plugin bridge with no fixed endpoint discovered an authenticated private LAN
service and listed all 44 tools. Dashboard authentication changes do not alter MCP or discovery
authentication. No account names, tokens, session data, message content, or Telegram credentials
were recorded.

The 0.6.0 candidate passed local release checks on 2026-09-23. Publication status is verified after
the release workflow finishes; the official MCP Registry name remains the case-sensitive
`io.github.Mesteriis/tg-account-mcp`.
