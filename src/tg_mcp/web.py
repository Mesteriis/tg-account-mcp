# ruff: noqa: E501
"""Small, dependency-free setup page and JSON administration routes."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from tg_mcp.errors import GatewayError

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

STATIC_ROOT = Path(__file__).with_name("static")
PAGE = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")


class LabelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=64)


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BotBody(LabelBody):
    token: str = Field(min_length=21, max_length=256)


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)


class PatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=SECURITY_HEADERS)


async def _body(request: Request, model):
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > 8192):
        raise GatewayError("request_too_large", "Request body is too large.")
    body = await request.body()
    if len(body) > 8192:
        raise GatewayError("request_too_large", "Request body is too large.")
    try:
        return model.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError):
        raise GatewayError("invalid_request", "Request body is invalid.") from None


def setup_routes(manager, telemetry) -> list[Route]:
    async def page(request: Request) -> Response:
        return HTMLResponse(PAGE, headers=SECURITY_HEADERS)

    async def asset(request: Request) -> Response:
        name = request.path_params["name"]
        allowed = {
            "app.css",
            "app.js",
            "icons.css",
            "phosphor.woff2",
            "inter-cyrillic.woff2",
        }
        is_icon = name.startswith("icon-") and name.endswith(".svg")
        if name not in allowed and not (is_icon and (STATIC_ROOT / name).is_file()):
            return Response(status_code=404, headers=SECURITY_HEADERS)
        return FileResponse(STATIC_ROOT / name, headers={"X-Content-Type-Options": "nosniff"})

    async def status(request: Request) -> Response:
        accounts = [manager.login_state(row["account_id"]) for row in manager.list_accounts()]
        return _json(
            {
                "summary": manager.status(),
                "accounts": accounts,
                "bots": manager.list_bots(),
                "analytics": telemetry.snapshot(days=30),
            }
        )

    async def accounts(request: Request) -> Response:
        try:
            await _body(request, EmptyBody)
            return _json(await manager.add_account(), 201)
        except GatewayError as exc:
            return _json({"error": exc.as_dict()}, 413 if exc.code == "request_too_large" else 400)

    async def account_login(request: Request) -> Response:
        try:
            return _json(await manager.begin_login(request.path_params["account_id"]))
        except GatewayError as exc:
            code = 404 if exc.code == "identity_not_found" else 409
            return _json({"error": exc.as_dict()}, code)

    async def account_password(request: Request) -> Response:
        try:
            body = await _body(request, PasswordBody)
            result = await manager.submit_password(request.path_params["account_id"], body.password)
            return _json(result)
        except GatewayError as exc:
            return _json({"error": exc.as_dict()}, 400)

    async def account_patch(request: Request) -> Response:
        try:
            body = await _body(request, PatchBody)
            account_id = request.path_params["account_id"]
            result = None
            if body.label is not None:
                result = await manager.rename_account(account_id, body.label)
            if body.enabled is not None:
                result = await manager.set_account_enabled(account_id, body.enabled)
            if result is None:
                raise GatewayError("invalid_request", "No account change was requested.")
            return _json(result)
        except GatewayError as exc:
            return _json({"error": exc.as_dict()}, 400)

    async def bots(request: Request) -> Response:
        try:
            body = await _body(request, BotBody)
            return _json(await manager.add_bot(body.label, body.token), 201)
        except GatewayError as exc:
            return _json({"error": exc.as_dict()}, 413 if exc.code == "request_too_large" else 400)

    async def bot_patch(request: Request) -> Response:
        try:
            body = await _body(request, PatchBody)
            bot_id = request.path_params["bot_id"]
            result = None
            if body.label is not None:
                result = await manager.rename_bot(bot_id, body.label)
            if body.enabled is not None:
                result = await manager.set_bot_enabled(bot_id, body.enabled)
            if result is None:
                raise GatewayError("invalid_request", "No bot change was requested.")
            return _json(result)
        except GatewayError as exc:
            return _json({"error": exc.as_dict()}, 400)

    return [
        Route("/", page, methods=["GET"]),
        Route("/assets/{name:str}", asset, methods=["GET"]),
        Route("/setup/api/status", status, methods=["GET"]),
        Route("/setup/api/accounts", accounts, methods=["POST"]),
        Route("/setup/api/accounts/{account_id:str}/login", account_login, methods=["POST"]),
        Route(
            "/setup/api/accounts/{account_id:str}/password",
            account_password,
            methods=["POST"],
        ),
        Route("/setup/api/accounts/{account_id:str}", account_patch, methods=["PATCH"]),
        Route("/setup/api/bots", bots, methods=["POST"]),
        Route("/setup/api/bots/{bot_id:str}", bot_patch, methods=["PATCH"]),
    ]
