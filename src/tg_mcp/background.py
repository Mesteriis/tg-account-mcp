"""Opt-in all-account discovery and fair, restart-safe local embedding queues."""

import asyncio
import contextlib
import logging
import sqlite3
from time import monotonic

from tg_mcp.archive import now
from tg_mcp.errors import GatewayError, LocalError
from tg_mcp.rag_metrics import SAMPLE_INTERVAL, RAGMetrics
from tg_mcp.semantic import WHITESPACE, OllamaEmbeddings, SemanticIndex


class BackgroundRAG:
    def __init__(self, manager, settings):
        self.manager = manager
        self.archive = manager.archive
        self.settings = settings
        self.provider = OllamaEmbeddings(settings)
        self.index = SemanticIndex(self.archive, self.provider)
        self.tasks = []
        self.last_discovery = None
        self.last_index = None
        self.errors = {"discovery": None, "index": None}
        self.model_key = None
        self.indexed = 0
        self.archive_indexed = 0
        self.metrics = RAGMetrics()
        self._served = {}
        self._retry = {}
        self._discovery_errors = {}
        self._last_warm = 0

    def start(self):
        self.tasks = [
            asyncio.create_task(self.discovery_loop(), name="tg-mcp-rag-discovery"),
            asyncio.create_task(self.index_loop(), name="tg-mcp-rag-index"),
            asyncio.create_task(self.metrics_loop(), name="tg-mcp-rag-metrics"),
        ]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.tasks = []

    def ready_accounts(self):
        return {
            a["account_id"]
            for a in self.manager.list_accounts()
            if a["status"] == "ready" and a.get("enabled", True)
        }

    async def discover(self):
        retry = getattr(self.manager, "retry_failed_accounts", None)
        if retry is not None:
            await retry()
        for account in sorted(self.ready_accounts()):
            if self._retry.get(account, 0) > monotonic():
                continue
            try:
                gateway = await self.manager.user_gateway(account)
                await gateway.discover_archives()
                self._discovery_errors.pop(account, None)
            except GatewayError as exc:
                if exc.code != "load_paused":
                    self._discovery_errors[account] = exc.code
                self._retry[account] = monotonic() + max(60, exc.retry_after or 0)
        ready = self.ready_accounts()
        self._discovery_errors = {
            account: code for account, code in self._discovery_errors.items() if account in ready
        }
        self.errors["discovery"] = next(iter(self._discovery_errors.values()), None)
        self.last_discovery = now()

    def jobs(self, key):
        ready = self.ready_accounts()
        with self.archive.connect() as db:
            chats = db.execute(
                "SELECT c.account,c.chat FROM chats c WHERE c.enabled=1 AND EXISTS "
                "(SELECT 1 FROM messages m WHERE m.account=c.account AND m.chat=c.chat "
                "AND m.deleted_at IS NULL AND trim(m.text,?)!='' AND NOT EXISTS "
                "(SELECT 1 FROM message_vectors v WHERE v.message=m.rowid AND v.model=?))",
                (WHITESPACE, key),
            ).fetchall()
            projects = db.execute(
                "SELECT p.account,p.id FROM projects p WHERE EXISTS "
                "(SELECT 1 FROM project_memories m WHERE m.project=p.id AND m.state='approved' "
                "AND NOT EXISTS (SELECT 1 FROM memory_vectors v "
                "WHERE v.memory=m.id AND v.model=?))",
                (key,),
            ).fetchall()
        return [("archive", r[0], r[1]) for r in chats if r[0] in ready] + [
            ("memory", r[0], r[1]) for r in projects if r[0] in ready
        ]

    async def index_once(self):
        key = await self.provider.model_key()
        self.model_key = key
        jobs = self.jobs(key)
        pending = set(jobs)
        self._served = {job: stamp for job, stamp in self._served.items() if job in pending}
        if not jobs:
            if monotonic() - self._last_warm > 300:
                await self.provider.embed(["Local background embedding readiness probe"], key)
                self._last_warm = monotonic()
            return False
        job = min(jobs, key=lambda item: (self._served.get(item, 0), item))
        self._served[job] = monotonic()
        result = await self.index.index(*job, limit=self.settings.rag_batch_size)
        self.model_key = result["model_key"]
        self.indexed += result["indexed"]
        if job[0] == "archive":
            self.archive_indexed += result["indexed"]
        self.last_index = now()
        self._last_warm = monotonic()
        return True

    async def discovery_loop(self):
        while True:
            try:
                await self.discover()
            except (OSError, sqlite3.Error, LocalError, GatewayError):
                self.errors["discovery"] = "discovery_unavailable"
                logging.getLogger("tg_mcp").error("Background RAG discovery failed")
            except Exception:
                self.errors["discovery"] = "worker_failed"
                logging.getLogger("tg_mcp").error("Background RAG discovery worker failed")
            await asyncio.sleep(self.settings.rag_discovery_interval)

    async def index_loop(self):
        failures = 0
        while True:
            delay = self.settings.rag_index_interval
            try:
                async with asyncio.timeout(45):
                    worked = await self.index_once()
                if worked is False:
                    delay = max(delay, 1)
                failures = 0
                self.errors["index"] = None
            except GatewayError as exc:
                failures += 1
                self.errors["index"] = exc.code
            except (OSError, sqlite3.Error, LocalError, TimeoutError):
                failures += 1
                self.errors["index"] = "index_unavailable"
            except Exception:
                failures += 1
                self.errors["index"] = "worker_failed"
                logging.getLogger("tg_mcp").error("Background RAG index worker failed")
            if failures:
                delay = max(delay, min(300, 5 * 2 ** min(failures, 6)))
            await asyncio.sleep(delay)

    def sample_metrics(self):
        if self.model_key is None:
            return
        with self.archive.connect() as db:
            chats = db.execute("SELECT account,chat FROM chats WHERE enabled=1").fetchall()
            row = db.execute(
                "SELECT count(*) AS eligible,coalesce(sum(EXISTS "
                "(SELECT 1 FROM message_vectors v WHERE v.message=m.rowid AND v.model=?)),0) "
                "AS indexed FROM messages m JOIN chats c USING(account,chat) "
                "WHERE c.enabled=1 AND m.deleted_at IS NULL AND trim(m.text,?)!=''",
                (self.model_key, WHITESPACE),
            ).fetchone()
        scope = self.metrics_scope(chats)
        self.metrics.observe(
            monotonic(), scope, row["eligible"], row["indexed"], self.archive_indexed
        )

    def metrics_scope(self, chats):
        return (
            self.model_key,
            tuple(sorted((r["account"], r["chat"]) for r in chats)),
            tuple(sorted(self.ready_accounts())),
        )

    async def metrics_loop(self):
        while True:
            try:
                self.sample_metrics()
            except (OSError, sqlite3.Error, LocalError, GatewayError):
                logging.getLogger("tg_mcp").error("Background RAG metrics sample failed")
            await asyncio.sleep(SAMPLE_INTERVAL)

    def status(self, *, details=False):
        with self.archive.connect() as db:
            rows = db.execute(
                "SELECT c.account,c.chat,c.title,c.backfill_complete,c.last_sync,c.error,"
                "count(m.rowid) AS archived,"
                "sum(CASE WHEN trim(m.text,?)!='' THEN 1 ELSE 0 END) AS eligible,"
                "sum(CASE WHEN trim(m.text,?)!='' AND v.message IS NOT NULL "
                "THEN 1 ELSE 0 END) AS indexed "
                "FROM chats c LEFT JOIN messages m ON m.account=c.account AND m.chat=c.chat "
                "AND m.deleted_at IS NULL LEFT JOIN message_vectors v "
                "ON v.message=m.rowid AND v.model=? WHERE c.enabled=1 "
                "GROUP BY c.account,c.chat ORDER BY c.account,c.title,c.chat",
                (WHITESPACE, WHITESPACE, self.model_key),
            ).fetchall()
            loading = [dict(row) for row in db.execute("SELECT * FROM rag_loading")]
        chat_details = [dict(row) for row in rows]
        chats = len(chat_details)
        messages = sum(row["archived"] for row in chat_details)
        vectors = sum(row["indexed"] for row in chat_details)
        eligible = sum(row["eligible"] for row in chat_details)
        running = bool(self.tasks) and all(not t.done() for t in self.tasks)
        scope = self.metrics_scope(chat_details)
        throughput = self.metrics.snapshot(
            monotonic(),
            scope,
            eligible - vectors if self.model_key else None,
            paused=not running or bool(self.errors["index"]),
            blocked=bool({r["account"] for r in chat_details} - self.ready_accounts()),
        )
        return {
            "enabled": True,
            "running": running,
            "throughput": throughput,
            "ready_accounts": len(self.ready_accounts()),
            "selected_chats": chats,
            "archived_messages": messages,
            "indexed_messages": vectors,
            "indexed_this_process": self.indexed,
            "eligible_messages": eligible,
            "pending_messages": eligible - vectors if self.model_key else None,
            "history_complete_chats": sum(row["backfill_complete"] for row in chat_details),
            "never_synced_chats": sum(row["last_sync"] is None for row in chat_details),
            "chat_errors": sum(bool(row["error"]) for row in chat_details),
            **({"chats": chat_details} if details else {}),
            "loading": loading,
            "embedding_model": self.settings.embedding_model,
            "observed_at": now(),
            "last_discovery": self.last_discovery,
            "last_index": self.last_index,
            "last_error": self.errors["index"] or self.errors["discovery"],
            "errors": dict(self.errors),
            "pending_scopes": len(self.jobs(self.model_key)) if self.model_key else None,
            "accounts_waiting_retry": sum(until > monotonic() for until in self._retry.values()),
            "coverage": "observed_only",
        }
