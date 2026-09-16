# TG multi-account MCP

<!-- mcp-name: io.github.mesteriis/tg-account-mcp -->

[Русская документация](README.ru.md)

A self-hosted [Model Context Protocol](https://modelcontextprotocol.io/) server that lets
AI agents work with Telegram through explicitly selected user accounts and optional bots.
Accounts are connected in a local web wizard by scanning a QR code and entering a Telegram
2FA password when required.

The server is designed as an agent tool rather than a Telegram client. It can search chat
history, read folders and threads, download attachments, track updates, create drafts, and
send messages. Every operation names the account or bot it uses; the server never silently
selects a sender.

> [!IMPORTANT]
> A Telegram session can access the corresponding account. Run this service on infrastructure
> you control, protect the state directory and MCP tokens, and give agent tokens only the
> permissions they need.

This is an unofficial integration that uses the Telegram API and is not affiliated with or
endorsed by Telegram.

## What it supports

- Multiple Telegram user accounts, each with its own QR/2FA onboarding flow and session.
- Optional Telegram bots connected independently through BotFather tokens.
- Streamable HTTP MCP with Bearer-token authentication.
- Chat, folder, message, attachment, mention, topic, reply-thread, and global search tools.
- Cyrillic/Latin transliteration matching when finding chats.
- User and bot sending, edits, scheduling, forwarding, reactions, drafts, and idempotency keys.
- Scoped agent tokens with `read`, `send`, and `admin` permissions plus identity/chat allowlists.
- A private operations dashboard that records metadata without message text, queries, passwords,
  or tokens.
- Docker Compose deployment with Caddy-managed HTTPS.

The current release exposes 44 MCP tools. See the [tool catalog](docs/tools.md) for the full
list and behavior notes.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A Telegram `api_id` and `api_hash` from
  [my.telegram.org](https://my.telegram.org/apps)

Docker and a domain are required only for the Compose deployment.

## Quick start

```sh
uv sync --frozen
uv run tg-mcp setup
TG_MCP_PORT=8765 uv run tg-mcp serve
```

`setup` requests the Telegram API credentials through local terminal input and generates a
random MCP access token. It does not request your phone number or account password.

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) and follow the account wizard:

1. Scan the QR code in **Telegram → Settings → Devices → Link Desktop Device**.
2. Enter the Telegram cloud password if 2FA is enabled.
3. Give the account a local display name.

Repeat the wizard to add more accounts. Bots are optional and are added separately in the
dashboard. Their tokens are verified with Telegram before storage.

The state directory defaults to `~/.local/share/tg-mcp`. Override it with `--state-dir` or
`TG_MCP_STATE_DIR`.

## Connect an MCP client

Print the main token locally:

```sh
uv run tg-mcp show-token
```

Configure the client to use the Streamable HTTP endpoint and Bearer header:

```json
{
  "url": "http://127.0.0.1:8765/mcp",
  "headers": {
    "Authorization": "Bearer <MCP_TOKEN>"
  }
}
```

The surrounding configuration shape depends on the MCP client. Clients that require OAuth and
cannot set a Bearer header are not currently supported.

Start with `get_capabilities`, `list_accounts`, and `list_bots`. All account and bot operations
require an explicit stable ID such as `acct_…` or `bot_…`.

For a folder-oriented request such as “show today’s messages in ITQ that concern my tasks,” an
agent can call `list_folders`, then `get_folder_messages` with matching `date_from` and `date_to`
values and an IANA timezone such as `Europe/Madrid`, provided that processing this content is
permitted under the consent requirements below.

## Codex plugin

This repository also ships a Codex plugin with the MCP connection and a workflow skill for chat
resolution, folder summaries, complete pagination, attachments, drafts, and idempotent sending.

```sh
export TG_MCP_TOKEN="$(uv run tg-mcp show-token)"
codex plugin marketplace add Mesteriis/tg-account-mcp --ref main
codex plugin add tg-account-mcp@tg-account-mcp
```

The bundled endpoint is `http://127.0.0.1:8765/mcp`. See the
[Codex plugin guide](docs/CODEX_PLUGIN.md) for remote-server setup and example prompts.

## Responsible use and Telegram terms

Operators must comply with the [Telegram API Terms](https://core.telegram.org/api/terms) and
[Content Licensing Terms](https://telegram.org/tos/content-licensing). In particular:

- obtain and use your own Telegram `api_id`;
- do not perform actions on a user's behalf without that user's knowledge and consent;
- do not scrape, index, harvest, aggregate, train on, benchmark with, or otherwise provide
  Telegram content to AI/ML systems unless every relevant user has given explicit, informed,
  affirmative, and continuing consent for the specific content and context;
- respect the rights, privacy, and instructions of people whose messages or files are accessed.

Installing this software does not grant rights to Telegram content. Use synthetic data, your own
saved messages, or chats where the required consent has been obtained and remains valid.

## Agent access control

The token generated by `setup` is the administrative token. Use `create_agent_token` to issue a
separate token for each agent and restrict it by:

- scope: `read`, `send`, or `admin`;
- permitted account and bot IDs;
- permitted chat IDs.

Only a SHA-256 hash of an agent token is retained, and the plaintext token is returned once.
Revoke access with `revoke_agent_token`. A chat-limited token cannot use aggregate inbox, folder,
or global-search tools because those operations could reveal neighboring chats.

## Docker Compose deployment

Point a domain at the server and allow inbound TCP 80/443, then run:

```sh
cp .env.example .env
# Set TG_MCP_DOMAIN to the real hostname in .env.
docker compose build
docker compose run --rm --no-deps tg-mcp setup
docker compose up -d
```

Open `https://your-domain.example/#token=<MCP_TOKEN>` for initial setup. The URL fragment is not
sent to the server; the page removes it from the address bar and keeps the token in tab memory.
Agents connect to `https://your-domain.example/mcp`.

Caddy terminates HTTPS and does not expose the application port publicly. The application
container runs as an unprivileged user with a read-only root filesystem. Run one application
replica per state volume.

## Security model

- The state directory is required to have mode `0700`; sensitive files use `0600`.
- Symlinks, hard-linked sensitive files, foreign ownership, and broad permissions are rejected.
- The web UI has no third-party scripts, fonts, analytics, or remote assets.
- Account data and setup APIs require the Bearer token when the service is not loopback-bound.
- Host and Origin values are checked against exact allowlists; wildcards are rejected.
- Logs and operations history omit message bodies, search terms, credentials, QR URLs, and 2FA
  passwords.
- Tests use fake Telegram adapters and never send real messages.

Back up the state volume only while the service is stopped and store the backup encrypted. If a
session is exposed, revoke it from **Telegram → Devices**. See [SECURITY.md](SECURITY.md) for
reporting vulnerabilities and the Russian README for operational details and error codes.

## Known limitations

- Secret chats are not available through Telegram's cloud API.
- Message deletion and distributed/multi-replica deployment are not supported.
- History is read from Telegram on demand rather than copied into a local database.
- Positional pagination can repeat or skip items when new messages arrive between pages.
- `poll_updates` keeps its most recent 2,000 events in process memory and resets after restart.

## Development

```sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
TG_MCP_DOMAIN=mcp.example.test docker compose config --quiet
docker build -t tg-account-mcp:local .
```

Architecture and contributor setup are documented in [docs/architecture.md](docs/architecture.md)
and [CONTRIBUTING.md](CONTRIBUTING.md). Release and registry steps are in
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
