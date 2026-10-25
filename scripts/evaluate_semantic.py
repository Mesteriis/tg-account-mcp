"""Small, synthetic multilingual retrieval smoke; never reads connected Telegram accounts."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from time import perf_counter

from tg_mcp.archive import ArchiveStore
from tg_mcp.config import Settings
from tg_mcp.errors import GatewayError
from tg_mcp.semantic import OllamaEmbeddings, SemanticIndex
from tg_mcp.storage import StateStore

DOCUMENTS = [
    "Историю переписки сохраняем локально в SQLite с версиями правок.",
    "Задания обрабатываем через очередь с повторными попытками после сбоя.",
    "Голосовые сообщения распознаём и сохраняем расшифровки для поиска.",
    "Доступ агента ограничен выбранным проектом и разрешёнными чатами.",
    "При удалении исходника очищаем связанные векторы и производные заметки.",
]
QUESTIONS = [
    ("Как превратить аудиосообщения в текст?", "3"),
    ("Как предотвратить утечку сведений между разными рабочими пространствами?", "4"),
    ("Что происходит с embeddings после стирания оригинала?", "5"),
]


async def evaluate(url: str, model: str, dimensions: int) -> dict:
    started = perf_counter()
    with tempfile.TemporaryDirectory(prefix="tg-mcp-synthetic-eval-") as folder:
        settings = Settings(
            state_dir=Path(folder),
            allowed_hosts=["localhost"],
            embedding_url=url,
            embedding_model=model,
            embedding_dimensions=dimensions,
        )
        archive = ArchiveStore(StateStore(settings.state_dir))
        account, chat = "acct_aaaaaaaaaaaaaaaa", "123"
        archive.configure(account, chat, "Synthetic evaluation", enabled=True, retain_deleted=False)
        archive.ingest_page(
            account,
            chat,
            [{"id": str(i), "text": text} for i, text in enumerate(DOCUMENTS, 1)],
            None,
        )
        index = SemanticIndex(archive, OllamaEmbeddings(settings))
        indexed = await index.index("archive", account, chat)
        cases = []
        for question, expected in QUESTIONS:
            result = await index.search("archive", account, chat, question, limit=1)
            actual = result["results"][0]["id"] if result["results"] else None
            cases.append({"expected_id": expected, "actual_id": actual, "pass": actual == expected})
        return {
            "synthetic_only": True,
            "documents": len(DOCUMENTS),
            "cases": cases,
            "top1_correct": sum(case["pass"] for case in cases),
            "total": len(cases),
            "model": model,
            "dimensions": dimensions,
            "model_key": indexed["model_key"],
            "elapsed_seconds": round(perf_counter() - started, 2),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dimensions", type=int, default=256)
    args = parser.parse_args()
    try:
        report = asyncio.run(evaluate(args.url, args.model, args.dimensions))
    except GatewayError as exc:
        print(json.dumps({"synthetic_only": True, "error": exc.as_dict()}, ensure_ascii=False))
        raise SystemExit(2) from None
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["top1_correct"] == report["total"] else 1)
