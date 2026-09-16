# Codex plugin

The repository includes a Codex plugin that connects to a locally running TG Account MCP server
and teaches Codex reliable multi-account Telegram workflows.

## Install from GitHub

Start the server on its plugin default endpoint:

```sh
TG_MCP_PORT=8765 uv run tg-mcp serve
```

Make the MCP token available to the environment that starts Codex:

```sh
export TG_MCP_TOKEN="$(uv run tg-mcp show-token)"
```

Do not commit the token or put it in the plugin files. Install the repository marketplace and the
plugin:

```sh
codex plugin marketplace add Mesteriis/tg-account-mcp --ref main
codex plugin add tg-account-mcp@tg-account-mcp
```

Restart Codex and open a new task so the plugin's MCP server and skill are loaded.

The bundled MCP configuration targets `http://127.0.0.1:8765/mcp`. For a remote deployment,
configure the MCP server separately with its HTTPS endpoint while keeping the plugin installed for
its workflow skill:

```sh
codex mcp add tg-account \
  --url https://telegram.example.com/mcp \
  --bearer-token-env-var TG_MCP_TOKEN
```

Use a scoped agent token rather than the administrative token whenever possible.

## Useful first prompts

- “Show today's messages in my ITQ folder that concern my tasks.”
- “Find my dialog with Dmitry Krivov and summarize September.”
- “Draft a reply to this Telegram message for my review.”
- “Send the approved reply from my work account.”

