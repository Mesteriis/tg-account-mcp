"""Signed, bounded continuation tokens; no session keys or access hashes."""

import base64
import hashlib
import hmac
import json

from tg_mcp.errors import GatewayError


class Cursors:
    def __init__(self, secret: str):
        self._key = secret.encode()

    def encode(self, kind: str, context: str, offset: int) -> str:
        data = json.dumps([kind, context, offset], separators=(",", ":")).encode()
        signature = hmac.digest(self._key, data, "sha256")
        return base64.urlsafe_b64encode(signature + data).decode()

    def decode(self, token: str | None, kind: str, context: str) -> int:
        if token is None:
            return 0
        try:
            if len(token) > 4096:
                raise ValueError
            raw = base64.b64decode(token, altchars=b"-_", validate=True)
            signature, data = raw[:32], raw[32:]
            if not hmac.compare_digest(signature, hmac.digest(self._key, data, "sha256")):
                raise ValueError
            parsed = json.loads(data)
            if (
                not isinstance(parsed, list)
                or len(parsed) != 3
                or parsed[:2] != [kind, context]
                or type(parsed[2]) is not int
                or parsed[2] < 0
            ):
                raise ValueError
            return parsed[2]
        except (ValueError, TypeError, UnicodeError):
            raise GatewayError(
                "invalid_cursor", "Use a cursor from the same chat and query."
            ) from None


def query_context(chat_id: str, query: str | None) -> str:
    return hashlib.sha256(json.dumps([chat_id, query]).encode()).hexdigest()
