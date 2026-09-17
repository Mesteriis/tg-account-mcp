"""Validated configuration; secret values have redacted representations."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from tg_mcp.discovery import DISCOVERY_PORT, local_ipv4_addresses, validate_endpoint


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    api_id: int = Field(gt=0, strict=True)
    api_hash: SecretStr
    mcp_token: SecretStr
    bot_token: SecretStr | None = None

    @field_validator("api_hash")
    @classmethod
    def validate_hash(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[a-fA-F0-9]{32}", value.get_secret_value()):
            raise ValueError("api_hash must contain 32 hexadecimal characters")
        return value

    @field_validator("mcp_token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", value.get_secret_value()):
            raise ValueError("MCP token must be generated with at least 32 random bytes")
        return value

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value and not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", value.get_secret_value()):
            raise ValueError("Invalid bot token format")
        return value


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    state_dir: Path
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_hosts: list[str] = Field(min_length=1)
    allowed_origins: list[str] = Field(default_factory=list)
    discovery_enabled: bool = False
    discovery_port: int = Field(default=DISCOVERY_PORT, ge=1, le=65535)
    discovery_url: str | None = None

    @field_validator("allowed_hosts", "allowed_origins")
    @classmethod
    def no_wildcards(cls, values: list[str]) -> list[str]:
        if any(not v or "*" in v or any(c.isspace() for c in v) for v in values):
            raise ValueError("Host and Origin allowlists must contain exact values")
        return values

    @field_validator("discovery_url")
    @classmethod
    def valid_discovery_url(cls, value: str | None) -> str | None:
        return validate_endpoint(value) if value is not None else None

    @classmethod
    def from_env(cls, state_dir: Path) -> "Settings":
        def csv(name: str, default: str) -> list[str]:
            return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]

        port = int(os.environ.get("TG_MCP_PORT", "8000"))
        host = os.environ.get("TG_MCP_BIND", "127.0.0.1")
        discovery_url = os.environ.get("TG_MCP_DISCOVERY_URL") or None
        discovery_mode = os.environ.get("TG_MCP_DISCOVERY", "auto").strip().lower()
        if discovery_mode == "auto":
            discovery_enabled = True
        elif discovery_mode in {"1", "true", "yes", "on"}:
            discovery_enabled = True
        elif discovery_mode in {"0", "false", "no", "off"}:
            discovery_enabled = False
        else:
            raise ValueError("TG_MCP_DISCOVERY must be auto, true, or false")

        allowed_hosts = csv("TG_MCP_ALLOWED_HOSTS", f"localhost:{port},127.0.0.1:{port}")
        if discovery_enabled:
            if discovery_url is not None:
                discovery_url = validate_endpoint(discovery_url)
                authority = urlsplit(discovery_url).netloc
                if authority not in allowed_hosts:
                    allowed_hosts.append(authority)
            else:
                for address in local_ipv4_addresses():
                    authority = f"{address}:{port}"
                    if authority not in allowed_hosts:
                        allowed_hosts.append(authority)
        return cls(
            state_dir=state_dir,
            host=host,
            port=port,
            allowed_hosts=allowed_hosts,
            allowed_origins=csv("TG_MCP_ALLOWED_ORIGINS", ""),
            discovery_enabled=discovery_enabled,
            discovery_port=int(os.environ.get("TG_MCP_DISCOVERY_PORT", str(DISCOVERY_PORT))),
            discovery_url=discovery_url,
        )
