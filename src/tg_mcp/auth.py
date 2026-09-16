"""Authenticate MCP and remote setup requests at the HTTP boundary."""

import ipaddress
import secrets
from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from tg_mcp.access import MASTER_ACCESS, AccessPolicy, current_access


def _loopback(value: str | None) -> bool:
    if value in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(value or "").is_loopback
    except ValueError:
        return False


class BearerAuth:
    def __init__(
        self,
        app: ASGIApp,
        token: str,
        hosts: list[str],
        origins: list[str],
        *,
        bind_host: str | None = None,
        scoped_token_resolver: Callable[[str], AccessPolicy | None] | None = None,
    ):
        self.app = app
        self._token = token.encode("ascii")
        self.hosts = {host.lower().encode("ascii") for host in hosts}
        self.origins = {origin.encode("ascii") for origin in origins}
        self.local_setup = _loopback(bind_host)
        self.scoped_token_resolver = scoped_token_resolver

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return

        headers = scope.get("headers", [])
        hosts = [value.lower() for key, value in headers if key.lower() == b"host"]
        origins = [value for key, value in headers if key.lower() == b"origin"]
        path = scope.get("path", "")
        client_host = scope.get("client", (None, 0))[0]
        local_setup_request = (
            path.startswith("/setup/api/") and self.local_setup and _loopback(client_host)
        )
        same_origin = bool(
            len(hosts) == 1
            and len(origins) == 1
            and origins[0].lower() in {b"http://" + hosts[0], b"https://" + hosts[0]}
        )
        if (
            len(hosts) != 1
            or hosts[0] not in self.hosts
            or len(origins) > 1
            or (
                origins
                and origins[0] not in self.origins
                and not (local_setup_request and same_origin)
            )
        ):
            await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
            return

        if scope.get("method") == "GET" and (path == "/" or path.startswith("/assets/")):
            await self.app(scope, receive, send)
            return
        if local_setup_request:
            await self.app(scope, receive, send)
            return

        authorization = [value for key, value in headers if key.lower() == b"authorization"]
        policy: AccessPolicy | None = None
        if len(authorization) == 1:
            scheme, _, token = authorization[0].partition(b" ")
            if scheme.lower() == b"bearer" and secrets.compare_digest(token, self._token):
                policy = MASTER_ACCESS
            elif scheme.lower() == b"bearer" and self.scoped_token_resolver is not None:
                try:
                    policy = self.scoped_token_resolver(token.decode("ascii"))
                except (UnicodeDecodeError, ValueError):
                    policy = None
        if policy is None:
            await JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        if not policy.is_master and not path.startswith("/mcp"):
            await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
            return
        context_token = current_access.set(policy)
        try:
            await self.app(scope, receive, send)
        finally:
            current_access.reset(context_token)
