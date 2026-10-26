"""Persistent per-account pacing for background Telegram reads."""

import asyncio
import math
import time
from contextlib import asynccontextmanager

from tg_mcp.errors import GatewayError

SCHEMA = """
CREATE TABLE IF NOT EXISTS rag_loading (
    account TEXT PRIMARY KEY,
    interval REAL NOT NULL DEFAULT 2,
    next_request REAL NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0,
    stable_since REAL NOT NULL DEFAULT 0,
    last_success REAL NOT NULL DEFAULT 0,
    last_limited REAL NOT NULL DEFAULT 0,
    limits INTEGER NOT NULL DEFAULT 0
);
"""
MIN_INTERVAL = 2.0
MAX_INTERVAL = 60.0
STABLE_SECONDS = 7200
MAX_IDLE_SECONDS = 600


class AdaptiveLoading:
    def __init__(self, archive, account, *, clock=time.time, sleep=asyncio.sleep):
        self.archive, self.account = archive, account
        self.clock, self.sleep = clock, sleep
        self.lock = asyncio.Lock()

    def state(self):
        with self.archive.connect() as db:
            row = db.execute(
                "SELECT * FROM rag_loading WHERE account=?", (self.account,)
            ).fetchone()
        return (
            dict(row)
            if row
            else {
                "account": self.account,
                "interval": MIN_INTERVAL,
                "next_request": 0,
                "cooldown_until": 0,
                "stable_since": 0,
                "last_success": 0,
                "last_limited": 0,
                "limits": 0,
            }
        )

    def save(self, state):
        with self.archive.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO rag_loading VALUES(?,?,?,?,?,?,?,?)",
                tuple(
                    state[key]
                    for key in (
                        "account",
                        "interval",
                        "next_request",
                        "cooldown_until",
                        "stable_since",
                        "last_success",
                        "last_limited",
                        "limits",
                    )
                ),
            )

    @asynccontextmanager
    async def request(self, *, wait=False):
        # Background discovery, history and media queue fairly on this shared gate.
        if self.lock.locked() and not wait:
            raise GatewayError("load_paused", "Background loading is already in progress.", 5)
        async with self.lock:
            state = self.state()
            remaining = max(state["next_request"], state["cooldown_until"]) - self.clock()
            if remaining > MAX_INTERVAL:
                raise GatewayError(
                    "load_paused", "Background loading is scheduled later.", math.ceil(remaining)
                )
            if remaining > 0:
                await self.sleep(remaining)
            try:
                yield state["interval"]
            except GatewayError as exc:
                if exc.code == "rate_limited":
                    stamp = self.clock()
                    state["interval"] = min(MAX_INTERVAL, state["interval"] * 2)
                    state["cooldown_until"] = stamp + max(exc.retry_after or 0, state["interval"])
                    state["last_limited"] = stamp
                    state["stable_since"] = 0
                    state["limits"] += 1
                raise
            else:
                stamp = self.clock()
                if not state["stable_since"] or stamp - state["last_success"] > MAX_IDLE_SECONDS:
                    state["stable_since"] = stamp
                elif stamp - state["stable_since"] >= STABLE_SECONDS:
                    state["interval"] = max(MIN_INTERVAL, state["interval"] * 0.8)
                    state["stable_since"] = stamp
                state["last_success"] = stamp
            finally:
                state["next_request"] = self.clock() + state["interval"]
                self.save(state)
