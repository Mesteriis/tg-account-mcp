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


def test_codex_plugin_uses_environment_for_mcp_token() -> None:
    config = load_json(PLUGIN_ROOT / ".mcp.json")
    server = config["mcpServers"]["tg-account"]

    assert server["type"] == "http"
    assert server["url"] == "http://127.0.0.1:8765/mcp"
    assert server["bearer_token_env_var"] == "TG_MCP_TOKEN"
    assert "bearer_token" not in server
