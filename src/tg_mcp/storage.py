"""Private local state, identity documents and an exclusive process lock."""

import fcntl
import json
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from tg_mcp.config import Credentials
from tg_mcp.errors import LocalError
from tg_mcp.identities import AccountRecord, BotRecord, IdentityDocument, new_identity_id


class StateStore:
    def __init__(self, root: Path):
        self.root = root.absolute()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check_directory(self.root, "State")

    def _check_directory(self, path: Path, label: str) -> None:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise LocalError(f"{label} must be an owned, non-symlink directory")
        if stat.S_IMODE(info.st_mode) != 0o700:
            raise LocalError(f"{label} directory must have permissions 0700")

    @property
    def session_path(self) -> Path:
        """Legacy single-account session path."""
        return self.root / "account.session"

    @property
    def accounts_dir(self) -> Path:
        path = self.root / "accounts"
        path.mkdir(mode=0o700, exist_ok=True)
        self._check_directory(path, "Accounts")
        return path

    def account_session_path(self, account_id: str) -> Path:
        if not re.fullmatch(r"acct_[a-z2-7]{16}", account_id):
            raise LocalError("Invalid account ID")
        return self.accounts_dir / f"{account_id}.session"

    def _check_file(self, path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise LocalError("State file must be owned, regular and not linked")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise LocalError("State file must have permissions 0600")

    def _open_private(self, path: Path, flags: int) -> int:
        self._check_file(path)
        return os.open(path, flags | os.O_NOFOLLOW, 0o600)

    def open_private(self, path: Path, flags: int) -> int:
        """Open an owned state file without following links."""
        if path.parent != self.root:
            raise LocalError("State file is outside private state")
        return self._open_private(path, flags)

    def prepare_session(self, path: Path | None = None) -> Path:
        path = path or self.session_path
        if path.parent not in (self.root, self.accounts_dir):
            raise LocalError("Session path is outside private state")
        for candidate in path.parent.glob(f"{path.name}*"):
            self._check_file(candidate)
        fd = self._open_private(path, os.O_CREAT | os.O_RDWR)
        os.close(fd)
        return path

    @contextmanager
    def lock(self) -> Iterator[None]:
        fd = self._open_private(self.root / ".lock", os.O_CREAT | os.O_RDWR)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LocalError(
                    "Telegram state is already in use; stop the service first"
                ) from None
            yield
        finally:
            os.close(fd)

    def _atomic_json(self, path: Path, data: dict) -> None:
        self._check_file(path)
        fd, name = tempfile.mkstemp(prefix=f".{path.stem}-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    def write_private_json(self, path: Path, data: dict) -> None:
        """Atomically replace a JSON document in the private state directory."""
        if path.parent != self.root:
            raise LocalError("State file is outside private state")
        self._atomic_json(path, data)

    def read_private_json(self, path: Path) -> dict:
        """Read one owned JSON document from the private state directory."""
        if path.parent != self.root:
            raise LocalError("State file is outside private state")
        fd = self._open_private(path, os.O_RDONLY)
        try:
            with os.fdopen(fd) as stream:
                value = json.load(stream)
        except (OSError, ValueError, TypeError):
            raise LocalError("Invalid private state document") from None
        if not isinstance(value, dict):
            raise LocalError("Invalid private state document")
        return value

    def load(self) -> Credentials:
        path = self.root / "credentials.json"
        try:
            fd = self._open_private(path, os.O_RDONLY)
        except FileNotFoundError:
            raise LocalError("Credentials missing; run tg-mcp setup first") from None
        try:
            with os.fdopen(fd) as stream:
                return Credentials.model_validate(json.load(stream))
        except (ValueError, ValidationError):
            raise LocalError("Invalid credentials file; reconfigure using the CLI") from None

    def save(self, credentials: Credentials) -> None:
        data = {
            "api_id": credentials.api_id,
            "api_hash": credentials.api_hash.get_secret_value(),
            "mcp_token": credentials.mcp_token.get_secret_value(),
            "bot_token": credentials.bot_token.get_secret_value()
            if credentials.bot_token
            else None,
        }
        self._atomic_json(self.root / "credentials.json", data)

    def load_identities(self) -> IdentityDocument | None:
        path = self.root / "identities.json"
        if not path.exists():
            return None
        fd = self._open_private(path, os.O_RDONLY)
        try:
            with os.fdopen(fd) as stream:
                return IdentityDocument.model_validate(json.load(stream))
        except (ValueError, ValidationError):
            raise LocalError("Invalid identities file") from None

    def save_identities(self, document: IdentityDocument) -> None:
        data = document.model_dump(mode="json")
        for bot, encoded in zip(document.bots, data["bots"], strict=True):
            encoded["token"] = bot.token.get_secret_value()
        self._atomic_json(self.root / "identities.json", data)

    def migrate_legacy(self, credentials: Credentials) -> IdentityDocument:
        accounts: list[AccountRecord] = []
        bots: list[BotRecord] = []
        copied: list[tuple[Path, Path]] = []
        legacy_files = list(self.root.glob("account.session*"))
        if legacy_files:
            account = AccountRecord(
                account_id=new_identity_id("acct"),
                label="Primary",
                setup_complete=False,
            )
            accounts.append(account)
            destination = self.account_session_path(account.account_id)
            for source in legacy_files:
                self._check_file(source)
                suffix = source.name.removeprefix("account.session")
                target = destination.with_name(destination.name + suffix)
                shutil.copy2(source, target, follow_symlinks=False)
                os.chmod(target, 0o600)
                copied.append((source, target))
        if credentials.bot_token:
            bots.append(
                BotRecord(
                    bot_id=new_identity_id("bot"), label="Primary bot", token=credentials.bot_token
                )
            )
        document = IdentityDocument(accounts=accounts, bots=bots)
        try:
            self.save_identities(document)
        except Exception:
            for _, target in copied:
                target.unlink(missing_ok=True)
            raise
        for source, _ in copied:
            source.unlink(missing_ok=True)
        if credentials.bot_token:
            self.save(
                Credentials(
                    api_id=credentials.api_id,
                    api_hash=credentials.api_hash,
                    mcp_token=credentials.mcp_token,
                )
            )
        return document
