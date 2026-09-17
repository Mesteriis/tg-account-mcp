import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "tg-account-mcp"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_codex_plugin_marketplace_points_to_valid_plugin() -> None:
    marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    entry = next(item for item in marketplace["plugins"] if item["name"] == "tg-account-mcp")
    source = ROOT / entry["source"]["path"]
    manifest = load_json(source / ".codex-plugin" / "plugin.json")

    assert source == PLUGIN_ROOT
    assert manifest["name"] == PLUGIN_ROOT.name
    assert manifest["mcpServers"] == "./.mcp.json"
    assert (source / manifest["skills"]).is_dir()


def test_codex_plugin_uses_discovery_bridge_without_embedding_a_token() -> None:
    config = load_json(PLUGIN_ROOT / ".mcp.json")
    server = config["mcpServers"]["tg-account"]

    assert server["command"] == "uvx"
    assert server["args"] == [
        "--from",
        "tg-account-mcp==0.5.1",
        "tg-mcp",
        "bridge",
    ]
    assert "TG_MCP_TOKEN" in server["env_vars"]
    assert "TG_MCP_STATE_DIR" in server["env_vars"]
    assert "bearer_token" not in server
    assert "url" not in server
