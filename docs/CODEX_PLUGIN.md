# Codex plugin

The repository includes a Codex plugin that finds an authenticated TG Account MCP service on the
same machine or local network and teaches Codex reliable multi-account Telegram workflows.

## Install from GitHub

Start the server on its plugin default endpoint:

```sh
TG_MCP_PORT=8765 uv run tg-mcp serve
```

When the server runs on another machine, make the MCP token available to the environment that
starts Codex:

```sh
export TG_MCP_TOKEN="$(uv run tg-mcp show-token)"
```

On the same machine, the bridge reads the token from `~/.local/share/tg-mcp` (or
`TG_MCP_STATE_DIR`) using the state store's ownership and permission checks, so this export is not
needed. Do not commit the token or put it in the plugin files. Install the repository marketplace
and the plugin:

```sh
codex plugin marketplace add Mesteriis/tg-account-mcp --ref main
codex plugin add tg-account-mcp@tg-account-mcp
```

Restart Codex and open a new task so the plugin's MCP server and skill are loaded. The plugin
starts a small stdio bridge with `uvx` and sends an authenticated UDP discovery request to the
local machine and network on port `38475`.

The discovery proof is derived from the SHA-256 digest of `TG_MCP_TOKEN`. The service only answers
valid proofs and signs its endpoint response, so automatic discovery never broadcasts the Bearer
token or sends it before authenticating the endpoint.

To make a directly launched server discoverable on the LAN, bind it to all interfaces. Exact local
interface addresses are added to the Host allowlist when discovery is active:

```sh
TG_MCP_BIND=0.0.0.0 TG_MCP_PORT=8765 uv run tg-mcp serve
```

Allow inbound TCP `8765` and UDP `38475` only from the trusted local network. Docker Compose
publishes the UDP discovery port and advertises its configured HTTPS domain.

Set `TG_MCP_URL=https://telegram.example.com/mcp` in the Codex environment to skip loopback and
LAN discovery. Set the same `TG_MCP_DISCOVERY_PORT` on the client and server if the default UDP
port cannot be used. Broadcast discovery normally stays within one subnet and may be blocked by
guest Wi-Fi, VLAN, VPN, or router policy; `TG_MCP_URL` is the deterministic fallback.

Use a scoped agent token rather than the administrative token whenever possible. Active scoped
tokens can authenticate discovery without exposing their stored hashes.

## Useful first prompts

- “Show today's messages in my ITQ folder that concern my tasks.”
- “Find my dialog with Dmitry Krivov and summarize September.”
- “Draft a reply to this Telegram message for my review.”
- “Send the approved reply from my work account.”
