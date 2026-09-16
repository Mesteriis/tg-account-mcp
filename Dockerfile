FROM ghcr.io/astral-sh/uv:0.12.15 AS uv
FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --no-cache

FROM python:3.12-slim
LABEL org.opencontainers.image.title="TG multi-account MCP" \
    org.opencontainers.image.description="Self-hosted multi-account Telegram MCP server for AI agents" \
    org.opencontainers.image.source="https://github.com/Mesteriis/tg-account-mcp" \
    org.opencontainers.image.licenses="Apache-2.0" \
    io.modelcontextprotocol.server.name="io.github.mesteriis/tg-account-mcp"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TG_MCP_STATE_DIR=/var/lib/tg-mcp
RUN groupadd --gid 10001 tgmcp \
    && useradd --uid 10001 --gid 10001 --no-create-home tgmcp \
    && mkdir -p /var/lib/tg-mcp \
    && chown 10001:10001 /var/lib/tg-mcp \
    && chmod 0700 /var/lib/tg-mcp
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
USER 10001:10001
ENTRYPOINT ["tg-mcp"]
CMD ["serve"]
