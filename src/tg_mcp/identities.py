"""Persistent multi-account and multi-bot identity catalog."""

import base64
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from tg_mcp.errors import LocalError


def new_identity_id(prefix: Literal["acct", "bot"]) -> str:
    suffix = base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=").lower()
    return f"{prefix}_{suffix}"


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, hide_input_in_errors=True)
    label: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    telegram_id: str | None = Field(default=None, pattern=r"^-?[1-9][0-9]{0,18}$")
    username: str | None = Field(default=None, max_length=64)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(char) < 32 for char in cleaned):
            raise ValueError("Identity label must contain visible characters")
        return cleaned


class AccountRecord(_Record):
    account_id: str = Field(pattern=r"^acct_[a-z2-7]{16}$")
    setup_complete: bool = True


class BotRecord(_Record):
    bot_id: str = Field(pattern=r"^bot_[a-z2-7]{16}$")
    token: SecretStr


class IdentityDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2] = 2
    accounts: list[AccountRecord] = Field(default_factory=list)
    bots: list[BotRecord] = Field(default_factory=list)


class IdentityCatalog:
    def __init__(self, store, document: IdentityDocument):
        self.store = store
        self.document = document

    @classmethod
    def load(cls, store, credentials) -> "IdentityCatalog":
        document = store.load_identities() or store.migrate_legacy(credentials)
        changed = False
        for account in document.accounts:
            if "setup_complete" not in account.model_fields_set and account.telegram_id is None:
                account.setup_complete = False
                changed = True
        catalog = cls(store, document)
        if changed:
            catalog.save()
        return catalog

    def _unique_label(self, label: str, records: list[_Record], exclude: str | None = None) -> None:
        candidate = label.strip().casefold()
        for record in records:
            record_id = getattr(record, "account_id", getattr(record, "bot_id", None))
            if record_id != exclude and record.label.casefold() == candidate:
                raise LocalError("An identity with this label already exists")

    def save(self) -> None:
        self.store.save_identities(self.document)

    def add_account(self, label: str | None = None) -> AccountRecord:
        account_id = new_identity_id("acct")
        final_label = label if label is not None else f"Pending {account_id[-6:]}"
        self._unique_label(final_label, self.document.accounts)
        account = AccountRecord(
            account_id=account_id,
            label=final_label,
            setup_complete=label is not None,
        )
        self.document.accounts.append(account)
        self.save()
        return account

    def add_bot(self, label: str, token: str, telegram_id: str, username: str | None) -> BotRecord:
        self._unique_label(label, self.document.bots)
        bot = BotRecord(
            bot_id=new_identity_id("bot"),
            label=label,
            token=token,
            telegram_id=telegram_id,
            username=username,
        )
        self.document.bots.append(bot)
        self.save()
        return bot

    def account(self, account_id: str) -> AccountRecord:
        for account in self.document.accounts:
            if account.account_id == account_id:
                return account
        raise LocalError("Account identity not found")

    def bot(self, bot_id: str) -> BotRecord:
        for bot in self.document.bots:
            if bot.bot_id == bot_id:
                return bot
        raise LocalError("Bot identity not found")

    def rename_account(self, account_id: str, label: str) -> AccountRecord:
        account = self.account(account_id)
        self._unique_label(label, self.document.accounts, account_id)
        account.label = label
        self.save()
        return account

    def rename_bot(self, bot_id: str, label: str) -> BotRecord:
        bot = self.bot(bot_id)
        self._unique_label(label, self.document.bots, bot_id)
        bot.label = label
        self.save()
        return bot
