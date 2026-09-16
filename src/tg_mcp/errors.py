"""Stable errors that never interpolate upstream exceptions or request contents."""

from contextlib import contextmanager

from telethon import errors


class LocalError(RuntimeError):
    """A safe, application-authored diagnostic for local configuration or lifecycle."""


class GatewayError(Exception):
    def __init__(self, code: str, message: str, retry_after: int | None = None):
        self.code = code
        self.message = message
        self.retry_after = retry_after
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.retry_after is not None:
            result["retry_after_seconds"] = self.retry_after
        return result


@contextmanager
def telegram_errors(*, sending: bool = False):
    try:
        yield
    except GatewayError:
        raise
    except errors.FloodWaitError as exc:
        raise GatewayError("rate_limited", "Wait before trying again.", exc.seconds) from None
    except (errors.UnauthorizedError, errors.AuthKeyError, errors.AuthKeyNotFound):
        raise GatewayError("not_authorized", "Telegram session requires a new CLI login.") from None
    except errors.ForbiddenError:
        raise GatewayError("forbidden", "Telegram does not permit this operation.") from None
    except (errors.ServerError, errors.RpcCallFailError, ConnectionError, OSError, TimeoutError):
        if sending:
            raise GatewayError(
                "delivery_unknown", "Message may have been sent. Check history before retrying."
            ) from None
        raise GatewayError("unavailable", "Telegram is temporarily unavailable.") from None
    except (errors.BadRequestError, ValueError):
        raise GatewayError(
            "invalid_request", "Chat, message or request is not available."
        ) from None
    except errors.RPCError:
        raise GatewayError("telegram_error", "Telegram rejected the operation.") from None


def validate_text(text: str) -> None:
    if not text.strip() or len(text.encode("utf-16-le")) // 2 > 4096:
        raise GatewayError("invalid_request", "Text must contain 1–4096 UTF-16 code units.")
