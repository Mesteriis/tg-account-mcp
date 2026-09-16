# Contributing

Thank you for improving Telegram multi-account MCP. Changes should preserve its core guarantees:
explicit sender selection, least-privilege agent access, private local state, and sanitized errors.

## Development setup

Install Python 3.12+ and [uv](https://docs.astral.sh/uv/), then run:

```sh
uv sync --frozen
uv run pytest -q
```

Telegram credentials are not required for tests. The test suite uses fake adapters and must not
send messages, read a developer's account, or depend on a local session.

## Making a change

1. Open an issue for a bug or a focused proposal. Discuss broad protocol, storage, or security
   changes before implementing them.
2. Keep changes scoped. Do not include credentials, session files, tokens, message contents, or
   local state in commits, fixtures, screenshots, or logs.
3. Add regression coverage for behavior changes. Use the fake adapters for Telegram boundaries.
4. Update the README, tool catalog, changelog, or deployment docs when public behavior changes.
5. Run the checks below before opening a pull request.

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
TG_MCP_DOMAIN=mcp.example.test docker compose config --quiet
docker build -t tg-account-mcp:local .
```

Changes under `plugins/tg-account-mcp` must also pass the bundled Codex validators:

```sh
python3 "$HOME/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py" \
  plugins/tg-account-mcp
python3 "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" \
  plugins/tg-account-mcp/skills/telegram-agent-workflows
```

## Pull requests

Describe the user-visible behavior, the failure mode being addressed, and the checks you ran.
Keep unrelated formatting or refactoring out of the same pull request. A maintainer may ask for a
smaller change when the security or compatibility impact is difficult to review.

Pull requests must not perform a real Telegram send as part of automated testing. If a live test
is necessary, document it separately and use only an explicitly chosen test chat.

## Security changes

Authentication, authorization, session storage, URL parsing, file downloads, message sending,
and error handling are security-sensitive. Include tests for denied access and failure behavior.
Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
