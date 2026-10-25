"""Explicit, bounded local Ollama embeddings and scope-filtered cosine retrieval."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import string
from urllib.parse import urlsplit

import httpx

from tg_mcp.archive import ArchiveStore
from tg_mcp.errors import GatewayError
from tg_mcp.memory import content_hash

# Unicode whitespace accepted by str.strip(), also used by SQLite trim(text, ?).
WHITESPACE = (
    string.whitespace + "\x1c\x1d\x1e\x1f\x85\xa0\u1680\u2000\u2001\u2002\u2003"
    "\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
MAX_SCAN = 2_000
MAX_BODY = 4 * 1024 * 1024


def validate_local_url(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
    ):
        raise ValueError("Embedding URL must be a local Ollama origin")
    if parts.port is not None and not 1 <= parts.port <= 65535:
        raise ValueError("Invalid local embedding port")
    host = parts.hostname
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host or "")
        except ValueError:
            raise ValueError("Use a loopback or private numeric embedding address") from None
        allowed = any(
            address in ipaddress.ip_network(network)
            for network in (
                ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
                if address.version == 4
                else ["::1/128", "fc00::/7"]
            )
        )
        if not allowed or (address.is_unspecified or address.is_multicast or address.is_link_local):
            raise ValueError("Embedding address must be loopback or private")
    return value.rstrip("/")


def normalized(vector: list, dimensions: int | None = None) -> list[float]:
    if (
        not isinstance(vector, list)
        or not 1 <= len(vector) <= 4096
        or (dimensions is not None and len(vector) != dimensions)
        or any(
            type(v) not in (int, float) or abs(v) > 1e100 or not math.isfinite(v) for v in vector
        )
    ):
        raise GatewayError("invalid_embedding", "Embedding provider returned an invalid vector.")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise GatewayError("invalid_embedding", "Embedding provider returned an invalid vector.")
    return [v / norm for v in vector]


class OllamaEmbeddings:
    def __init__(self, settings):
        self.url = settings.embedding_url
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.enabled = bool(self.url and self.model)

    def require_enabled(self):
        if not self.enabled:
            raise GatewayError("semantic_disabled", "Configure a local embedding provider first.")

    async def _request(self, method: str, path: str, payload: dict | None = None):
        self.require_enabled()
        try:
            async with httpx.AsyncClient(
                timeout=30, trust_env=False, follow_redirects=False
            ) as http:
                async with http.stream(method, self.url + path, json=payload) as response:
                    if response.status_code != 200:
                        raise GatewayError(
                            "embedding_unavailable", "Local embedding request failed."
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BODY:
                            raise GatewayError(
                                "invalid_embedding", "Embedding response is too large."
                            )
                    return json.loads(body)
        except httpx.TimeoutException:
            raise GatewayError(
                "embedding_timeout",
                "Local embedding request timed out; warm the model "
                "or reduce the indexing batch size.",
            ) from None
        except (httpx.HTTPError, ValueError, TypeError):
            raise GatewayError(
                "embedding_unavailable", "Local embedding provider is unavailable."
            ) from None

    async def model_key(self) -> str:
        data = await self._request("GET", "/api/tags")
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise GatewayError("invalid_embedding", "Invalid embedding model catalog.")
        for model in data["models"]:
            if isinstance(model, dict) and model.get("name") == self.model:
                digest = model.get("digest")
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                    or not isinstance(model.get("size"), int)
                    or model["size"] <= 0
                    or not isinstance(model.get("details"), dict)
                    or model["details"].get("format") != "gguf"
                    or "cloud" in self.model.casefold()
                ):
                    raise GatewayError("invalid_embedding", "Select an installed local GGUF model.")
                return hashlib.sha256(
                    json.dumps(
                        [self.url, self.model, digest, self.dimensions, "plain-cosine-v1"]
                    ).encode()
                ).hexdigest()
        raise GatewayError(
            "embedding_model_missing", "Install the configured local embedding model."
        )

    async def embed(self, texts: list[str], model_key: str) -> list[list[float]]:
        if not 1 <= len(texts) <= 16 or any(not t.strip() or len(t) > 4096 for t in texts):
            raise GatewayError(
                "invalid_request", "Embed 1–16 nonempty texts of at most 4096 characters."
            )
        if await self.model_key() != model_key:
            raise GatewayError(
                "embedding_model_changed", "Model changed; restart indexing or search."
            )
        data = await self._request(
            "POST",
            "/api/embed",
            {
                "model": self.model,
                "input": texts,
                "truncate": False,
                "dimensions": self.dimensions,
            },
        )
        vectors = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise GatewayError("invalid_embedding", "Embedding provider returned an invalid batch.")
        result = [normalized(vector, self.dimensions) for vector in vectors]
        if await self.model_key() != model_key:
            raise GatewayError("embedding_model_changed", "Model changed during embedding.")
        return result


class SemanticIndex:
    def __init__(self, archive: ArchiveStore, provider: OllamaEmbeddings):
        self.archive = archive
        self.provider = provider

    @staticmethod
    def _scope(kind: str, account: str, target: str):
        if kind == "archive":
            return (
                "messages",
                "message_vectors",
                "message",
                "snapshot",
                "account=? AND chat=? AND deleted_at IS NULL AND trim(text,?)!=''",
                [account, target, WHITESPACE],
            )
        return (
            "project_memories",
            "memory_vectors",
            "memory",
            "text",
            "project=? AND state='approved' "
            "AND project IN (SELECT id FROM projects WHERE account=?)",
            [target, account],
        )

    async def index(self, kind: str, account: str, target: str, *, limit=16) -> dict:
        key = await self.provider.model_key()
        table, vectors, idcol, content, where, params = self._scope(kind, account, target)
        object_id = "rowid" if kind == "archive" else "id"
        with self.archive.connect() as db:
            # Edits invalidate vectors in SQLite triggers; one model digest is indexed at a time.
            rows = db.execute(
                f"SELECT * FROM {table} WHERE {where} AND {object_id} NOT IN "
                f"(SELECT {idcol} FROM {vectors} WHERE model=?) ORDER BY {object_id} LIMIT ?",
                [*params, key, limit + 1],
            ).fetchall()
        batch = rows[:limit]
        # rowid must be explicit in messages (stable across VACUUM).
        texts = [row["text"] for row in batch]
        embeddings = await self.provider.embed(texts, key) if texts else []
        saved = 0
        with self.archive.connect() as db:
            for row, vector in zip(batch, embeddings, strict=True):
                identifier = row[object_id]
                fresh = db.execute(
                    f"SELECT {content} FROM {table} WHERE {where} AND {object_id}=?",
                    [*params, identifier],
                ).fetchone()
                fingerprint = content_hash(row[content])
                if fresh is None or content_hash(fresh[content]) != fingerprint:
                    continue
                db.execute(
                    f"INSERT OR REPLACE INTO {vectors} VALUES(?,?,?,?)",
                    (identifier, key, fingerprint, json.dumps(normalized(vector))),
                )
                saved += 1
        return {
            "indexed": saved,
            "skipped_changed": len(batch) - saved,
            "has_more": len(rows) > limit or saved < len(batch),
            "model_key": key,
        }

    async def search(self, kind: str, account: str, target: str, query: str, *, limit=10) -> dict:
        key = await self.provider.model_key()
        query_vector = normalized((await self.provider.embed([query], key))[0])
        table, vectors, idcol, content, where, params = self._scope(kind, account, target)
        object_id = "rowid" if kind == "archive" else "id"
        order = (
            "d.date DESC,CAST(d.mid AS INTEGER) DESC"
            if kind == "archive"
            else "d.created_at DESC,d.id DESC"
        )
        with self.archive.connect() as db:
            rows = db.execute(
                f"SELECT d.*,v.vector,v.fingerprint FROM {table} d JOIN {vectors} v "
                f"ON d.{object_id}=v.{idcol} WHERE {where} AND v.model=? "
                f"ORDER BY {order} LIMIT ?",
                [*params, key, MAX_SCAN + 1],
            ).fetchall()
            total = db.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]
        ranked = []
        for row in rows[:MAX_SCAN]:
            if content_hash(row[content]) != row["fingerprint"]:
                continue
            vector = normalized(json.loads(row["vector"]), len(query_vector))
            score = sum(a * b for a, b in zip(query_vector, vector, strict=True))
            if kind == "archive":
                item = {**json.loads(row["snapshot"]), "account_id": account, "chat_id": target}
            else:
                item = {"memory_id": row["id"], "text": row["text"], "state": row["state"]}
            ranked.append({**item, "score": score})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return {
            "results": ranked[:limit],
            "model_key": key,
            "indexed_scanned": len(ranked),
            "eligible_count": total,
            "partial": len(rows) > MAX_SCAN or len(ranked) < total,
        }
