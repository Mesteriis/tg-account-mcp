"""Bounded local-first retrieval with explicit provenance and Telegram fallback."""

import asyncio
from contextlib import nullcontext
from datetime import date

from tg_mcp.errors import GatewayError


class MessageRetrieval:
    def __init__(self, manager, archive, semantic):
        self.manager, self.archive, self.semantic = manager, archive, semantic

    def coverage(self, account, chat):
        with self.archive.connect() as db:
            where, params = "account=?", [account]
            if chat is not None:
                where += " AND chat=?"
                params.append(chat)
            rows = db.execute(
                "SELECT enabled,backfill_complete,last_sync,error FROM chats WHERE " + where,
                params,
            ).fetchall()
        complete = (
            bool(rows)
            and all(r["enabled"] and r["backfill_complete"] and not r["error"] for r in rows)
            and not self.archive.capture_failed
        )
        return {
            "known_chats": len(rows),
            "history_complete_chats": sum(r["backfill_complete"] for r in rows),
            "known_history_complete": complete,
            "dialog_inventory": "unknown" if chat is None else "single_chat",
            "coverage": "observed_only",
        }

    async def search(
        self,
        account,
        query,
        *,
        chat=None,
        limit=20,
        telegram="auto",
        include_context=False,
        date_from=None,
        date_to=None,
    ):
        if not query.strip():
            raise GatewayError("invalid_request", "Search query must contain words.")
        try:
            start = date.fromisoformat(date_from) if date_from else None
            end = date.fromisoformat(date_to) if date_to else None
            if start and end and start > end:
                raise ValueError
        except ValueError:
            raise GatewayError("invalid_request", "Invalid UTC date range.") from None
        filters = {"date_from": date_from, "date_to": date_to}
        coverage = self.coverage(account, chat)
        warnings, candidates, stages = [], {}, []

        def merge(messages, source):
            for rank, message in enumerate(messages, 1):
                if message.get("account_id") not in (None, account) or (
                    chat is not None and message.get("chat_id") not in (None, chat)
                ):
                    warnings.append({"source": source, "code": "invalid_source_scope"})
                    continue
                peer = chat if chat is not None else message.get("chat_id")
                if peer is None or message.get("id") is None:
                    continue
                key = (str(peer), str(message["id"]))
                old = candidates.get(key)
                sources = list(old["matched_by"]) if old else []
                if source not in sources:
                    sources.append(source)
                score = (old["retrieval_score"] if old else 0) + 1 / (60 + rank)
                # A live snapshot takes precedence over archived content for the same ID.
                item = dict(message) if old is None or source == "telegram" else dict(old)
                if source == "semantic":
                    item["semantic_score"] = message["score"]
                item.pop("score", None)
                if source == "telegram" and old and old.get("text") != item.get("text"):
                    item["local_snapshot_stale"] = True
                    item.pop("semantic_score", None)
                item.update(
                    account_id=account,
                    chat_id=str(peer),
                    matched_by=sources,
                    retrieval_score=score,
                    source="telegram" if source == "telegram" else "local_archive",
                )
                candidates[key] = item

        lexical = {"messages": [], "has_more": False}
        if coverage["known_chats"]:
            lexical = self.archive.search(account, chat, query, limit=limit, **filters)
        merge(lexical["messages"], "keyword")
        stages.append("local_keyword")
        semantic = {"results": [], "partial": True, "indexed_scanned": 0}
        try:
            async with asyncio.timeout(8):
                semantic = await self.semantic.search(
                    "archive", account, chat, query, limit=limit, **filters
                )
            merge(semantic["results"], "semantic")
        except GatewayError as exc:
            warnings.append({"source": "local_semantic", "code": exc.code})
        except TimeoutError:
            warnings.append({"source": "local_semantic", "code": "timeout"})
        stages.append("local_semantic")
        incomplete = not coverage["known_history_complete"] or chat is None or semantic["partial"]
        reasons = []
        if incomplete:
            reasons.append("local_coverage_incomplete")
        if len(candidates) < limit:
            reasons.append("insufficient_local_results")
        if telegram == "always":
            reasons.append("freshness_requested")
        live = {"attempted": False, "succeeded": False, "next_cursor": None}
        if telegram != "never" and (reasons or telegram == "always"):
            live["attempted"] = True
            try:
                async with asyncio.timeout(15):
                    gateway = await self.manager.user_gateway(account)
                    loading = getattr(gateway, "loading", None)
                    async with loading.request() if loading else nullcontext():
                        page = (
                            await gateway.history(
                                chat, query=query, limit=min(limit, 99), **filters
                            )
                            if chat is not None
                            else await gateway.search_all(query, limit=min(limit, 99), **filters)
                        )
                merge(page["messages"], "telegram")
                live.update(succeeded=True, next_cursor=page.get("next_cursor"))
            except GatewayError as exc:
                warning = {"source": "telegram", "code": exc.code}
                if exc.retry_after is not None:
                    warning["retry_after_seconds"] = exc.retry_after
                warnings.append(warning)
            except TimeoutError:
                warnings.append({"source": "telegram", "code": "timeout"})
            stages.append("telegram")
        results = sorted(
            candidates.values(), key=lambda r: (-r["retrieval_score"], r["chat_id"], r["id"])
        )[:limit]
        context = None
        if include_context and results and telegram != "never":
            first = results[0]
            try:
                async with asyncio.timeout(8):
                    gateway = await self.manager.user_gateway(account)
                    loading = getattr(gateway, "loading", None)
                    async with loading.request() if loading else nullcontext():
                        context = await gateway.message_context(
                            first["chat_id"], first["id"], before=2, after=2
                        )
            except GatewayError as exc:
                warnings.append({"source": "context", "code": exc.code})
            except TimeoutError:
                warnings.append({"source": "context", "code": "timeout"})
        return {
            "account_id": account,
            "chat_id": chat,
            "results": results,
            "stages": stages,
            "local_coverage": coverage,
            "semantic_scanned": semantic["indexed_scanned"],
            "semantic_eligible": semantic.get("eligible_count"),
            "semantic_partial": semantic["partial"],
            "local_keyword_has_more": lexical["has_more"],
            "telegram": {
                **live,
                "reasons": reasons,
                "cursor_tool": "search_messages" if chat else "search_all_messages",
            },
            "partial": bool(
                incomplete
                or lexical["has_more"]
                or len(candidates) > limit
                or live["next_cursor"]
                or warnings
            ),
            "warnings": warnings,
            "context": context,
        }
