# TG multi-account MCP

<!-- mcp-name: io.github.Mesteriis/tg-account-mcp -->

[![CI](https://github.com/Mesteriis/tg-account-mcp/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/Mesteriis/tg-account-mcp/actions/workflows/ci.yml?query=branch%3Amain)
[![PyPI](https://img.shields.io/pypi/v/tg-account-mcp)](https://pypi.org/project/tg-account-mcp/)
[![Python](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpypi.org%2Fpypi%2Ftg-account-mcp%2Fjson&query=%24.info.requires_python&label=Python&color=blue)](https://pypi.org/project/tg-account-mcp/)
[![License](https://img.shields.io/github/license/Mesteriis/tg-account-mcp)](LICENSE)

[![TG multi-account MCP server](https://mcprush.com/badge/tg-multi-account-mcp/card.svg)](https://mcprush.com/to/tg-multi-account-mcp?ref=badge)

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
- Dashboard controls to disable, reconnect, or permanently delete an account and its local session.
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

Install the published package:

```sh
uv tool install tg-account-mcp
tg-mcp setup
TG_MCP_PORT=8765 tg-mcp serve
```

For development from a source checkout:

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

This repository also ships a Codex plugin with authenticated automatic service discovery and a
workflow skill for chat resolution, folder summaries, complete pagination, attachments, drafts,
and idempotent sending.

```sh
codex plugin marketplace add Mesteriis/tg-account-mcp --ref main
codex plugin add tg-account-mcp@tg-account-mcp
```

The plugin sends an authenticated discovery request to the local machine and network. Discovery
requests and replies are authenticated using the configured MCP token; the token itself is never
broadcast or sent before the discovered endpoint is authenticated. Set `TG_MCP_URL` to skip
discovery and use a specific HTTPS endpoint. See the
[Codex plugin guide](docs/CODEX_PLUGIN.md) for server setup and example prompts.

When Codex and the service run as the same OS user on one machine, the bridge reads the token from
the protected local state automatically. For a service on another machine, provide
`TG_MCP_TOKEN` to the Codex process.

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

## Direct LAN deployment

For a trusted private network without the Compose HTTPS proxy, bind the service to the LAN and
start it on the LAN:

```sh
TG_MCP_BIND=0.0.0.0 \
TG_MCP_PORT=8765 \
TG_MCP_TRUSTED_NETWORKS=192.168.1.0/24 \
tg-mcp serve
```

`TG_MCP_TRUSTED_NETWORKS` is optional and defaults to empty. When set to private CIDR ranges,
clients whose direct TCP peer address is in one of those ranges can use `/mcp` without a Bearer
token. This grants full administrative MCP access to every device in those ranges. Do not expose
the service beyond the trusted LAN; forwarded client-address headers are not used for this check.

Open the server's LAN address in a browser. The dashboard does not ask for a token, so every user
who can reach it can view its metadata and manage Telegram identities. Same-origin browser requests
are accepted automatically; a separate frontend origin must be added to
`TG_MCP_ALLOWED_ORIGINS`. Permit TCP `8765` and discovery UDP `38475` only from trusted networks.
Use a VPN or an authenticating reverse proxy when traffic crosses an untrusted network.

## Docker Compose deployment

Point a domain at the server and allow inbound TCP 80/443, then run:

```sh
cp .env.example .env
# Set TG_MCP_DOMAIN to the real hostname in .env.
docker compose build
docker compose run --rm --no-deps tg-mcp setup
docker compose up -d
```

Open `https://your-domain.example/` for initial setup. The dashboard is intentionally available
without a token; protect the domain with network policy or an authenticating reverse proxy.
Agents still connect to `https://your-domain.example/mcp` with a Bearer token.

Compose also publishes authenticated UDP discovery on port `38475` and advertises that HTTPS
endpoint to clients on the same private network. Change `TG_MCP_DISCOVERY_PORT` on both sides when
needed, or set `TG_MCP_DISCOVERY=false` if local discovery is not part of the deployment.

Caddy terminates HTTPS and does not expose the application port publicly. The application
container runs as an unprivileged user with a read-only root filesystem. Run one application
replica per state volume.

## Security model

- The state directory is required to have mode `0700`; sensitive files use `0600`.
- Symlinks, hard-linked sensitive files, foreign ownership, and broad permissions are rejected.
- The web UI has no third-party scripts, fonts, analytics, or remote assets.
- Dashboard account data and setup APIs are available without a token to clients that can reach
  the server. The MCP endpoint requires a Bearer token unless an operator explicitly configures
  `TG_MCP_TRUSTED_NETWORKS`; that opt-in grants full MCP access to clients in those private CIDRs.
- Host and Origin values are checked against exact allowlists; wildcards are rejected.
- Logs and operations history omit message bodies, search terms, credentials, QR URLs, and 2FA
  passwords.
- Tests use fake Telegram adapters and never send real messages.

Back up the state volume only while the service is stopped and store the backup encrypted. If a
session is exposed, revoke it from **Telegram → Devices**. See [SECURITY.md](SECURITY.md) for
reporting vulnerabilities and the Russian README for operational details and error codes.

## Local chat archives

Opt in selected chats to persistent local history, observed edit versions and full-text search.
Deleted-content retention is off by default. See [archive setup and limitations](docs/archive.md)
and the [tool catalog](docs/tools.md#local-archives).

[Project memory and semantic search](docs/project-memory.md) add source-backed drafts, explicit
approval and opt-in local Ollama embeddings. Projects stay isolated; source edits and deletions
invalidate derived memory. Keyword search works without an embedding model.
[Optional background RAG](docs/background-rag.md) automatically discovers all current/future
user-account chats, groups and channels and maintains local embeddings.

## Known limitations

- Secret chats are not available through Telegram's cloud API.
- Message deletion and distributed/multi-replica deployment are not supported.
- History tools read Telegram on demand. Only explicitly selected chats are copied to the local
  archive; observed coverage and deletion events are not guaranteed complete.
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

### Local-first message retrieval

Use `find_messages(account_id, query, chat_id=..., telegram="auto")` as the preferred message
retrieval tool. It combines local lexical matches and semantic candidates, deduplicates by
account/chat/message ID, and falls back to one bounded Telegram page when local results or
coverage are insufficient. `telegram="never"` makes no Telegram reads; `"always"` verifies
freshness. Optional `date_from`/`date_to` are inclusive UTC dates. `include_context=true` reads
only the top result with two neighboring messages each side, unless local-only mode is selected.

Inspect `partial`, `warnings`, `local_coverage`, `semantic_partial` and provenance. Semantic
retrieval remains bounded to 2000 recent indexed messages in scope; lexical search covers the
retained archive. Account-wide inventory is not certified complete, so automatic account-wide
queries may also consult Telegram. Results are a bounded ranking, not a full export, and scores
are not confidence. A Telegram cursor must be continued with the returned native `cursor_tool`
(`search_messages` or `search_all_messages`), preserving the account/query/chat/date arguments.

Fallback/context reads share the account's adaptive loading gate. Telegram failures, cooldowns
or timeouts preserve local results with explicit warnings. No deleted content is returned and
no source is automatically enabled, archived or reindexed by a retrieval request. Chat-restricted
tokens must supply an allowed `chat_id`; account-wide retrieval is rejected before any reads.

### Continuous text and S3 ingestion

Private chats always enable text RAG and every supported attachment type. Group and
channel defaults keep text RAG enabled and S3 disabled; set their rules on the RAG
page or with admin `set_ingestion_policy`. A discovered chat can override its type's
rule or inherit it again. `get_ingestion_policy` reads one chat's effective rule.
Global changes require an admin token unrestricted by identity or chat. Explicitly
paused archives, excluded chats and disabled accounts remain paused.

RAG text and S3 files are separate switches. S3 types are `photo`, `video`,
`document`, `audio`, `voice`, `video_note`, `sticker`, `animation`. Captions can enter
text RAG; files are stored as original binary objects, without OCR or transcription.
Disabling a rule stops future ingestion and keeps existing data. Re-enabling text
RAG restarts history coverage; enabling S3 seeds existing saved attachment metadata.
New live messages enqueue immediately; transfers are asynchronous, newest first,
with fair turns between ready accounts. Telegram discovery still runs every configured
interval. Downloads share the persistent adaptive Telegram gate with history reads;
FloodWait pauses and increased intervals apply to both. Semantic embeddings remain local.

Configure a private S3-compatible endpoint using `TG_MCP_S3_ENDPOINT`,
`TG_MCP_S3_REGION` (default `garage`), `TG_MCP_S3_BUCKET`, `TG_MCP_S3_PREFIX`
(default `telegram`), `TG_MCP_S3_ACCESS_KEY` and `TG_MCP_S3_SECRET_KEY`.
Supply endpoint, bucket and both credentials together in a private environment file;
S3 requires background RAG and its local embedding provider. The endpoint must be
loopback/private network; public endpoints and environment proxies are not used.
Provision the bucket and scoped credentials separately; never commit them.

The worker keeps a private resumable spool, durable upload intents and idempotent
object keys, checks object length and SHA-256 metadata after upload, and reserves
5 GiB of local free space. Telegram files that disappeared before download are
reported as skipped. Dashboard status reports queued, saved, failed and pending
S3 deletion counts without file names or credentials. Purging an archive schedules
object deletion; `media_cleanup_pending` reports this asynchronous cleanup queue.
Telegram deletion retention follows the chat's existing `retain_deleted` setting.
Back up the SQLite archive, spool, credentials and S3 service data together; an
S3 service on the same machine is storage, not an independent backup.
