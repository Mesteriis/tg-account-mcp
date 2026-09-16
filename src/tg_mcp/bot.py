"""Small Bot API adapter; no polling, webhook changes, or implicit retries."""

import httpx

from tg_mcp.errors import GatewayError, validate_text


class BotGateway:
    def __init__(self, token: str | None, client: httpx.AsyncClient):
        self._token = token
        self.client = client

    async def _call(self, method: str, payload: dict, *, sending: bool = False) -> dict:
        if self._token is None:
            raise GatewayError("bot_not_configured", "Run tg-mcp set-bot on the server.")
        try:
            response = await self.client.post(
                f"https://api.telegram.org/bot{self._token}/{method}",
                json=payload,
            )
            if response.status_code >= 500:
                raise GatewayError(
                    "delivery_unknown" if sending else "unavailable",
                    "Telegram server error. Check history before retrying a send.",
                )
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            if response.is_success and data.get("ok") is True:
                result = data["result"]
                if not isinstance(result, dict):
                    raise ValueError
                return result
            code = data.get("error_code", response.status_code)
            if code == 429:
                retry = data.get("parameters", {}).get("retry_after")
                raise GatewayError(
                    "rate_limited",
                    "Wait before trying again.",
                    retry if type(retry) is int and retry >= 0 else None,
                )
            if code in (401, 404):
                raise GatewayError("not_authorized", "Bot token is invalid or revoked.")
            if code == 403:
                raise GatewayError("forbidden", "Bot cannot write to this chat.")
            raise GatewayError("invalid_request", "Bot API rejected the chat, message or request.")
        except GatewayError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise GatewayError(
                "delivery_unknown" if sending else "unavailable",
                "Telegram response unavailable. Check history before retrying a send.",
            ) from None

    async def status(self) -> dict:
        if self._token is None:
            return {"configured": False}
        data = await self._call("getMe", {})
        try:
            return {"configured": True, "id": str(data["id"]), "username": data.get("username")}
        except KeyError:
            raise GatewayError("unavailable", "Invalid bot identity response.") from None

    async def send(self, chat_id: str, text: str, reply_to: str | None = None) -> dict:
        validate_text(text)
        payload = {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}}
        if reply_to:
            payload["reply_parameters"] = {
                "message_id": int(reply_to),
                "allow_sending_without_reply": False,
            }
        data = await self._call("sendMessage", payload, sending=True)
        try:
            sender = data.get("sender_chat") or data.get("from")
            return {
                "sender": "bot",
                "sender_id": str(sender["id"]),
                "chat_id": str(data["chat"]["id"]),
                "message_id": str(data["message_id"]),
            }
        except (KeyError, TypeError):
            raise GatewayError(
                "delivery_unknown", "Invalid message receipt. Check history before retrying."
            ) from None
