"""Server-local administration. No secrets in command-line arguments."""

import argparse
import asyncio
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from getpass import getpass
from pathlib import Path

import httpx
import qrcode
import uvicorn
from pydantic import ValidationError

from tg_mcp.bot import BotGateway
from tg_mcp.config import Credentials, Settings
from tg_mcp.errors import GatewayError, LocalError, telegram_errors
from tg_mcp.manager import IdentityManager
from tg_mcp.onboarding import login_with_qr
from tg_mcp.server import create_app
from tg_mcp.storage import StateStore
from tg_mcp.telegram import make_client


def configure_logging() -> None:
    # Upstream loggers can print token-bearing URLs, RPC requests and validation inputs.
    # Keep our own safe event messages, suppress dependency diagnostics in production.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for name in ("mcp", "mcp_types", "telethon", "httpx", "httpcore", "httpx2", "httpcore2"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False)


async def login(store: StateStore, credentials: Credentials) -> None:
    client = make_client(store, credentials)

    def show_qr(url: str) -> None:
        print("Scan in Telegram → Settings → Devices → Link Desktop Device.", file=sys.stderr)
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.print_ascii(out=sys.stderr, invert=True)

    async def password() -> str:
        # Keep the event loop free so Telethon can continue receiving updates during input.
        return await asyncio.to_thread(getpass, "Telegram 2FA password (up to 3 attempts): ")

    try:
        with telegram_errors():
            await client.connect()
            await login_with_qr(client, show_qr, password)
        print("Telegram session saved.")
    finally:
        await client.disconnect()


async def set_bot(store: StateStore, credentials: Credentials, token: str) -> None:
    updated = Credentials(
        api_id=credentials.api_id,
        api_hash=credentials.api_hash,
        mcp_token=credentials.mcp_token,
        bot_token=token,
    )
    async with http_client() as http:
        await BotGateway(token, http).status()
    store.save(updated)
    print("Bot verified and saved.")


def serve(store: StateStore, credentials: Credentials) -> None:
    settings = Settings.from_env(store.root)
    http = http_client()
    manager = IdentityManager(store, credentials, http)

    @asynccontextmanager
    async def lifecycle():
        try:
            await manager.start()
            yield
        finally:
            await manager.close()
            await http.aclose()

    app = create_app(
        settings,
        manager,
        credentials.mcp_token.get_secret_value(),
        lifecycle=lifecycle,
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        workers=1,
        access_log=False,
        proxy_headers=False,
        log_level="warning",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private Telegram MCP server")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.environ.get("TG_MCP_STATE_DIR", "~/.local/share/tg-mcp")).expanduser(),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("setup", "Create credentials using hidden input; generates an MCP token"),
        ("login", "Legacy single-account QR login (prefer the setup web page)"),
        ("set-bot", "Legacy single-bot setup (prefer the setup web page)"),
        ("rotate-token", "Replace the MCP access token (stop the service first)"),
        ("show-token", "Print the MCP token for secure client provisioning"),
        ("serve", "Run the MCP HTTP service with one worker"),
    ):
        commands.add_parser(command, help=help_text)
    args = parser.parse_args(argv)
    previous_umask = os.umask(0o077)
    configure_logging()
    try:
        store = StateStore(args.state_dir)
        # Read-only token retrieval is safe while the server owns the session lock.
        if args.command == "show-token":
            print(store.load().mcp_token.get_secret_value())
            return 0
        with store.lock():
            if args.command == "setup":
                if (store.root / "credentials.json").exists():
                    raise LocalError("Already configured; use login, set-bot or rotate-token")
                api_id = int(input("Telegram api_id: "))
                api_hash = getpass("Telegram api_hash: ")
                store.save(
                    Credentials(
                        api_id=api_id,
                        api_hash=api_hash,
                        mcp_token=secrets.token_urlsafe(32),
                    )
                )
                print("Credentials saved. Run serve and open the setup web page.")
                return 0
            credentials = store.load()
            if args.command == "login":
                asyncio.run(login(store, credentials))
            elif args.command == "set-bot":
                token = getpass("BotFather token: ")
                asyncio.run(set_bot(store, credentials, token))
            elif args.command == "rotate-token":
                store.save(
                    Credentials(
                        api_id=credentials.api_id,
                        api_hash=credentials.api_hash,
                        mcp_token=secrets.token_urlsafe(32),
                        bot_token=credentials.bot_token,
                    )
                )
                print("MCP token rotated. Run show-token and update all clients before restart.")
            elif args.command == "serve":
                serve(store, credentials)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Cancelled.", file=sys.stderr)
        return 130
    except GatewayError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValidationError, ValueError):
        print(
            "Invalid configuration or input. Check the command and configuration format.",
            file=sys.stderr,
        )
        return 1
    except LocalError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print(
            "Operation failed. Check connectivity and private state permissions.", file=sys.stderr
        )
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
