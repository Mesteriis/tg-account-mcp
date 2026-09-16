import json
import os
import stat

import pytest

from tg_mcp.config import Credentials
from tg_mcp.errors import LocalError
from tg_mcp.identities import IdentityCatalog
from tg_mcp.storage import StateStore


def credentials(bot=False):
    return Credentials(
        api_id=12345,
        api_hash="a" * 32,
        mcp_token="x" * 43,
        bot_token="123:" + "b" * 30 if bot else None,
    )


def test_empty_catalog_and_stable_ids(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(credentials())
    catalog = IdentityCatalog.load(store, store.load())
    assert catalog.document.schema_version == 2
    assert catalog.document.accounts == []
    account = catalog.add_account("Personal")
    bot = catalog.add_bot("Assistant", "123:" + "c" * 30, "123", "helper")
    assert account.account_id.startswith("acct_")
    assert account.setup_complete is True
    assert bot.bot_id.startswith("bot_")
    assert "c" * 30 not in repr(bot)
    assert StateStore(store.root).load_identities().accounts[0].account_id == account.account_id


def test_labels_are_unique_per_identity_kind(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(credentials())
    catalog = IdentityCatalog.load(store, store.load())
    catalog.add_account("Work")
    with pytest.raises(LocalError, match="already exists"):
        catalog.add_account(" work ")
    with pytest.raises(ValueError):
        catalog.add_account("\n")


def test_legacy_session_and_bot_migrate_once(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(credentials(bot=True))
    store.prepare_session()
    store.session_path.write_bytes(b"legacy-session")
    os.chmod(store.session_path, 0o600)
    first = IdentityCatalog.load(store, store.load())
    assert len(first.document.accounts) == 1
    assert len(first.document.bots) == 1
    account = first.document.accounts[0]
    target = store.account_session_path(account.account_id)
    assert target.read_bytes() == b"legacy-session"
    assert not store.session_path.exists()
    assert store.load().bot_token is None
    second = IdentityCatalog.load(store, store.load())
    assert [item.account_id for item in second.document.accounts] == [account.account_id]
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert account.setup_complete is False


def test_failed_identity_write_keeps_legacy_source(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state")
    store.save(credentials())
    store.prepare_session()
    store.session_path.write_bytes(b"source")

    def fail(document):
        raise OSError("disk full")

    monkeypatch.setattr(store, "save_identities", fail)
    with pytest.raises(OSError):
        IdentityCatalog.load(store, store.load())
    assert store.session_path.read_bytes() == b"source"


def test_unsafe_identity_file_rejected(tmp_path):
    store = StateStore(tmp_path / "state")
    store.save(credentials())
    path = store.root / "identities.json"
    path.write_text(json.dumps({"schema_version": 2, "accounts": [], "bots": []}))
    os.chmod(path, 0o644)
    with pytest.raises(LocalError, match="0600"):
        store.load_identities()


def test_account_path_rejects_traversal(tmp_path):
    store = StateStore(tmp_path / "state")
    with pytest.raises(LocalError, match="account ID"):
        store.account_session_path("../secret")
