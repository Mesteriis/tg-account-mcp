import os
import secrets
import stat

import httpx
import pytest

from tg_mcp.auth import BearerAuth
from tg_mcp.config import Credentials
from tg_mcp.storage import StateStore
from tg_mcp.telegram import make_client

TOKEN = secrets.token_urlsafe(32)


async def downstream(scope, receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


@pytest.fixture
async def client():
    app = BearerAuth(downstream, TOKEN, ["mcp.test"], ["https://mcp.test"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://mcp.test"
    ) as client:
        yield client


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE", "OPTIONS"])
async def test_every_method_requires_token(client, method):
    response = await client.request(method, "/mcp")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_valid_and_invalid_token(client):
    for token, status in [(TOKEN, 204), ("wrong", 401), ("", 401)]:
        response = await client.post("/mcp", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == status
        assert TOKEN not in response.text


async def test_duplicate_credentials_are_rejected(client):
    response = await client.post("/mcp", headers=[("Authorization", f"Bearer {TOKEN}")] * 2)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "headers", [{"Host": "evil.test"}, {"Origin": "https://evil.test"}, {"Origin": "null"}]
)
async def test_host_origin_boundary(client, headers):
    response = await client.post("/mcp", headers={"Authorization": f"Bearer {TOKEN}", **headers})
    assert response.status_code == 403


async def test_allowed_origin(client):
    response = await client.post(
        "/mcp", headers={"Authorization": f"Bearer {TOKEN}", "Origin": "https://mcp.test"}
    )
    assert response.status_code == 204


async def test_loopback_setup_accepts_its_own_browser_origin():
    app = BearerAuth(
        downstream,
        TOKEN,
        ["127.0.0.1:8765"],
        [],
        bind_host="127.0.0.1",
    )
    transport = httpx.ASGITransport(app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as local:
        response = await local.post(
            "/setup/api/accounts/example/password",
            headers={"Origin": "http://127.0.0.1:8765"},
        )
        rejected = await local.post(
            "/setup/api/accounts/example/password",
            headers={"Origin": "https://evil.test"},
        )

    assert response.status_code == 204
    assert rejected.status_code == 403


async def test_lifespan_passthrough():
    scopes = []

    async def life(scope, receive, send):
        scopes.append(scope["type"])

    await BearerAuth(life, TOKEN, ["mcp.test"], [])({"type": "lifespan"}, None, None)
    assert scopes == ["lifespan"]


def credentials():
    return Credentials(api_id=12345, api_hash="a" * 32, mcp_token=TOKEN)


def test_private_atomic_state_and_session(tmp_path):
    store = StateStore(tmp_path / "private")
    with store.lock():
        store.save(credentials())
        store.prepare_session()
        assert store.load().mcp_token.get_secret_value() == TOKEN
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    for name in ("credentials.json", "account.session", ".lock"):
        assert stat.S_IMODE((store.root / name).stat().st_mode) == 0o600
    assert TOKEN not in repr(store.load())


def test_session_lock_is_exclusive(tmp_path):
    store = StateStore(tmp_path / "private")
    with store.lock():
        with pytest.raises(RuntimeError, match="already in use"):
            with StateStore(store.root).lock():
                pytest.fail("Lock acquired twice")


def test_state_symlink_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(actual)
    with pytest.raises(RuntimeError, match="directory"):
        StateStore(link)


def test_credential_symlink_rejected(tmp_path):
    store = StateStore(tmp_path / "private")
    target = tmp_path / "target"
    target.write_text("do not change")
    (store.root / "credentials.json").symlink_to(target)
    with pytest.raises(RuntimeError, match="file"):
        store.save(credentials())
    assert target.read_text() == "do not change"


def test_public_state_and_files_rejected(tmp_path):
    root = tmp_path / "public"
    root.mkdir(mode=0o755)
    with pytest.raises(RuntimeError, match="0700"):
        StateStore(root)
    os.chmod(root, 0o700)
    store = StateStore(root)
    store.save(credentials())
    os.chmod(root / "credentials.json", 0o644)
    with pytest.raises(RuntimeError, match="0600"):
        store.load()


async def test_telethon_session_persists_across_client_instances(tmp_path):
    from telethon.crypto import AuthKey

    store = StateStore(tmp_path / "private")
    with store.lock():
        first = make_client(store, credentials())
        first.session.auth_key = AuthKey(b"x" * 256)
        first.session.save()
        first.session.close()
    with store.lock():
        second = make_client(store, credentials())
        assert second.session.auth_key.key == b"x" * 256
        second.session.close()
    assert stat.S_IMODE(store.session_path.stat().st_mode) == 0o600
